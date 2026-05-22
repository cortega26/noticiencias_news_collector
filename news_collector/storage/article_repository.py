"""
Article repository — focused CRUD, dedup, clustering, scoring, and publishing state.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union, cast

from sqlalchemy import desc
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, load_only
from sqlalchemy.orm.attributes import QueryableAttribute

from news_collector.config.settings import DEDUP_CONFIG
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
        self.simhash_threshold = DEDUP_CONFIG.get("simhash_threshold", 10)
        self.simhash_candidate_window = DEDUP_CONFIG.get(
            "simhash_candidate_window", 500
        )

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

    def mark_article_published(self, article_id: int, pr_url: str) -> bool:
        """Record PR_CREATED publication candidate state."""
        with self._session() as session:
            article = session.query(Article).filter(Article.id == article_id).first()
            if not article:
                logger.warning(
                    "Could not find article %s to mark as published.", article_id
                )
                return False

            article.processing_status = "completed"
            article.published_at = datetime.now(timezone.utc)
            article.published_url = pr_url
            article_metadata = dict(article.article_metadata or {})
            publication_meta = dict(article_metadata.get("publication") or {})
            publication_meta.update(
                {
                    "state": "PR_CREATED",
                    "pr_url": pr_url,
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
            logger.info("Marked article %s as PR_CREATED (PR: %s)", article_id, pr_url)
            return True

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
                    "Could not find article %s to update audit status.", article_id
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
                "Updated audit state for article %s: %s", article_id, audit_status
            )
            return True

    def is_article_published(self, article_id: int) -> bool:
        """Check if an article has already reached PR_CREATED state."""
        with self._session() as session:
            article = session.query(Article).filter(Article.id == article_id).first()
            if not article:
                return False
            return article.published_url is not None or article.published_at is not None

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
        """Return publishing metadata if article is in 'publishing' state."""
        with self._session() as session:
            article = session.query(Article).filter(Article.id == article_id).first()
            if not article or article.processing_status != "publishing":
                return None

            metadata = dict(article.article_metadata or {})
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
                    "Attempted to overwrite existing slug %s with %s. Ignored.",
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
                        "Found existing article by URL: %s (ID: %s)",
                        payload["url"],
                        existing.id,
                    )
                    return None

                # Check 2: Content hash dedup
                existing_by_content = (
                    session.query(Article).filter_by(content_hash=content_hash).first()
                )
                if existing_by_content:
                    logger.debug("Duplicate content found for: %s", payload["title"])
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

                logger.info("Article saved: %s...", article.title[:50])
                return article

            except IntegrityError as e:
                session.rollback()
                err_msg = str(e).lower()
                if "unique" in err_msg or "duplicate" in err_msg:
                    logger.warning(
                        "Concurrent duplicate insertion trapped by DB constraint: %s",
                        e,
                    )
                    return None
                logger.error("Critical IntegrityError saving article: %s", e)
                raise
            except Exception as e:
                logger.error("Error saving article: %s", e)
                raise

    def save_articles_bulk(  # noqa: C901
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

        saved_count = 0
        pending_count = 0
        seen_urls: Set[str] = set()

        with self._session() as session:
            try:
                for data in articles_data:
                    if isinstance(data, CollectorArticleModel):
                        model = data
                    else:
                        try:
                            model = CollectorArticleModel.model_validate(data)
                        except ValidationError as exc:
                            logger.warning("Invalid bulk item skipped: %s", exc)
                            continue

                    payload = model.model_dump_for_storage()
                    payload["url"] = canonicalize_url(payload["url"]) or payload["url"]
                    url = payload["url"]

                    if url in seen_urls:
                        continue
                    seen_urls.add(url)

                    normalized_published = ensure_timezone(
                        payload.get("published_date")
                    )
                    if normalized_published:
                        payload["published_date"] = normalized_published

                    # URL dedup
                    if (
                        session.query(Article)
                        .filter_by(url=payload["url"])
                        .with_entities(Article.id)
                        .first()
                    ):
                        continue

                    norm_title, norm_summary, normalized_text = normalize_article_text(
                        payload.get("title", ""),
                        payload.get("summary", ""),
                    )
                    normalized_basis = normalized_text or payload["url"]
                    content_hash = sha256_hex(normalized_basis)

                    # Content hash dedup
                    if (
                        session.query(Article)
                        .filter_by(content_hash=content_hash)
                        .with_entities(Article.id)
                        .first()
                    ):
                        continue

                    simhash_value = simhash_normalize_unsigned(
                        simhash64(normalized_basis)
                    )
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
                        processing_status=PENDING_STATUS,
                        article_metadata=article_metadata,
                        word_count=payload.get("word_count"),
                        reading_time_minutes=payload.get("reading_time_minutes"),
                        cluster_id=cluster_id,
                        duplication_confidence=confidence,
                    )

                    initial_status = getattr(model, "processing_status_override", None)
                    if initial_status is not None:
                        if initial_status not in PROCESSING_STATUS_VALUES:
                            raise ValueError(
                                f"Invalid processing_status: {initial_status}. "
                                f"Allowed: {PROCESSING_STATUS_VALUES}"
                            )
                        article.processing_status = initial_status

                    session.add(article)
                    pending_count += 1

                    if pending_count >= batch_size:
                        try:
                            with session.begin_nested():
                                session.flush()
                            saved_count += pending_count
                            pending_count = 0
                        except IntegrityError as e:
                            logger.warning(
                                "Bulk insert collision in batch: %s",
                                str(e).splitlines()[0],
                            )
                            raise

                if pending_count > 0:
                    try:
                        with session.begin_nested():
                            session.flush()
                        saved_count += pending_count
                    except IntegrityError as e:
                        logger.warning(
                            "Bulk insert collision in final batch: %s",
                            str(e).splitlines()[0],
                        )
                        raise

                session.commit()
                logger.info("Bulk save completed atomically: %s articles", saved_count)
                return saved_count

            except Exception as e:
                session.rollback()
                logger.error("Fatal error in bulk save, transaction aborted: %s", e)
                raise

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    def get_articles_by_score(
        self,
        limit: int = 10,
        min_score: float = 0.0,
        exclude_published: bool = False,
    ) -> List[Article]:
        """Return the highest-ranked articles."""
        with self._session() as session:
            query = (
                session.query(Article)
                .filter(Article.final_score >= min_score)
                .filter(Article.processing_status == "completed")
            )
            if exclude_published:
                query = query.filter(Article.published_at.is_(None))

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
                logger.error("Error in update_validation_status_bulk: %s", e)
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
                        "Invalid scoring payload for article %s: %s",
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
                logger.error("Error in update_articles_score_bulk: %s", e)
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
                    logger.warning("Article not found for score update: %s", article_id)
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
                    "Score updated for article %s: %s",
                    article_id,
                    payload["final_score"],
                )
                return True

            except Exception as e:
                logger.error("Error updating score: %s", e)
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
                logger.error("Error deleting article %s: %s", article_id, e)
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
                    "Cache cleared: %s articles and %s logs deleted.",
                    deleted_articles,
                    deleted_logs,
                )
                return int(deleted_articles)
            except Exception as e:
                logger.error("Error clearing cache: %s", e)
                raise

    # ------------------------------------------------------------------
    # Internal: simhash cluster assignment and revalidation
    # ------------------------------------------------------------------

    def _assign_cluster(  # noqa: C901
        self,
        session: Session,
        simhash_value: int,
        published_date: Optional[datetime],
    ) -> Tuple[str, float]:
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
        remaining = self.simhash_candidate_window
        article_id_attr = cast(QueryableAttribute[Any], Article.id)
        article_simhash_attr = cast(QueryableAttribute[Any], Article.simhash)
        article_cluster_id_attr = cast(QueryableAttribute[Any], Article.cluster_id)
        article_published_date_attr = cast(
            QueryableAttribute[Any], Article.published_date
        )
        article_dup_conf_attr = cast(
            QueryableAttribute[Any], Article.duplication_confidence
        )
        article_collected_date_attr = cast(
            QueryableAttribute[Any], Article.collected_date
        )

        for pref in sorted(
            dict.fromkeys(candidate_prefixes), key=lambda p: abs(p - prefix)
        ):
            query = (
                session.query(Article)
                .options(
                    load_only(
                        article_id_attr,
                        article_simhash_attr,
                        article_cluster_id_attr,
                        article_published_date_attr,
                        article_dup_conf_attr,
                        article_collected_date_attr,
                    )
                )
                .filter(Article.simhash_prefix == pref)
                .filter(Article.simhash.isnot(None))
                .order_by(Article.collected_date.desc())
                .limit(remaining)
            )
            pref_candidates = query.all()
            candidates.extend(pref_candidates)
            remaining = self.simhash_candidate_window - len(candidates)
            if remaining <= 0:
                break

        if not candidates:
            candidates = (
                session.query(Article)
                .options(
                    load_only(
                        article_id_attr,
                        article_simhash_attr,
                        article_cluster_id_attr,
                        article_published_date_attr,
                        article_dup_conf_attr,
                        article_collected_date_attr,
                    )
                )
                .filter(Article.simhash.isnot(None))
                .order_by(Article.collected_date.desc())
                .limit(self.simhash_candidate_window)
                .all()
            )

        if not candidates:
            return generate_cluster_id(), 0.0

        unique_candidates = {}
        for candidate in candidates:
            if candidate.id not in unique_candidates:
                unique_candidates[candidate.id] = candidate
        candidates = list(unique_candidates.values())

        hits: List[Tuple[Article, int]] = []
        for candidate in candidates:
            c_simhash = getattr(candidate, "simhash", None)
            candidate_simhash = simhash_from_storage(
                int(c_simhash) if c_simhash is not None else None
            )
            if candidate_simhash is None:
                continue
            distance = hamming_distance(simhash_value, candidate_simhash)
            if distance <= self.simhash_threshold:
                hits.append((candidate, distance))

        if not hits:
            return generate_cluster_id(), 0.0

        def sort_key(item: Tuple[Article, int]):
            cand, dist = item
            time_delta = time_distance_seconds(
                published_date, getattr(cand, "published_date", None)
            )
            cand_id = getattr(cand, "id", 0)
            return (dist, time_delta, -int(cand_id))

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

        other_clusters = {
            cand.cluster_id
            for cand, _ in hits
            if cand.cluster_id and cand.cluster_id != target_cluster
        }

        for other_cluster in other_clusters:
            session.query(Article).filter(Article.cluster_id == other_cluster).update(
                {"cluster_id": target_cluster}, synchronize_session=False
            )

        return str(target_cluster), float(duplication_confidence(best_distance))

    def _revalidate_cluster(self, session: Session, cluster_id: Optional[str]) -> None:
        if not cluster_id:
            return
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
            if distance > self.simhash_threshold * 2:
                new_cluster = generate_cluster_id()
                article_record = cast(Any, article)
                article_record.cluster_id = new_cluster
                article_record.duplication_confidence = 0.0
