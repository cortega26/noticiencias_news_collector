"""
Article repository — focused CRUD, dedup, clustering, scoring, and publishing state.
"""

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
    cast,
)

from sqlalchemy import and_, desc, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, load_only
from sqlalchemy.orm.attributes import QueryableAttribute

from news_collector.config.settings import get_runtime_config
from news_collector.contracts import CollectorArticleModel, ScoringRequestModel
from news_collector.contracts.frontend_publication import (
    FRONTEND_REQUIRED_PUBLICATION_WORKFLOWS,
)
from news_collector.utils.dedupe import (
    duplication_confidence,
    generate_cluster_id,
    hamming_distance,
    normalize_article_text,
    sha256_hex,
    simhash64,
)
from news_collector.utils.logger import get_logger
from news_collector.utils.pydantic_compat import get_pydantic_module
from news_collector.utils.url_canonicalizer import canonicalize_url

from .models import PENDING_STATUS, PROCESSING_STATUS_VALUES, Article, ScoreLog

ValidationError = get_pydantic_module().ValidationError

SIMHASH_BITS = 64
SIMHASH_MASK = (1 << SIMHASH_BITS) - 1
SIMHASH_SIGN_BIT = 1 << (SIMHASH_BITS - 1)

logger = get_logger().create_module_logger(__name__)


# ---------------------------------------------------------------------------
# Pure helper functions (module-level for testability)
# ---------------------------------------------------------------------------


def ensure_timezone(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def simhash_normalize_unsigned(simhash_value: Optional[int]) -> Optional[int]:
    if simhash_value is None:
        return None
    return simhash_value & SIMHASH_MASK


def simhash_to_storage(simhash_value: Optional[int]) -> Optional[int]:
    if simhash_value is None:
        return None
    normalized = simhash_value & SIMHASH_MASK
    if normalized >= SIMHASH_SIGN_BIT:
        return normalized - (1 << SIMHASH_BITS)
    return normalized


def simhash_from_storage(simhash_value: Optional[int]) -> Optional[int]:
    if simhash_value is None:
        return None
    if simhash_value < 0:
        return simhash_value + (1 << SIMHASH_BITS)
    return simhash_value


def simhash_prefix_value(simhash_value: Optional[int]) -> Optional[int]:
    if simhash_value is None:
        return None
    normalized = simhash_value & SIMHASH_MASK
    return (normalized >> 48) & 0xFFFF


def time_distance_seconds(a: Optional[datetime], b: Optional[datetime]) -> float:
    if not a or not b:
        return float("inf")
    normalized_a = ensure_timezone(a)
    normalized_b = ensure_timezone(b)
    if normalized_a is None or normalized_b is None:
        return float("inf")
    return abs((normalized_a - normalized_b).total_seconds())


@dataclass(frozen=True)
class ArticleCursor:
    """Keyset-pagination cursor: the last row seen, by (collected_date, id)."""

    collected_date: datetime
    id: int


@dataclass(frozen=True)
class ArticlePage:
    """One page of a keyset-paginated article query."""

    items: List[Article]
    next_cursor: Optional[ArticleCursor]


@dataclass
class _ClusterBatchContext:
    """Plan 037: mutable state for one `save_articles_bulk()` call's
    in-memory near-duplicate clustering — prefetched candidates grouped by
    prefix (augmented with not-yet-flushed same-batch rows as they're
    created), a lazily-memoized global fallback, and a synthetic tie-break
    id for rows that don't have a real primary key yet."""

    session: Session
    repo: Any
    candidates_by_prefix: Dict[int, List[Article]]
    window: int
    pending_by_cluster: Dict[str, List[Article]] = field(default_factory=dict)
    pending_all: List[Article] = field(default_factory=list)
    synthetic_ids: Dict[int, int] = field(default_factory=dict)
    synthetic_counter: int = 10**9
    _fallback_cache: Optional[List[Article]] = None

    def tie_break_id(self, article: Article) -> int:
        real_id = getattr(article, "id", None)
        if real_id is not None:
            return int(real_id)
        return self.synthetic_ids.get(id(article), 0)

    def fetch_fallback(self) -> List[Article]:
        if self._fallback_cache is None:
            self._fallback_cache = (
                self.session.query(Article)
                .options(self.repo._cluster_load_only())
                .filter(Article.simhash.isnot(None))
                .order_by(Article.collected_date.desc())
                .limit(self.window)
                .all()
            )
        same_batch = [a for a in self.pending_all if a.simhash is not None]
        return (same_batch + self._fallback_cache)[: self.window]

    def resolve(self, row: Dict[str, Any]) -> Tuple[str, float]:
        simhash_value = row["simhash_value"]
        if not simhash_value or row["simhash_prefix"] is None:
            return generate_cluster_id(), 0.0

        gathered = ArticleRepository._gather_batch_candidates(
            self.candidates_by_prefix,
            row["simhash_prefix"],
            self.window,
            self.fetch_fallback,
        )
        return cast(
            Tuple[str, float],
            self.repo._resolve_cluster_for_candidates(
                self.session,
                gathered,
                simhash_value,
                row["payload"].get("published_date"),
                tie_break_id=self.tie_break_id,
                pending_by_cluster=self.pending_by_cluster,
            ),
        )

    def register(self, article: Article, row: Dict[str, Any]) -> None:
        if not row["simhash_value"] or row["simhash_prefix"] is None:
            return
        # Prepend — most recent — matching the recency ordering the DB
        # prefetch already uses, so later same-batch rows see it first.
        self.candidates_by_prefix.setdefault(row["simhash_prefix"], []).insert(
            0, article
        )
        self.pending_all.insert(0, article)
        self.pending_by_cluster.setdefault(cast(str, article.cluster_id), []).append(
            article
        )
        self.synthetic_ids[id(article)] = self.synthetic_counter
        self.synthetic_counter += 1


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


class ArticleRepository:
    """
    Focused repository for article CRUD, deduplication, clustering, and scoring.

    Receives a DatabaseManager (or any object with ``get_session()``) as its
    session provider so that engine lifecycle is owned by the caller.
    """

    def __init__(self, db_manager: Any) -> None:
        self._db = db_manager

    @contextmanager
    def _session(self):
        with self._db.get_session() as session:
            yield session

    # ------------------------------------------------------------------
    # Existence & lookup
    # ------------------------------------------------------------------

    def article_exists(self, url: str) -> bool:
        """Check if an article with the given URL already exists."""
        url = canonicalize_url(url) or url
        with self._session() as session:
            result = session.query(
                session.query(Article).filter_by(url=url).exists()
            ).scalar()
            return bool(result)

    def get_article_by_url(self, url: str) -> Optional[Article]:
        """Fetch a single article by canonical URL."""
        canonical_url = canonicalize_url(url) or url
        with self._session() as session:
            article = cast(
                Optional[Article],
                session.query(Article).filter_by(url=canonical_url).first(),
            )
            if article is not None:
                session.expunge(article)
            return article

    def get_article_by_id(self, article_id: int) -> Optional[Article]:
        """Fetch a single article by id."""
        with self._session() as session:
            article = cast(
                Optional[Article],
                session.query(Article).filter(Article.id == article_id).first(),
            )
            if article is not None:
                session.expunge(article)
            return article

    def articles_exist(self, urls: List[str]) -> Set[str]:
        """
        Batch check for existing articles by URL.

        Returns a set of URLs that already exist.  Canonicalizes all URLs
        before querying.
        """
        if not urls:
            return set()

        urls = [canonicalize_url(u) or u for u in urls]

        CHUNK_SIZE = 500
        existing_urls: Set[str] = set()

        with self._session() as session:
            for i in range(0, len(urls), CHUNK_SIZE):
                chunk = urls[i : i + CHUNK_SIZE]
                results = (
                    session.query(Article.url).filter(Article.url.in_(chunk)).all()
                )
                existing_urls.update(r[0] for r in results)

        return existing_urls

    # ------------------------------------------------------------------
    # Publishing state
    # ------------------------------------------------------------------

    def mark_article_published(
        self, article_id: int, pr_url: str, refinery_id: str | None = None
    ) -> bool:
        """Record PR_CREATED publication-attempt state.

        Plan 021: opening a PR is not a real publication — keeps
        ``processing_status = "publishing"`` (previously jumped straight to
        ``"completed"``, which meant a validation failure or a PR closed
        without merging still left the article looking permanently live).
        ``published_at``/``published_url`` are intentionally left unset
        here too; they now only get set by :meth:`complete_publication_attempts`
        on a real deploy. Real transitions happen via
        :meth:`reject_publication_attempts`/:meth:`complete_publication_attempts`,
        keyed by ``refinery_id`` (persisted here into
        ``article_metadata["publication"]["refinery_id"]``) once the
        frontend's webhook callback names this attempt.
        """
        with self._session() as session:
            article = session.query(Article).filter(Article.id == article_id).first()
            if not article:
                logger.warning(
                    "Could not find article {} to mark as published.", article_id
                )
                return False

            article.processing_status = "publishing"
            article_metadata = dict(article.article_metadata or {})
            publication_meta = dict(article_metadata.get("publication") or {})
            publication_meta.update(
                {
                    "state": "PR_CREATED",
                    "pr_url": pr_url,
                    "refinery_id": refinery_id or str(article_id),
                    "frontend_checks": {
                        "state": "pending",
                        "ready_for_merge": False,
                        "required_workflows": list(
                            FRONTEND_REQUIRED_PUBLICATION_WORKFLOWS
                        ),
                    },
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            article_metadata["publication"] = publication_meta
            article.article_metadata = article_metadata
            session.add(article)
            logger.info("Marked article {} as PR_CREATED (PR: {})", article_id, pr_url)
            return True

    def reject_publication_attempts(
        self, refinery_ids: list[str], reason: str = ""
    ) -> int:
        """Transition named, still-in-flight publication attempts to 'rejected'.

        Matches by ``article_metadata["publication"]["refinery_id"]`` — never
        bulk-updates every 'publishing' row, only ones a frontend callback
        actually named. Idempotent: an attempt already 'rejected' or
        'completed' is left alone (a replayed callback is a no-op, not an
        error).
        """
        if not refinery_ids:
            return 0
        wanted = set(refinery_ids)
        updated = 0
        with self._session() as session:
            candidates = (
                session.query(Article)
                .filter(Article.processing_status == "publishing")
                .all()
            )
            for article in candidates:
                metadata = article.article_metadata or {}
                publication = metadata.get("publication") or {}
                if publication.get("refinery_id") not in wanted:
                    continue
                article.processing_status = "rejected"
                new_metadata = dict(metadata)
                new_publication = dict(publication)
                new_publication.update(
                    {
                        "state": "REJECTED",
                        "reason": reason,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
                new_metadata["publication"] = new_publication
                article.article_metadata = new_metadata
                session.add(article)
                updated += 1
        return updated

    def complete_publication_attempts(
        self, refinery_ids: list[str], deploy_url: str | None
    ) -> int:
        """Transition named, still-in-flight publication attempts to 'completed'.

        Sets the real ``published_at``/``published_url`` here — the only
        place they get set, now that a PR being opened no longer implies a
        live deploy. Matches by ``refinery_id``, same idempotency guarantee
        as :meth:`reject_publication_attempts`.
        """
        if not refinery_ids:
            return 0
        wanted = set(refinery_ids)
        now = datetime.now(timezone.utc)
        updated = 0
        with self._session() as session:
            candidates = (
                session.query(Article)
                .filter(Article.processing_status == "publishing")
                .all()
            )
            for article in candidates:
                metadata = article.article_metadata or {}
                publication = metadata.get("publication") or {}
                if publication.get("refinery_id") not in wanted:
                    continue
                article.processing_status = "completed"
                article.published_at = now
                if deploy_url:
                    article.published_url = deploy_url
                new_metadata = dict(metadata)
                new_publication = dict(publication)
                new_publication.update(
                    {
                        "state": "COMPLETED",
                        "updated_at": now.isoformat(),
                    }
                )
                new_metadata["publication"] = new_publication
                article.article_metadata = new_metadata
                session.add(article)
                updated += 1
        return updated

    def update_article_audit_status(
        self,
        article_id: int,
        audit_status: str,
        reason: str = "",
        *,
        attempts: int | None = None,
        timeout_seconds: int | None = None,
        model: str | None = None,
        endpoint: str | None = None,
    ) -> bool:
        """Persist auditor execution outcome without mutating publication stage."""
        with self._session() as session:
            article = session.query(Article).filter(Article.id == article_id).first()
            if not article:
                logger.warning(
                    "Could not find article {} to update audit status.", article_id
                )
                return False

            article_metadata = dict(article.article_metadata or {})
            audit_meta = dict(article_metadata.get("audit") or {})
            audit_meta.update(
                {
                    "state": str(audit_status),
                    "reason": str(reason or ""),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            if attempts is not None:
                audit_meta["attempts"] = int(attempts)
            if timeout_seconds is not None:
                audit_meta["timeout_seconds"] = int(timeout_seconds)
            if model:
                audit_meta["model"] = str(model)
            if endpoint:
                audit_meta["endpoint"] = str(endpoint)

            article_metadata["audit"] = audit_meta
            article.article_metadata = article_metadata
            session.add(article)
            logger.info(
                "Updated audit state for article {}: {}", article_id, audit_status
            )
            return True

    def is_article_published(self, article_id: int) -> bool:
        """Check if an article has already reached PR_CREATED state."""
        with self._session() as session:
            article = session.query(Article).filter(Article.id == article_id).first()
            if not article:
                return False
            return article.published_url is not None or article.published_at is not None

    def is_article_in_flight_or_done(self, article_id: int) -> bool:
        """True if the article already has an open PR or a completed publication.

        ``processing_status == "publishing"`` covers an open, still-pending PR
        (plan 021 keeps that status for the whole PR window, not just
        pre-PR). ``published_url``/``published_at`` cover a real deploy
        completion. Plain ``completed`` does *not* count as done: the scoring
        phase sets ``completed`` as soon as scoring finishes, so a scored-but-
        never-published article must remain a valid editorial candidate.
        Consuming code that only needs the deploy-completion signal should
        call :meth:`is_article_published` instead.
        """
        with self._session() as session:
            article = session.query(Article).filter(Article.id == article_id).first()
            if not article:
                return False
            return (
                article.processing_status == "publishing"
                or article.published_url is not None
                or article.published_at is not None
            )

    def articles_in_flight_or_done(self, article_ids: list[int]) -> set[int]:
        """Batch version of :meth:`is_article_in_flight_or_done`."""
        if not article_ids:
            return set()
        with self._session() as session:
            rows = (
                session.query(Article.id)
                .filter(Article.id.in_(article_ids))
                .filter(
                    or_(
                        Article.processing_status == "publishing",
                        Article.published_url.isnot(None),
                        Article.published_at.isnot(None),
                    )
                )
                .all()
            )
            return {row[0] for row in rows}

    def published_ids_in(self, article_ids: list[int]) -> set[int]:
        """Return the subset of ``article_ids`` already published.

        Mirrors :meth:`is_article_published` (``published_url`` set OR
        ``published_at`` set) but resolves the whole batch in a single query,
        avoiding the N+1 pattern when filtering candidate lists.
        """
        if not article_ids:
            return set()
        with self._session() as session:
            rows = (
                session.query(Article.id)
                .filter(Article.id.in_(article_ids))
                .filter(
                    or_(
                        Article.published_url.isnot(None),
                        Article.published_at.isnot(None),
                    )
                )
                .all()
            )
            return {row[0] for row in rows}

    def mark_article_publishing(self, article_id: int, branch_name: str) -> bool:
        """Mark article as 'publishing' before git operations."""
        with self._session() as session:
            article = session.query(Article).filter(Article.id == article_id).first()
            if not article:
                return False

            article.processing_status = "publishing"
            article_metadata = dict(article.article_metadata or {})
            article_metadata["publishing_started_at"] = datetime.now(
                timezone.utc
            ).isoformat()
            article_metadata["publishing_branch"] = branch_name
            article.article_metadata = article_metadata
            session.add(article)
            return True

    def get_publishing_state(self, article_id: int) -> dict | None:
        """Return publishing metadata only while genuinely stuck pre-PR.

        Plan 021 keeps ``processing_status = "publishing"`` for the entire
        window a PR is open awaiting frontend CI/deploy, not just before
        the PR exists. Returning state (and thus letting
        ``PROrchestrator.attempt_recovery`` fire) once a PR already exists
        would create a duplicate PR after ``PUBLISHING_TIMEOUT_SECONDS``
        elapses on a slow-but-healthy CI run — so this returns ``None`` as
        soon as ``article_metadata["publication"]`` exists (a PR was
        created), even though ``processing_status`` is still
        ``"publishing"``.
        """
        with self._session() as session:
            article = session.query(Article).filter(Article.id == article_id).first()
            if not article or article.processing_status != "publishing":
                return None

            metadata = dict(article.article_metadata or {})
            if metadata.get("publication"):
                return None
            return {
                "publishing_started_at": metadata.get("publishing_started_at"),
                "publishing_branch": metadata.get("publishing_branch"),
            }

    def is_processed(self, identifier: str | int) -> bool:
        """
        Backwards-compatible helper used by Refinery for file-based workflows.
        Returns True only if the identifier maps to a numeric article ID that
        has already been published.
        """
        ident_str = str(identifier).strip()
        if ident_str.isdigit():
            return self.is_article_published(int(ident_str))

        stem = ident_str.rsplit(".", 1)[0]
        if stem.isdigit():
            return self.is_article_published(int(stem))

        return False

    # ------------------------------------------------------------------
    # Canonical slug (immutable identity)
    # ------------------------------------------------------------------

    def get_canonical_slug(self, article_id: int | str) -> Optional[str]:
        """Retrieve the immutable canonical slug for an article."""
        try:
            val_id = int(str(article_id).strip())
        except ValueError:
            return None

        with self._session() as session:
            article = session.query(Article).filter(Article.id == val_id).first()
            if article:
                return str(article.canonical_slug) if article.canonical_slug else None
        return None

    def set_canonical_slug(self, article_id: int | str, slug: str) -> bool:
        """
        Persist the immutable canonical slug for an article.
        Fails safely if already set.
        """
        try:
            val_id = int(str(article_id).strip())
        except ValueError:
            return False

        if not slug or not slug.strip():
            return False

        with self._session() as session:
            article = session.query(Article).filter(Article.id == val_id).first()
            if not article:
                return False

            if article.canonical_slug and article.canonical_slug != slug:
                logger.warning(
                    "Attempted to overwrite existing slug {} with {}. Ignored.",
                    article.canonical_slug,
                    slug,
                )
                return False

            article.canonical_slug = slug
            session.add(article)
            return True

    # ------------------------------------------------------------------
    # Save / bulk save (core write path with dedup)
    # ------------------------------------------------------------------

    def save_article(  # noqa: C901
        self, article_data: CollectorArticleModel | Dict[str, Any]
    ) -> Optional[Article]:
        """
        Save a new article with URL + content-hash dedup and cluster assignment.
        Returns the saved Article or None if a duplicate exists.
        """
        if isinstance(article_data, CollectorArticleModel):
            model = article_data
        else:
            try:
                model = CollectorArticleModel.model_validate(article_data)
            except ValidationError as exc:
                raise ValueError(f"Invalid collector payload: {exc}") from exc

        payload = model.model_dump_for_storage()

        # Defense-in-depth (LAW-4): canonical URL immediately
        payload["url"] = canonicalize_url(payload["url"]) or payload["url"]

        normalized_published = ensure_timezone(payload.get("published_date"))
        if normalized_published:
            payload["published_date"] = normalized_published

        with self._session() as session:
            try:
                norm_title, norm_summary, normalized_text = normalize_article_text(
                    payload.get("title", ""),
                    payload.get("summary", ""),
                )
                normalized_basis = normalized_text or payload["url"]
                content_hash = sha256_hex(normalized_basis)

                # Check 1: URL dedup
                existing: Article | None = (
                    session.query(Article).filter_by(url=payload["url"]).first()
                )
                if existing:
                    logger.warning(
                        "Found existing article by URL: {} (ID: {})",
                        payload["url"],
                        existing.id,
                    )
                    return None

                # Check 2: Content hash dedup
                existing_by_content = (
                    session.query(Article).filter_by(content_hash=content_hash).first()
                )
                if existing_by_content:
                    logger.debug("Duplicate content found for: {}", payload["title"])
                    return None

                simhash_value = simhash_normalize_unsigned(simhash64(normalized_basis))
                simhash_prefix = simhash_prefix_value(simhash_value)
                cluster_id, confidence = self._assign_cluster(
                    session,
                    int(simhash_value) if simhash_value is not None else 0,
                    payload.get("published_date"),
                )

                article_metadata = payload.get("article_metadata", {}) or {}
                article_metadata.setdefault("normalized_title", norm_title)
                article_metadata.setdefault("normalized_summary", norm_summary)
                article_metadata.setdefault(
                    "original_url",
                    payload.get("original_url", payload["url"]),
                )

                initial_status = (
                    getattr(model, "processing_status_override", None) or PENDING_STATUS
                )
                if initial_status not in PROCESSING_STATUS_VALUES:
                    raise ValueError(
                        f"Invalid processing_status: {initial_status}. "
                        f"Allowed: {PROCESSING_STATUS_VALUES}"
                    )

                article = Article(
                    url=payload["url"],
                    content_hash=content_hash,
                    simhash=simhash_to_storage(simhash_value),
                    simhash_prefix=simhash_prefix,
                    title=payload["title"],
                    summary=payload.get("summary"),
                    content=payload.get("content"),
                    source_id=payload["source_id"],
                    source_name=payload["source_name"],
                    published_date=payload.get("published_date"),
                    published_tz_offset_minutes=payload.get(
                        "published_tz_offset_minutes"
                    ),
                    published_tz_name=payload.get("published_tz_name"),
                    authors=payload.get("authors"),
                    category=payload["category"],
                    doi=payload.get("doi"),
                    journal=payload.get("journal"),
                    is_preprint=payload.get("is_preprint", False),
                    language=payload.get("language", "en"),
                    content_mode=payload.get("content_mode"),
                    processing_status=initial_status,
                    article_metadata=article_metadata,
                    word_count=payload.get("word_count"),
                    reading_time_minutes=payload.get("reading_time_minutes"),
                    cluster_id=cluster_id,
                    duplication_confidence=confidence,
                )

                session.add(article)
                session.flush()

                if cluster_id:
                    self._revalidate_cluster(session, cluster_id)

                logger.info("Article saved: {}...", article.title[:50])
                return article

            except IntegrityError as e:
                session.rollback()
                err_msg = str(e).lower()
                if "unique" in err_msg or "duplicate" in err_msg:
                    logger.warning(
                        "Concurrent duplicate insertion trapped by DB constraint: {}",
                        e,
                    )
                    return None
                logger.error("Critical IntegrityError saving article: {}", e)
                raise
            except Exception as e:
                logger.error("Error saving article: {}", e)
                raise

    def _prepare_bulk_row(
        self, data: Union[Dict[str, Any], "CollectorArticleModel"]
    ) -> Optional[Dict[str, Any]]:
        """Validate/canonicalize/normalize/hash one bulk input exactly once.

        Returns None for an invalid payload (logged, skipped) — never
        raises for a bad individual row, matching current behavior.
        """
        if isinstance(data, CollectorArticleModel):
            model = data
        else:
            try:
                model = CollectorArticleModel.model_validate(data)
            except ValidationError as exc:
                logger.warning("Invalid bulk item skipped: {}", exc)
                return None

        payload = model.model_dump_for_storage()
        payload["url"] = canonicalize_url(payload["url"]) or payload["url"]

        normalized_published = ensure_timezone(payload.get("published_date"))
        if normalized_published:
            payload["published_date"] = normalized_published

        norm_title, norm_summary, normalized_text = normalize_article_text(
            payload.get("title", ""),
            payload.get("summary", ""),
        )
        normalized_basis = normalized_text or payload["url"]
        content_hash = sha256_hex(normalized_basis)
        simhash_value = simhash_normalize_unsigned(simhash64(normalized_basis))
        simhash_prefix = simhash_prefix_value(simhash_value)

        initial_status = getattr(model, "processing_status_override", None)
        if (
            initial_status is not None
            and initial_status not in PROCESSING_STATUS_VALUES
        ):
            raise ValueError(
                f"Invalid processing_status: {initial_status}. "
                f"Allowed: {PROCESSING_STATUS_VALUES}"
            )

        return {
            "payload": payload,
            "url": payload["url"],
            "content_hash": content_hash,
            "simhash_value": int(simhash_value) if simhash_value is not None else 0,
            "simhash_prefix": simhash_prefix,
            "norm_title": norm_title,
            "norm_summary": norm_summary,
            "initial_status": initial_status,
        }

    @staticmethod
    def _dedupe_prepared_rows(
        prepared_rows: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """In-batch dedup by canonical URL and content hash, first
        occurrence wins, stable input order."""
        seen_urls: Set[str] = set()
        seen_hashes: Set[str] = set()
        deduped: List[Dict[str, Any]] = []
        for row in prepared_rows:
            if row["url"] in seen_urls:
                continue
            if row["content_hash"] and row["content_hash"] in seen_hashes:
                continue
            seen_urls.add(row["url"])
            if row["content_hash"]:
                seen_hashes.add(row["content_hash"])
            deduped.append(row)
        return deduped

    def _filter_existing_articles(
        self, session: Session, prepared_rows: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Step 3: chunked exact-duplicate prefetch (reusing
        `articles_exist()`'s `CHUNK_SIZE=500` IN-query pattern)."""
        existing_urls = self._chunked_in_lookup(
            session, Article.url, [r["url"] for r in prepared_rows]
        )
        existing_hashes = self._chunked_in_lookup(
            session,
            Article.content_hash,
            [r["content_hash"] for r in prepared_rows if r["content_hash"]],
        )
        return [
            r
            for r in prepared_rows
            if r["url"] not in existing_urls
            and (not r["content_hash"] or r["content_hash"] not in existing_hashes)
        ]

    def _build_cluster_batch_context(
        self, session: Session, filtered_rows: List[Dict[str, Any]]
    ) -> "_ClusterBatchContext":
        needed_prefixes: Set[int] = set()
        for r in filtered_rows:
            if not r["simhash_value"] or r["simhash_prefix"] is None:
                continue
            p = r["simhash_prefix"]
            needed_prefixes.add(p)
            if p > 0:
                needed_prefixes.add(p - 1)
            if p < 0xFFFF:
                needed_prefixes.add(p + 1)

        candidates_by_prefix = self._fetch_batch_cluster_candidates(
            session, needed_prefixes
        )
        window = get_runtime_config().dedup_config.get("simhash_candidate_window", 500)
        return _ClusterBatchContext(
            session=session,
            repo=self,
            candidates_by_prefix=candidates_by_prefix,
            window=window,
        )

    def _build_article_from_row(
        self, row: Dict[str, Any], cluster_id: str, confidence: float
    ) -> Article:
        payload = row["payload"]
        article_metadata = payload.get("article_metadata", {}) or {}
        article_metadata.setdefault("normalized_title", row["norm_title"])
        article_metadata.setdefault("normalized_summary", row["norm_summary"])
        article_metadata.setdefault(
            "original_url", payload.get("original_url", payload["url"])
        )

        return Article(
            url=payload["url"],
            content_hash=row["content_hash"],
            simhash=simhash_to_storage(row["simhash_value"]),
            simhash_prefix=row["simhash_prefix"],
            title=payload["title"],
            summary=payload.get("summary"),
            content=payload.get("content"),
            source_id=payload["source_id"],
            source_name=payload["source_name"],
            published_date=payload.get("published_date"),
            published_tz_offset_minutes=payload.get("published_tz_offset_minutes"),
            published_tz_name=payload.get("published_tz_name"),
            authors=payload.get("authors"),
            category=payload["category"],
            doi=payload.get("doi"),
            journal=payload.get("journal"),
            is_preprint=payload.get("is_preprint", False),
            language=payload.get("language", "en"),
            content_mode=payload.get("content_mode"),
            processing_status=row["initial_status"] or PENDING_STATUS,
            article_metadata=article_metadata,
            word_count=payload.get("word_count"),
            reading_time_minutes=payload.get("reading_time_minutes"),
            cluster_id=cluster_id,
            duplication_confidence=confidence,
            collected_date=datetime.now(timezone.utc),
        )

    def _flush_batch(self, session: Session, pending_count: int, label: str) -> None:
        try:
            with session.begin_nested():
                session.flush()
        except IntegrityError as e:
            logger.warning(
                "Bulk insert collision in {}: {}", label, str(e).splitlines()[0]
            )
            raise

    def save_articles_bulk(
        self,
        articles_data: Sequence[Union[Dict[str, Any], CollectorArticleModel]],
        batch_size: int = 50,
    ) -> int:
        """
        Save multiple articles atomically in batches.
        Returns the number of saved (non-duplicate) articles.
        """
        if not articles_data:
            return 0

        # Step 2: normalize/dedupe the input once, in stable input order.
        prepared_rows = self._dedupe_prepared_rows(
            [r for r in (self._prepare_bulk_row(d) for d in articles_data) if r]
        )
        if not prepared_rows:
            return 0

        with self._session() as session:
            try:
                filtered_rows = self._filter_existing_articles(session, prepared_rows)
                if not filtered_rows:
                    session.commit()
                    return 0

                # Step 4: one prefetch across every prefix any row might
                # need, then resolve each row's cluster in memory.
                context = self._build_cluster_batch_context(session, filtered_rows)

                saved_count = 0
                pending_count = 0

                for row in filtered_rows:
                    cluster_id, confidence = context.resolve(row)
                    article = self._build_article_from_row(row, cluster_id, confidence)
                    session.add(article)
                    context.register(article, row)
                    pending_count += 1

                    if pending_count >= batch_size:
                        self._flush_batch(session, pending_count, "batch")
                        saved_count += pending_count
                        pending_count = 0

                if pending_count > 0:
                    self._flush_batch(session, pending_count, "final batch")
                    saved_count += pending_count

                session.commit()
                logger.info("Bulk save completed atomically: {} articles", saved_count)
                return saved_count

            except Exception as e:
                session.rollback()
                logger.error("Fatal error in bulk save, transaction aborted: {}", e)
                raise

    @staticmethod
    def _chunked_in_lookup(
        session: Session, column: Any, values: List[str], chunk_size: int = 500
    ) -> Set[str]:
        """Chunked `IN` existence lookup — same pattern as `articles_exist`."""
        found: Set[str] = set()
        unique_values = list(dict.fromkeys(v for v in values if v))
        for i in range(0, len(unique_values), chunk_size):
            chunk = unique_values[i : i + chunk_size]
            rows = session.query(column).filter(column.in_(chunk)).all()
            found.update(r[0] for r in rows)
        return found

    @staticmethod
    def _gather_batch_candidates(
        candidates_by_prefix: Dict[int, List[Article]],
        prefix: int,
        window: int,
        fetch_fallback: Callable[[], List[Article]],
    ) -> List[Article]:
        """In-memory equivalent of `_assign_cluster`'s per-prefix querying
        loop: closest-prefix-first, window-limited, reading from the
        prefetched (and same-batch-augmented) in-memory map instead of
        issuing a new query."""
        candidate_prefixes = [prefix]
        if prefix > 0:
            candidate_prefixes.append(prefix - 1)
        if prefix < 0xFFFF:
            candidate_prefixes.append(prefix + 1)

        candidates: List[Article] = []
        remaining = window
        for pref in sorted(
            dict.fromkeys(candidate_prefixes), key=lambda p: abs(p - prefix)
        ):
            pref_candidates = candidates_by_prefix.get(pref, [])[:remaining]
            candidates.extend(pref_candidates)
            remaining = window - len(candidates)
            if remaining <= 0:
                break

        if not candidates:
            candidates = fetch_fallback()

        return candidates

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    def get_articles_by_score(
        self,
        limit: int = 10,
        min_score: float = 0.0,
        exclude_published: bool = False,
        max_age_days: Optional[int] = None,
    ) -> List[Article]:
        """Return the highest-ranked articles.

        `max_age_days` optionally bounds candidates to articles whose
        reference date (published_date, falling back to collected_date)
        is within that many days — the candidate recency gate.
        """
        with self._session() as session:
            query = (
                session.query(Article)
                .filter(Article.final_score >= min_score)
                .filter(Article.processing_status == "completed")
            )
            if exclude_published:
                query = query.filter(Article.published_at.is_(None))
            if max_age_days is not None:
                cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
                query = query.filter(
                    func.coalesce(Article.published_date, Article.collected_date)
                    >= cutoff
                )

            return list(
                query.order_by(desc(Article.final_score), Article.collected_date.desc())
                .limit(limit)
                .all()
            )

    def get_articles_by_category(
        self, category: str, days_back: int = 7
    ) -> List[Article]:
        """Return recent articles in a category."""
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_back)

        with self._session() as session:
            results = (
                session.query(Article)
                .filter(Article.category == category)
                .filter(Article.collected_date >= cutoff_date)
                .filter(Article.processing_status == "completed")
                .order_by(desc(Article.final_score), Article.collected_date.desc())
                .all()
            )
            return list(results)

    def get_pending_articles(
        self, limit: Optional[int] = None, status: str = PENDING_STATUS
    ) -> List[Article]:
        """Return articles pending processing."""
        with self._session() as session:
            query = (
                session.query(Article)
                .filter(Article.processing_status == status)
                .order_by(Article.collected_date)
            )
            if limit:
                query = query.limit(limit)

            pending_articles = query.all()
            session.expunge_all()
            return list(pending_articles)

    def get_completed_articles_for_rescoring(
        self, days_back: int = 14
    ) -> List[Article]:
        """Return completed but unpublished articles collected within the last N days."""
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_back)
        with self._session() as session:
            completed_articles = (
                session.query(Article)
                .filter(Article.processing_status == "completed")
                .filter(Article.published_url.is_(None))
                .filter(Article.published_at.is_(None))
                .filter(Article.collected_date >= cutoff_date)
                .order_by(Article.collected_date)
                .all()
            )
            session.expunge_all()
            return list(completed_articles)

    @staticmethod
    def _keyset_predicate(cursor: ArticleCursor):
        """Tuple-comparison continuation predicate for (collected_date, id).

        A plain ``collected_date > cursor.collected_date`` would skip or
        duplicate rows that share a timestamp with the cursor row.
        """
        return or_(
            Article.collected_date > cursor.collected_date,
            and_(
                Article.collected_date == cursor.collected_date,
                Article.id > cursor.id,
            ),
        )

    def get_pending_articles_page(
        self,
        limit: int,
        status: str = PENDING_STATUS,
        cursor: Optional[ArticleCursor] = None,
    ) -> ArticlePage:
        """Keyset-paginated pending articles, ordered by (collected_date, id).

        Used by ScoringCoordinator to bound one scoring cycle's memory
        footprint (plan 036) — kept alongside, not instead of,
        `get_pending_articles` which other callers (validation coordinator,
        pipeline_e2e snapshots) rely on for its own status-driven pagination.
        """
        with self._session() as session:
            query = session.query(Article).filter(Article.processing_status == status)
            if cursor is not None:
                query = query.filter(self._keyset_predicate(cursor))
            rows = list(
                query.order_by(Article.collected_date, Article.id)
                .limit(limit + 1)
                .all()
            )
            session.expunge_all()
            has_more = len(rows) > limit
            items = rows[:limit]
            next_cursor = (
                ArticleCursor(items[-1].collected_date, items[-1].id)
                if has_more and items
                else None
            )
            return ArticlePage(items=items, next_cursor=next_cursor)

    def get_completed_articles_for_rescoring_page(
        self,
        limit: int,
        days_back: int = 14,
        cursor: Optional[ArticleCursor] = None,
    ) -> ArticlePage:
        """Keyset-paginated rescore candidates, ordered by (collected_date, id).

        See `get_pending_articles_page` — additive, plan 036.
        """
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_back)
        with self._session() as session:
            query = (
                session.query(Article)
                .filter(Article.processing_status == "completed")
                .filter(Article.published_url.is_(None))
                .filter(Article.published_at.is_(None))
                .filter(Article.collected_date >= cutoff_date)
            )
            if cursor is not None:
                query = query.filter(self._keyset_predicate(cursor))
            rows = list(
                query.order_by(Article.collected_date, Article.id)
                .limit(limit + 1)
                .all()
            )
            session.expunge_all()
            has_more = len(rows) > limit
            items = rows[:limit]
            next_cursor = (
                ArticleCursor(items[-1].collected_date, items[-1].id)
                if has_more and items
                else None
            )
            return ArticlePage(items=items, next_cursor=next_cursor)

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def update_validation_status_bulk(self, mappings: List[Dict[str, Any]]) -> bool:
        """Bulk-update validation status for multiple articles."""
        if not mappings:
            return True

        with self._session() as session:
            try:
                session.bulk_update_mappings(Article, mappings)
                session.commit()
                return True
            except Exception as e:
                logger.error("Error in update_validation_status_bulk: {}", e)
                session.rollback()
                return False

    def update_articles_score_bulk(
        self,
        score_data_list: List[Tuple[int, ScoringRequestModel | Dict[str, Any]]],
    ) -> bool:
        """Bulk-update scores and record ScoreLog entries."""
        if not score_data_list:
            return True

        article_mappings = []
        score_logs = []

        for article_id, score_data in score_data_list:
            if isinstance(score_data, ScoringRequestModel):
                score_model = score_data
            else:
                try:
                    score_model = ScoringRequestModel.model_validate(score_data)
                except ValidationError as exc:
                    logger.error(
                        "Invalid scoring payload for article {}: {}",
                        article_id,
                        exc,
                    )
                    continue

            payload = score_model.model_dump_for_storage()
            components_model = score_model.components

            article_mappings.append(
                {
                    "id": article_id,
                    "final_score": payload["final_score"],
                    "score_components": payload.get("components", {}),
                    "processing_status": "completed",
                }
            )

            score_logs.append(
                ScoreLog(
                    article_id=article_id,
                    score_version=payload.get("version", "1.0"),
                    source_credibility_score=payload["components"].get(
                        "source_credibility"
                    ),
                    recency_score=payload["components"].get("recency"),
                    content_quality_score=payload["components"].get("content_quality"),
                    engagement_score=components_model.get_engagement_value(),
                    final_score=payload["final_score"],
                    score_explanation=payload.get("explanation", {}),
                    algorithm_weights=payload.get("weights", {}),
                )
            )

        with self._session() as session:
            try:
                session.bulk_update_mappings(Article, article_mappings)
                session.add_all(score_logs)
                session.commit()
                return True
            except Exception as e:
                logger.error("Error in update_articles_score_bulk: {}", e)
                session.rollback()
                return False

    def update_article_score(
        self,
        article_id: int,
        score_data: ScoringRequestModel | Dict[str, Any],
    ) -> bool:
        """Update a single article's score and record a ScoreLog entry."""
        if isinstance(score_data, ScoringRequestModel):
            score_model = score_data
        else:
            try:
                score_model = ScoringRequestModel.model_validate(score_data)
            except ValidationError as exc:
                raise ValueError(
                    f"Invalid scoring payload for article {article_id}: {exc}"
                ) from exc

        payload = score_model.model_dump_for_storage()
        components_model = score_model.components

        with self._session() as session:
            try:
                article = session.query(Article).filter_by(id=article_id).first()
                if not article:
                    logger.warning("Article not found for score update: {}", article_id)
                    return False

                article.final_score = payload["final_score"]
                article.score_components = payload.get("components", {})
                article.processing_status = "completed"

                score_log = ScoreLog(
                    article_id=article_id,
                    score_version=payload.get("version", "1.0"),
                    source_credibility_score=payload["components"].get(
                        "source_credibility"
                    ),
                    recency_score=payload["components"].get("recency"),
                    content_quality_score=payload["components"].get("content_quality"),
                    engagement_score=components_model.get_engagement_value(),
                    final_score=payload["final_score"],
                    score_explanation=payload.get("explanation", {}),
                    algorithm_weights=payload.get("weights", {}),
                )

                session.add(score_log)
                logger.info(
                    "Score updated for article {}: {}",
                    article_id,
                    payload["final_score"],
                )
                return True

            except Exception as e:
                logger.error("Error updating score: {}", e)
                session.rollback()
                return False

    # ------------------------------------------------------------------
    # Delete / clear
    # ------------------------------------------------------------------

    def delete_article(self, article_id: Union[int, str]) -> bool:
        """Delete a single article by ID."""
        try:
            num_id = int(article_id)
        except ValueError:
            return False

        with self._session() as session:
            try:
                article = session.query(Article).filter(Article.id == num_id).first()
                if article:
                    session.delete(article)
                    return True
            except Exception as e:
                logger.error("Error deleting article {}: {}", article_id, e)
                session.rollback()
            return False

    def clear_all_articles(self) -> int:
        """
        Delete ALL collected articles and score logs.
        This is destructive and irreversible.
        """
        with self._session() as session:
            try:
                deleted_logs = session.query(ScoreLog).delete()
                deleted_articles = session.query(Article).delete()
                logger.info(
                    "Cache cleared: {} articles and {} logs deleted.",
                    deleted_articles,
                    deleted_logs,
                )
                return int(deleted_articles)
            except Exception as e:
                logger.error("Error clearing cache: {}", e)
                raise

    # ------------------------------------------------------------------
    # Internal: simhash cluster assignment and revalidation
    # ------------------------------------------------------------------

    _CLUSTER_LOAD_ONLY_ATTRS = (
        "id",
        "simhash",
        "cluster_id",
        "published_date",
        "duplication_confidence",
        "collected_date",
    )

    @classmethod
    def _cluster_load_only(cls):
        return load_only(
            *(
                cast(QueryableAttribute[Any], getattr(Article, name))
                for name in cls._CLUSTER_LOAD_ONLY_ATTRS
            )
        )

    def _assign_cluster(
        self,
        session: Session,
        simhash_value: int,
        published_date: Optional[datetime],
    ) -> Tuple[str, float]:
        """Single-item cluster assignment: fetch candidates live, then
        delegate to the same decision+merge logic the batched path uses
        (`_resolve_cluster_for_candidates`) — one implementation shared by
        both, so they cannot silently drift."""
        dedup_config = get_runtime_config().dedup_config
        simhash_candidate_window = dedup_config.get("simhash_candidate_window", 500)

        simhash_value = simhash_normalize_unsigned(simhash_value) or 0
        if not simhash_value:
            return generate_cluster_id(), 0.0

        prefix = simhash_prefix_value(simhash_value)
        if prefix is None:
            return generate_cluster_id(), 0.0

        candidate_prefixes = [prefix]
        if prefix > 0:
            candidate_prefixes.append(prefix - 1)
        if prefix < 0xFFFF:
            candidate_prefixes.append(prefix + 1)

        candidates: List[Article] = []
        remaining = simhash_candidate_window

        for pref in sorted(
            dict.fromkeys(candidate_prefixes), key=lambda p: abs(p - prefix)
        ):
            query = (
                session.query(Article)
                .options(self._cluster_load_only())
                .filter(Article.simhash_prefix == pref)
                .filter(Article.simhash.isnot(None))
                .order_by(Article.collected_date.desc())
                .limit(remaining)
            )
            pref_candidates = query.all()
            candidates.extend(pref_candidates)
            remaining = simhash_candidate_window - len(candidates)
            if remaining <= 0:
                break

        if not candidates:
            candidates = (
                session.query(Article)
                .options(self._cluster_load_only())
                .filter(Article.simhash.isnot(None))
                .order_by(Article.collected_date.desc())
                .limit(simhash_candidate_window)
                .all()
            )

        unique_candidates: Dict[Any, Article] = {}
        for candidate in candidates:
            if candidate.id not in unique_candidates:
                unique_candidates[candidate.id] = candidate
        candidates = list(unique_candidates.values())

        return self._resolve_cluster_for_candidates(
            session,
            candidates,
            simhash_value,
            published_date,
            tie_break_id=lambda c: int(getattr(c, "id", 0) or 0),
        )

    def _resolve_cluster_for_candidates(
        self,
        session: Session,
        candidates: List[Article],
        simhash_value: int,
        published_date: Optional[datetime],
        tie_break_id: Callable[[Article], int],
        pending_by_cluster: Optional[Dict[str, List[Article]]] = None,
    ) -> Tuple[str, float]:
        """Pure decision logic: hamming-distance filtering, closest-match
        selection, confidence back-mutation, and other-cluster merging.
        Shared by the live single-query path (`_assign_cluster`) and the
        batched in-memory path (`save_articles_bulk`) — `candidates` must
        already be deduplicated by identity.

        `tie_break_id` resolves the `-int(cand_id)` tie-break key for a
        candidate; for not-yet-flushed same-batch rows (no real id yet)
        the caller supplies a synthetic monotonically-increasing id so
        ties resolve the same way real sequential inserts would (most
        recently added wins).

        `pending_by_cluster`, if given, lets an other-cluster merge also
        update not-yet-flushed same-batch articles' in-memory `cluster_id`
        — the DB-side bulk UPDATE below only reaches already-persisted
        rows.
        """
        if not candidates:
            return generate_cluster_id(), 0.0

        hits = self._hamming_filter_hits(candidates, simhash_value)
        if not hits:
            return generate_cluster_id(), 0.0

        def sort_key(item: Tuple[Article, int]):
            cand, dist = item
            time_delta = time_distance_seconds(
                published_date, getattr(cand, "published_date", None)
            )
            return (dist, time_delta, -tie_break_id(cand))

        hits.sort(key=sort_key)
        best_candidate, best_distance = hits[0]

        target_cluster = best_candidate.cluster_id or generate_cluster_id()
        if best_candidate.cluster_id is None:
            best_candidate.cluster_id = target_cluster
        current_confidence = float(
            getattr(best_candidate, "duplication_confidence", 0.0) or 0.0
        )
        best_candidate_record = cast(Any, best_candidate)
        best_candidate_record.duplication_confidence = max(
            current_confidence, float(duplication_confidence(best_distance))
        )

        self._merge_other_clusters(session, hits, target_cluster, pending_by_cluster)

        return str(target_cluster), float(duplication_confidence(best_distance))

    @staticmethod
    def _hamming_filter_hits(
        candidates: List[Article], simhash_value: int
    ) -> List[Tuple[Article, int]]:
        dedup_config = get_runtime_config().dedup_config
        simhash_threshold = dedup_config.get("simhash_threshold", 10)

        hits: List[Tuple[Article, int]] = []
        for candidate in candidates:
            c_simhash = getattr(candidate, "simhash", None)
            candidate_simhash = simhash_from_storage(
                int(c_simhash) if c_simhash is not None else None
            )
            if candidate_simhash is None:
                continue
            distance = hamming_distance(simhash_value, candidate_simhash)
            if distance <= simhash_threshold:
                hits.append((candidate, distance))
        return hits

    @staticmethod
    def _merge_other_clusters(
        session: Session,
        hits: List[Tuple[Article, int]],
        target_cluster: str,
        pending_by_cluster: Optional[Dict[str, List[Article]]],
    ) -> None:
        other_clusters = {
            cand.cluster_id
            for cand, _ in hits
            if cand.cluster_id and cand.cluster_id != target_cluster
        }

        for other_cluster in other_clusters:
            session.query(Article).filter(Article.cluster_id == other_cluster).update(
                {"cluster_id": target_cluster}, synchronize_session=False
            )
            if pending_by_cluster is not None:
                moved = pending_by_cluster.pop(other_cluster, [])
                for pending_article in moved:
                    pending_article.cluster_id = target_cluster
                if moved:
                    pending_by_cluster.setdefault(target_cluster, []).extend(moved)

    def _fetch_batch_cluster_candidates(
        self, session: Session, prefixes: Set[int]
    ) -> Dict[int, List[Article]]:
        """One prefetch query (chunked at the same 500-item `IN` bound as
        `articles_exist`) across every prefix any item in the batch might
        need, grouped by prefix, ordered by collected_date desc (matching
        each per-item query's own ordering)."""
        by_prefix: Dict[int, List[Article]] = {p: [] for p in prefixes}
        if not prefixes:
            return by_prefix

        prefix_list = list(prefixes)
        CHUNK_SIZE = 500
        for i in range(0, len(prefix_list), CHUNK_SIZE):
            chunk = prefix_list[i : i + CHUNK_SIZE]
            rows = (
                session.query(Article)
                .options(self._cluster_load_only())
                .filter(Article.simhash_prefix.in_(chunk))
                .filter(Article.simhash.isnot(None))
                .order_by(Article.collected_date.desc())
                .all()
            )
            for row in rows:
                by_prefix.setdefault(cast(int, row.simhash_prefix), []).append(row)

        return by_prefix

    def _revalidate_cluster(self, session: Session, cluster_id: Optional[str]) -> None:
        if not cluster_id:
            return
        simhash_threshold = get_runtime_config().dedup_config.get(
            "simhash_threshold", 10
        )
        article_id_attr = cast(QueryableAttribute[Any], Article.id)
        article_simhash_attr = cast(QueryableAttribute[Any], Article.simhash)
        article_cluster_id_attr = cast(QueryableAttribute[Any], Article.cluster_id)
        articles = (
            session.query(Article)
            .options(
                load_only(
                    article_id_attr,
                    article_simhash_attr,
                    article_cluster_id_attr,
                )
            )
            .filter(Article.cluster_id == cluster_id)
            .all()
        )
        if len(articles) <= 1:
            return
        anchor = next((a for a in articles if a.simhash is not None), None)
        if anchor is None or anchor.simhash is None:
            return
        anchor_simhash = simhash_from_storage(
            int(anchor.simhash) if anchor.simhash is not None else None
        )
        if anchor_simhash is None:
            return
        for article in articles:
            if article.id == anchor.id or article.simhash is None:
                continue
            article_simhash = simhash_from_storage(
                int(article.simhash) if article.simhash is not None else None
            )
            if article_simhash is None:
                continue
            distance = hamming_distance(article_simhash, anchor_simhash)
            if distance > simhash_threshold * 2:
                new_cluster = generate_cluster_id()
                article_record = cast(Any, article)
                article_record.cluster_id = new_cluster
                article_record.duplication_confidence = 0.0
