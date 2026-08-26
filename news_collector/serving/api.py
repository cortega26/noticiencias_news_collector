"""
Module role: Provides a FastAPI HTTP surface for retrieving ranked articles and checking subsystem health.

Inputs:
- HTTP query parameters for filtering articles (source, topic, date bounds, pagination).
- Database manager dependencies injected via FastAPI.

Outputs:
- JSON payloads structuring paginated article lists, filters, metadata, and cursors.
- Readiness and health probe status dictionaries.

Side effects:
- Issues SQLAlchemy queries against the database for fetching articles, score logs, and health status.

Invariants:
- Uses deterministic sorting (descending score, collected date, and ID) enabling cursor-based pagination.
- Validates date range logic consistently, ensuring the start date never exceeds the end date.
- Employs base64 url-safe encoding and decoding for opaque cursor payload serialization.

Failure modes:
- Raises HTTP 400 exceptions if cursor formats are malformed.
- Raises HTTP 503 if the database is unavailable during readiness probes.
"""

from __future__ import annotations

import base64
import contextlib
import hmac
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    Iterable,
    List,
    Optional,
    Sequence,
    Tuple,
    cast,
)

from dateutil import parser as date_parser
from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from noticiencias.config_manager import load_config
from sqlalchemy import and_, func, or_
from sqlalchemy.engine import Row as RowType
from sqlalchemy.orm import aliased

from news_collector.config import settings as config_settings
from news_collector.config.settings import get_runtime_config
from news_collector.contracts.admin import (
    AdminAnalyticsEnvelope,
    AdminArticleDetail,
    AdminArticleListEnvelope,
    AdminArticleListItem,
    AdminArticlePagination,
    AdminAuditStatusUpdate,
    AdminBulkResetFailure,
    AdminBulkResetRequest,
    AdminBulkResetResult,
    AdminCollectRequest,
    AdminCollectStarted,
    AdminCollectStatus,
    AdminConfigSnapshot,
    AdminContentEnvelope,
    AdminImageBriefItem,
    AdminImageBriefUpdate,
    AdminImageBriefUploadResult,
    AdminImageQueueEnvelope,
    AdminMutationResult,
    AdminPromptsEnvelope,
    AdminRejectRequest,
    AdminRunStatus,
    AdminSourceHealthEnvelope,
    AdminSourceListEnvelope,
    AdminSourceListItem,
    AdminSourceToggleRequest,
    AdminSourceUpsert,
)
from news_collector.contracts.image_brief import ImageBriefModel
from news_collector.logic.workflows.collection_run_workflow import (
    CollectionRunWorkflow,
)
from news_collector.storage.database import DatabaseManager, get_database_manager
from news_collector.storage.models import Article, ScoreLog
from news_collector.utils.logger import get_logger
from news_collector.utils.pydantic_compat import get_pydantic_module

logger = get_logger().create_module_logger("serving.api")

# Collector export artifact consumed by the admin source-health endpoint.
# Overridable in tests via monkeypatch.
ADMIN_SOURCE_HEALTH_PATH = "data/exports/source_health.json"

# processing_status values the admin triage queue can filter by. Mirrors the
# statuses the storage layer transitions between (pending/new → publishing →
# rejected/completed).
_ADMIN_VALID_STATUSES = frozenset(
    {"new", "pending", "publishing", "rejected", "completed"}
)

if TYPE_CHECKING:  # pragma: no cover - typing-only imports
    from pydantic import BaseModel, Field, field_validator, model_validator
else:
    _pydantic = get_pydantic_module()
    BaseModel = _pydantic.BaseModel
    Field = _pydantic.Field
    field_validator = _pydantic.field_validator
    model_validator = _pydantic.model_validator


class ArticleListParams(BaseModel):
    """Validated query parameters for listing ranked articles."""

    source: Optional[List[str]] = Field(default=None, alias="source")
    topic: Optional[List[str]] = Field(default=None, alias="topic")
    date_from: Optional[datetime] = Field(default=None, alias="date_from")
    date_to: Optional[datetime] = Field(default=None, alias="date_to")
    page_size: int = Field(default=20, ge=1, le=50, alias="page_size")
    cursor: Optional[str] = Field(default=None, alias="cursor")

    @field_validator("source", "topic", mode="before")
    def _normalize_list(cls, value: Any) -> Optional[List[str]]:  # noqa: D401
        """Allow repeated or comma-separated query values."""
        if value is None:
            return None
        values: List[str] = []
        if isinstance(value, (list, tuple)):
            seq: Iterable[str] = value
        else:
            seq = [value]
        for item in seq:
            if not isinstance(item, str):
                raise ValueError("invalid list entry")
            parts = [part.strip() for part in item.split(",") if part.strip()]
            values.extend(parts)
        return values or None

    @field_validator("date_from", "date_to", mode="before")
    def _parse_datetime(cls, value: Any) -> Optional[datetime]:
        if value in (None, ""):
            return None
        if isinstance(value, datetime):
            parsed = value
        else:
            try:
                parsed = date_parser.isoparse(str(value))
            except (ValueError, TypeError) as exc:
                raise ValueError("invalid datetime format") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    @model_validator(mode="after")
    def _validate_date_range(self) -> "ArticleListParams":
        if self.date_to is not None and self.date_from is not None:  # noqa: SIM102
            if self.date_to < self.date_from:
                raise ValueError("date_to must be greater than or equal to date_from")
        return self


class ArticleResponse(BaseModel):
    id: int
    title: str
    summary: Optional[str]
    url: str
    source: Dict[str, Any]
    category: Optional[str]
    topics: List[str]
    published_at: Optional[datetime]
    collected_at: Optional[datetime]
    final_score: Optional[float]
    score_components: Optional[Dict[str, float]]
    why_ranked: List[str]


class RelatedSourceResponse(BaseModel):
    id: str
    name: str


class RelatedArticleResponse(BaseModel):
    id: int
    title: str
    source: RelatedSourceResponse
    url: str
    score: Optional[float]


class PaginationResponse(BaseModel):
    next_cursor: Optional[str]
    has_more: bool
    page_size: int
    returned: int


class ArticlesEnvelope(BaseModel):
    data: List[ArticleResponse]
    pagination: PaginationResponse
    filters: Dict[str, Any]
    meta: Dict[str, Any]


def _decode_cursor(raw_cursor: str) -> Tuple[float, datetime, int]:
    try:
        decoded = base64.urlsafe_b64decode(raw_cursor.encode("utf-8")).decode("utf-8")
        score_part, collected_part, id_part = decoded.split("|")
        score = float(score_part)
        collected = datetime.fromisoformat(collected_part)
        if collected.tzinfo is None:
            collected = collected.replace(tzinfo=timezone.utc)
        return score, collected, int(id_part)
    except Exception as exc:  # pragma: no cover - defensive branch
        raise HTTPException(status_code=400, detail="Invalid cursor") from exc


def _encode_cursor(row: RowType) -> str:
    score = row.final_score or 0.0
    collected = row.collected_date or datetime.now(timezone.utc)
    payload = f"{score:.6f}|{collected.isoformat()}|{row.article_id}"
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("utf-8")


def _extract_topics_from_metadata(metadata: Any, keywords: Any) -> List[str]:
    """Extract topics from an article's metadata dict (JSON column value)."""
    meta: Dict[str, Any] = metadata if isinstance(metadata, dict) else {}
    enrichment = meta.get("enrichment") if isinstance(meta, dict) else {}
    topics = enrichment.get("topics") if isinstance(enrichment, dict) else None
    if isinstance(topics, (list, tuple)):
        return [str(topic) for topic in topics]
    keyword_list: List[Any] = keywords if isinstance(keywords, list) else []
    return [str(keyword) for keyword in keyword_list] if keyword_list else []


def _summarize_why_ranked(  # noqa: C901
    row: RowType,
) -> List[str]:
    score_log: Any = {"score_explanation": row.score_explanation}
    if isinstance(score_log.get("score_explanation"), dict):
        explanation = score_log["score_explanation"]
        strengths = explanation.get("key_strengths")
        if isinstance(strengths, list) and strengths:
            return [str(item) for item in strengths][:3]
        breakdown = explanation.get("component_breakdown", {})
        factors: List[str] = []
        if isinstance(breakdown, dict):
            for component in breakdown.values():
                component_factors = (
                    component.get("factors") if isinstance(component, dict) else None
                )
                if isinstance(component_factors, list):
                    factors.extend(str(factor) for factor in component_factors)
        if factors:
            return factors[:3]
    components: Dict[str, Any] = (
        row.score_components if isinstance(row.score_components, dict) else {}
    )
    if isinstance(components, dict) and components:
        ordered = sorted(
            components.items(),
            key=lambda item: (item[1] if isinstance(item[1], (int, float)) else 0.0),
            reverse=True,
        )
        summaries = []
        for name, value in ordered[:3]:
            try:
                score_value = float(value)
            except (TypeError, ValueError):
                score_value = 0.0
            summaries.append(
                f"{name.replace('_', ' ').title()} score {score_value:.2f}"
            )
        if summaries:
            return summaries
    return ["Ranked by editorial scorer"]


def _apply_topic_filters(query, topics: Sequence[str]):
    if not topics:
        return query
    topics_json = func.coalesce(
        func.json_extract(Article.article_metadata, "$.enrichment.topics"),
        "",
    )
    for topic in topics:
        pattern = f'"{topic}"'
        query = query.filter(func.instr(topics_json, pattern) > 0)
    return query


def _build_article_payload(row: RowType) -> Dict[str, Any]:
    """Build the article payload from an explicit-projection row (plan 045).

    The row carries exactly the columns the response needs — no full ORM
    hydration of Article/ScoreLog entities.
    """
    topics = _extract_topics_from_metadata(row.article_metadata, row.keywords)
    return {
        "id": row.article_id,
        "title": row.title,
        "summary": row.summary,
        "url": row.url,
        "source": {"id": row.source_id, "name": row.source_name},
        "category": row.category,
        "topics": topics,
        "published_at": row.published_date,
        "collected_at": row.collected_date,
        "final_score": row.final_score,
        "score_components": row.score_components,
        "why_ranked": _summarize_why_ranked(row),
    }


def _build_admin_list_item(row: RowType) -> AdminArticleListItem:
    """Build an admin triage-row payload from an explicit-projection row.

    Same projection discipline as ``_build_article_payload`` (plan 045):
    the query selects exactly the columns used here, so no full ORM
    hydration happens for the list.
    """
    topics = _extract_topics_from_metadata(row.article_metadata, row.keywords)
    metadata = row.article_metadata or {}
    refinery_id = (metadata.get("publication") or {}).get("refinery_id")
    return AdminArticleListItem(
        id=row.article_id,
        title=row.title,
        summary=row.summary,
        url=row.url,
        source={"id": row.source_id, "name": row.source_name},
        category=row.category,
        topics=topics,
        published_at=row.published_date,
        collected_at=row.collected_date,
        final_score=row.final_score,
        score_components=row.score_components,
        why_ranked=_summarize_why_ranked(row),
        processing_status=row.processing_status,
        error_message=row.error_message,
        published_url=row.published_url,
        refinery_id=refinery_id,
    )


def _normalize_config_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a config-save payload into the full Config shape.

    Accepts both a PARTIAL patch (any section dicts) and the sanitized
    snapshot returned by GET /v1/admin/config: top-level
    environment/debug/timezone move under app.*, `sources`/`meta` (read-only
    extras) are dropped, and empty-string optional model names become None
    (the form renders None optionals as ""). Secrets (github.token,
    nvidia/gemini api_key) are never accepted.
    """
    for section in ("github", "nvidia", "gemini"):
        if isinstance(payload.get(section), dict):
            for key in ("token", "api_key"):
                payload[section].pop(key, None)

    normalized: Dict[str, Any] = {}
    for key, value in payload.items():
        if key in ("sources", "meta"):
            continue
        if key in ("environment", "debug", "timezone"):
            app_section = dict(normalized.get("app", {}))
            app_section[key] = value
            normalized["app"] = app_section
            continue
        normalized[key] = value

    for section in ("ollama", "gemini", "nvidia"):
        if isinstance(normalized.get(section), dict):
            normalized[section] = {
                k: (None if v == "" else v) for k, v in normalized[section].items()
            }
    return normalized


def verify_webhook_token(
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> None:
    """Verify Bearer token against WEBHOOK_API_KEY env var (constant-time).

    Plan 021: fails closed outside the explicit "development" environment
    tier (reusing the existing ``environment``/``is_production``/
    ``is_staging`` runtime config, not inventing a new concept) when no key
    is configured — the previous unconditional fail-open made the webhook
    unauthenticated by default in any deployed environment that simply
    forgot to set ``WEBHOOK_API_KEY``.
    """
    webhook_api_key = os.environ.get("WEBHOOK_API_KEY", "")
    if not webhook_api_key:
        runtime = get_runtime_config()
        if runtime.environment != "development":
            logger.error(
                "WEBHOOK_API_KEY is not set outside the 'development' "
                "environment (environment={}) — refusing unauthenticated "
                "webhook access.",
                runtime.environment,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Webhook authentication is not configured for this environment",
            )
        return  # explicit development-only fail-open

    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
        )
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format. Use: Bearer <token>",
        )
    if not hmac.compare_digest(token, webhook_api_key):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid webhook API key",
        )


def verify_admin_token(
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> None:
    """Verify Bearer token against ADMIN_API_KEY env var (constant-time).

    Same fail-closed semantics as ``verify_webhook_token`` (plan 021), with a
    distinct credential so the admin surface is never reachable with the
    frontend CI webhook key. Outside the explicit "development" environment
    tier an unset key refuses all admin access (503).
    """
    admin_api_key = os.environ.get("ADMIN_API_KEY", "")
    if not admin_api_key:
        runtime = get_runtime_config()
        if runtime.environment != "development":
            logger.error(
                "ADMIN_API_KEY is not set outside the 'development' "
                "environment (environment={}) — refusing unauthenticated "
                "admin access.",
                runtime.environment,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Admin authentication is not configured for this environment",
            )
        return  # explicit development-only fail-open

    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
        )
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format. Use: Bearer <token>",
        )
    if not hmac.compare_digest(token, admin_api_key):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid admin API key",
        )


def create_app(  # noqa: C901
    database_manager: Optional[DatabaseManager] = None,
) -> FastAPI:
    """Create a configured FastAPI application."""

    db_manager = database_manager or get_database_manager()
    collection_run_workflow = CollectionRunWorkflow(db_manager)

    @contextlib.asynccontextmanager
    async def _lifespan(_app: FastAPI):
        # Plan 060 / Phase 4a: restart recovery is deterministic, not
        # timer-dependent — the only process that could be holding a stale
        # "running" lease is the one that just (re)started, so this runs
        # once here rather than on a periodic schedule. This is the first
        # process-startup hook this codebase has needed at all (checked:
        # no `@app.on_event`/`lifespan` precedent exists anywhere in the
        # repo) — `lifespan` is the current, non-deprecated FastAPI
        # mechanism for it.
        recovered = collection_run_workflow.recover_expired_leases()
        if recovered:
            logger.warning(
                "Startup: recovered {} stale collection run(s): {}",
                len(recovered),
                recovered,
            )
        yield

    app = FastAPI(title="Noticiencias API", version="1.0.0", lifespan=_lifespan)

    # Phase 2: the Refinery admin GUI is a separate static app; allow its
    # origin(s) to call the admin surface cross-origin. Explicit allowlist
    # only — never "*" (Bearer auth in headers, no cookies). Defaults cover
    # `astro dev` (4321) and `astro preview` (4322).
    from fastapi.middleware.cors import CORSMiddleware

    cors_origins = [
        origin.strip()
        for origin in os.environ.get(
            "ADMIN_CORS_ORIGINS", "http://localhost:4321,http://localhost:4322"
        ).split(",")
        if origin.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    def get_params(
        source: Optional[List[str]] = Query(None, alias="source"),
        topic: Optional[List[str]] = Query(None, alias="topic"),
        date_from: Optional[Any] = Query(None, alias="date_from"),
        date_to: Optional[Any] = Query(None, alias="date_to"),
        page_size: int = Query(20, alias="page_size"),
        cursor: Optional[str] = Query(None, alias="cursor"),
    ) -> ArticleListParams:
        return ArticleListParams(
            source=source,
            topic=topic,
            date_from=date_from,
            date_to=date_to,
            page_size=page_size,
            cursor=cursor,
        )

    def get_db() -> DatabaseManager:
        return db_manager

    @app.get("/healthz")
    def health_probe(manager: DatabaseManager = Depends(get_db)) -> Dict[str, Any]:
        status = manager.get_health_status()
        return {
            "status": "ok" if status.get("status") == "healthy" else "degraded",
            "details": status,
        }

    @app.get("/readyz")
    def readiness_probe(manager: DatabaseManager = Depends(get_db)) -> Dict[str, Any]:
        try:
            with manager.get_session() as session:
                session.query(func.count(Article.id)).scalar()
        except Exception as exc:  # pragma: no cover - defensive branch
            raise HTTPException(status_code=503, detail="database unavailable") from exc
        return {"status": "ready"}

    @app.get("/v1/articles", response_model=ArticlesEnvelope)
    def list_ranked_articles(
        params: ArticleListParams = Depends(get_params),
        manager: DatabaseManager = Depends(get_db),
    ) -> ArticlesEnvelope:
        score_column = func.coalesce(Article.final_score, 0.0)
        with manager.get_session() as session:
            latest_log_subquery = (
                session.query(
                    ScoreLog.article_id.label("article_id"),
                    func.max(ScoreLog.calculated_at).label("latest_calculated"),
                )
                .group_by(ScoreLog.article_id)
                .subquery()
            )

            score_log_alias = aliased(ScoreLog)

            # Explicit projection (plan 045): select exactly the columns the
            # payload and cursor need instead of hydrating full Article and
            # ScoreLog ORM entities (which include heavy Text/JSON columns).
            query = (
                session.query(
                    Article.id.label("article_id"),
                    Article.title,
                    Article.summary,
                    Article.url,
                    Article.source_id,
                    Article.source_name,
                    Article.category,
                    Article.published_date,
                    Article.collected_date,
                    Article.final_score,
                    Article.score_components,
                    Article.article_metadata,
                    Article.keywords,
                    score_log_alias.id.label("score_log_id"),
                    score_log_alias.score_explanation,
                )
                .outerjoin(
                    latest_log_subquery,
                    latest_log_subquery.c.article_id == Article.id,
                )
                .outerjoin(
                    score_log_alias,
                    and_(
                        score_log_alias.article_id == Article.id,
                        score_log_alias.calculated_at
                        == latest_log_subquery.c.latest_calculated,
                    ),
                )
                .filter(Article.processing_status == "completed")
            )

            if params.source:
                query = query.filter(Article.source_id.in_(params.source))

            if params.date_from:
                query = query.filter(Article.published_date >= params.date_from)

            if params.date_to:
                query = query.filter(Article.published_date <= params.date_to)

            query = _apply_topic_filters(query, params.topic or [])

            if params.cursor:
                cursor_score, cursor_collected, cursor_id = _decode_cursor(
                    params.cursor
                )
                query = query.filter(
                    or_(
                        score_column < cursor_score,
                        and_(
                            score_column == cursor_score,
                            Article.collected_date < cursor_collected,
                        ),
                        and_(
                            score_column == cursor_score,
                            Article.collected_date == cursor_collected,
                            Article.id < cursor_id,
                        ),
                    )
                )

            query = query.order_by(
                score_column.desc(),
                Article.collected_date.desc(),
                Article.id.desc(),
            )

            records: List[RowType] = query.limit(params.page_size + 1).all()

            has_more = len(records) > params.page_size
            if has_more:
                records = records[: params.page_size]

            payload = [_build_article_payload(row) for row in records]
            next_cursor = _encode_cursor(records[-1]) if has_more else None

            return ArticlesEnvelope(
                data=[ArticleResponse(**item) for item in payload],
                pagination=PaginationResponse(
                    next_cursor=next_cursor,
                    has_more=has_more,
                    page_size=params.page_size,
                    returned=len(payload),
                ),
                filters={
                    "source": params.source or [],
                    "topic": params.topic or [],
                    "date_from": (
                        params.date_from.isoformat() if params.date_from else None
                    ),
                    "date_to": params.date_to.isoformat() if params.date_to else None,
                },
                meta={"generated_at": datetime.now(timezone.utc).isoformat()},
            )

    @app.get(
        "/v1/articles/{article_id}/related",
        response_model=List[RelatedArticleResponse],
    )
    def get_related_articles(
        article_id: int,
        manager: DatabaseManager = Depends(get_db),
    ) -> List[RelatedArticleResponse]:
        with manager.get_session() as session:
            article = (
                session.query(Article.id, Article.cluster_id)
                .filter(Article.id == article_id)
                .first()
            )
            if article is None:
                raise HTTPException(status_code=404, detail="Article not found")
            if article.cluster_id is None:
                return []

            related = (
                session.query(Article)
                .filter(
                    Article.cluster_id == article.cluster_id,
                    Article.id != article_id,
                )
                .order_by(
                    func.coalesce(Article.final_score, 0.0).desc(),
                    Article.id.desc(),
                )
                .limit(20)
                .all()
            )
            return [
                RelatedArticleResponse(
                    id=item.id,
                    title=item.title,
                    source=RelatedSourceResponse(
                        id=item.source_id,
                        name=item.source_name,
                    ),
                    url=item.url,
                    score=item.final_score,
                )
                for item in related
            ]

    @app.post(
        "/api/v1/webhook/frontend",
        status_code=status.HTTP_202_ACCEPTED,
    )
    def frontend_webhook(
        payload: Dict[str, Any],
        manager: DatabaseManager = Depends(get_db),
        _: None = Depends(verify_webhook_token),
    ) -> Dict[str, Any]:
        """Receive CI callbacks from the Noticiencias frontend.

        Accepts ``validation_result`` (Content Guard) and
        ``publish_complete`` (GitHub Pages deploy) events.
        Processing is best-effort — the response is always 202.
        """
        from news_collector.contracts.webhook import (
            PublishCompleteEvent,
            ValidationResultEvent,
            parse_webhook_payload,
        )
        from news_collector.serving.webhook_handler import (
            process_publish_complete,
            process_validation_result,
        )

        # Validate payload structure
        try:
            event = parse_webhook_payload(payload)
        except Exception as exc:
            logger.warning("Invalid webhook payload: {}", exc)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Invalid payload: {exc}",
            ) from exc

        # Dispatch by event type (best-effort — always return 202)
        try:
            if isinstance(event, ValidationResultEvent):
                process_validation_result(event, manager)
            elif isinstance(event, PublishCompleteEvent):
                process_publish_complete(event, manager)
        except Exception as exc:
            logger.error(
                "Webhook processing error (event={}): {}",
                event.event,
                exc,
                exc_info=True,
            )

        return {
            "accepted": True,
            "event": event.event,
        }

    # ------------------------------------------------------------------
    # Admin surface (/v1/admin/*) — Phase 1 of the Refinery GUI decoupling.
    #
    # Read-oriented per LAW-B4 (serving may compose read-only queries against
    # storage). The two mutation endpoints only dispatch to existing,
    # idempotent storage transitions (mirroring the webhook handler pattern);
    # no editorial write workflow lives here (§3.6).
    # ------------------------------------------------------------------

    @app.get("/v1/admin/articles", response_model=AdminArticleListEnvelope)
    def admin_list_articles(
        status_filter: str = Query("pending", alias="status"),
        source: Optional[List[str]] = Query(None, alias="source"),
        page_size: int = Query(20, ge=1, le=50, alias="page_size"),
        cursor: Optional[str] = Query(None, alias="cursor"),
        manager: DatabaseManager = Depends(get_db),
        _: None = Depends(verify_admin_token),
    ) -> AdminArticleListEnvelope:
        if status_filter not in _ADMIN_VALID_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    f"Invalid status '{status_filter}'. "
                    f"Valid: {sorted(_ADMIN_VALID_STATUSES)}"
                ),
            )

        score_column = func.coalesce(Article.final_score, 0.0)
        with manager.get_session() as session:
            latest_log_subquery = (
                session.query(
                    ScoreLog.article_id.label("article_id"),
                    func.max(ScoreLog.calculated_at).label("latest_calculated"),
                )
                .group_by(ScoreLog.article_id)
                .subquery()
            )
            score_log_alias = aliased(ScoreLog)

            query = (
                session.query(
                    Article.id.label("article_id"),
                    Article.title,
                    Article.summary,
                    Article.url,
                    Article.source_id,
                    Article.source_name,
                    Article.category,
                    Article.published_date,
                    Article.collected_date,
                    Article.final_score,
                    Article.score_components,
                    Article.article_metadata,
                    Article.keywords,
                    Article.processing_status,
                    Article.error_message,
                    Article.published_url,
                    score_log_alias.score_explanation,
                )
                .outerjoin(
                    latest_log_subquery,
                    latest_log_subquery.c.article_id == Article.id,
                )
                .outerjoin(
                    score_log_alias,
                    and_(
                        score_log_alias.article_id == Article.id,
                        score_log_alias.calculated_at
                        == latest_log_subquery.c.latest_calculated,
                    ),
                )
                .filter(Article.processing_status == status_filter)
            )

            if source:
                query = query.filter(Article.source_id.in_(source))

            if cursor:
                cursor_score, cursor_collected, cursor_id = _decode_cursor(cursor)
                query = query.filter(
                    or_(
                        score_column < cursor_score,
                        and_(
                            score_column == cursor_score,
                            Article.collected_date < cursor_collected,
                        ),
                        and_(
                            score_column == cursor_score,
                            Article.collected_date == cursor_collected,
                            Article.id < cursor_id,
                        ),
                    )
                )

            query = query.order_by(
                score_column.desc(),
                Article.collected_date.desc(),
                Article.id.desc(),
            )

            records: List[RowType] = query.limit(page_size + 1).all()
            has_more = len(records) > page_size
            if has_more:
                records = records[:page_size]

            items = [_build_admin_list_item(row) for row in records]
            next_cursor = _encode_cursor(records[-1]) if has_more else None

            return AdminArticleListEnvelope(
                data=items,
                pagination=AdminArticlePagination(
                    next_cursor=next_cursor,
                    has_more=has_more,
                    page_size=page_size,
                    returned=len(items),
                ),
                filters={"status": status_filter, "source": source or []},
                meta={"generated_at": datetime.now(timezone.utc).isoformat()},
            )

    @app.get(
        "/v1/admin/articles/{article_id}",
        response_model=AdminArticleDetail,
    )
    def admin_article_detail(
        article_id: int,
        manager: DatabaseManager = Depends(get_db),
        _: None = Depends(verify_admin_token),
    ) -> AdminArticleDetail:
        with manager.get_session() as session:
            latest_log_subquery = (
                session.query(
                    ScoreLog.article_id.label("article_id"),
                    func.max(ScoreLog.calculated_at).label("latest_calculated"),
                )
                .group_by(ScoreLog.article_id)
                .subquery()
            )
            score_log_alias = aliased(ScoreLog)

            row = (
                session.query(
                    Article.id.label("article_id"),
                    Article.title,
                    Article.summary,
                    Article.url,
                    Article.source_id,
                    Article.source_name,
                    Article.category,
                    Article.published_date,
                    Article.collected_date,
                    Article.final_score,
                    Article.score_components,
                    Article.article_metadata,
                    Article.keywords,
                    Article.processing_status,
                    Article.error_message,
                    Article.published_url,
                    Article.content,
                    Article.cluster_id,
                    score_log_alias.final_score.label("latest_score"),
                    score_log_alias.score_explanation.label("score_explanation"),
                )
                .outerjoin(
                    latest_log_subquery,
                    latest_log_subquery.c.article_id == Article.id,
                )
                .outerjoin(
                    score_log_alias,
                    and_(
                        score_log_alias.article_id == Article.id,
                        score_log_alias.calculated_at
                        == latest_log_subquery.c.latest_calculated,
                    ),
                )
                .filter(Article.id == article_id)
                .first()
            )
            if row is None:
                raise HTTPException(status_code=404, detail="Article not found")

            list_item = _build_admin_list_item(row)
            metadata = dict(row.article_metadata or {})
            detail = list_item.model_dump()
            detail.update(
                {
                    "content": row.content,
                    "cluster_id": row.cluster_id,
                    "article_metadata": metadata,
                    "publication": metadata.get("publication") or {},
                    "audit": metadata.get("audit") or {},
                    "latest_score": row.latest_score,
                    "latest_score_explanation": row.score_explanation,
                }
            )
            return AdminArticleDetail(**detail)

    @app.get("/v1/admin/sources/health", response_model=AdminSourceHealthEnvelope)
    def admin_source_health(
        _: None = Depends(verify_admin_token),
    ) -> AdminSourceHealthEnvelope:
        import json as _json

        if not os.path.exists(ADMIN_SOURCE_HEALTH_PATH):
            return AdminSourceHealthEnvelope(sources=[])
        try:
            with open(ADMIN_SOURCE_HEALTH_PATH, "r", encoding="utf-8") as f:
                data = _json.load(f)
        except (OSError, ValueError) as exc:
            logger.warning("Failed to read source health export: {}", exc)
            return AdminSourceHealthEnvelope(sources=[])
        records = data.values() if isinstance(data, dict) else data
        return AdminSourceHealthEnvelope(sources=list(records))

    @app.get("/v1/admin/analytics", response_model=AdminAnalyticsEnvelope)
    def admin_analytics(
        manager: DatabaseManager = Depends(get_db),
        _: None = Depends(verify_admin_token),
    ) -> AdminAnalyticsEnvelope:
        from apps.refinery.analytics_read_model import build_analytics_read_model

        model = build_analytics_read_model(manager)
        return AdminAnalyticsEnvelope(
            **model,
            as_of=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )

    @app.get("/v1/admin/config", response_model=AdminConfigSnapshot)
    def admin_config(
        _: None = Depends(verify_admin_token),
    ) -> AdminConfigSnapshot:
        cfg = load_config()
        github = {
            "user_name": cfg.github.user_name,
            "source_repo_url": cfg.github.source_repo_url,
            "target_repo_url": cfg.github.target_repo_url,
        }
        ollama = {
            "model": cfg.ollama.model,
            "translator_model": cfg.ollama.translator_model,
            "editor_model": cfg.ollama.editor_model,
            "headlines_model": cfg.ollama.headlines_model,
            "enrichment_model": cfg.ollama.enrichment_model,
        }
        weights_value: Any = cfg.scoring.weights
        if hasattr(weights_value, "model_dump"):
            weights_value = weights_value.model_dump(mode="python")
        scoring = {
            "weights": weights_value,
        }
        return AdminConfigSnapshot(
            environment=cfg.app.environment,
            debug=cfg.app.debug,
            timezone=cfg.app.timezone,
            github=github,
            ollama=ollama,
            scoring=scoring,
        )

    @app.post(
        "/v1/admin/articles/{article_id}/audit-status",
        response_model=AdminMutationResult,
    )
    def admin_audit_status(
        article_id: int,
        payload: AdminAuditStatusUpdate,
        manager: DatabaseManager = Depends(get_db),
        _: None = Depends(verify_admin_token),
    ) -> AdminMutationResult:
        ok = manager.update_article_audit_status(
            article_id, payload.audit_status, payload.reason
        )
        if not ok:
            raise HTTPException(status_code=404, detail="Article not found")
        return AdminMutationResult(
            status="ok",
            detail=f"Audit status '{payload.audit_status}' recorded",
            updated=1,
        )

    @app.post(
        "/v1/admin/articles/{article_id}/reject",
        response_model=AdminMutationResult,
    )
    def admin_reject_article(
        article_id: int,
        payload: AdminRejectRequest,
        manager: DatabaseManager = Depends(get_db),
        _: None = Depends(verify_admin_token),
    ) -> AdminMutationResult:
        with manager.get_session() as session:
            article = session.query(Article).filter(Article.id == article_id).first()
            if article is None:
                raise HTTPException(status_code=404, detail="Article not found")
            metadata = article.article_metadata or {}
            refinery_id = (metadata.get("publication") or {}).get("refinery_id")
            if not refinery_id:
                return AdminMutationResult(
                    status="noop",
                    detail="Article has no named publication attempt to reject",
                )
        updated = manager.reject_publication_attempts(
            [str(refinery_id)], payload.reason
        )
        if updated == 0:
            return AdminMutationResult(
                status="noop",
                detail="Publication attempt already rejected or not in flight",
            )
        return AdminMutationResult(
            status="ok",
            detail=f"Rejected publication attempt {refinery_id}",
            updated=updated,
        )

    # ------------------------------------------------------------------
    # Phase 3/4a: operational surface (fetch/reprocess/manage)
    # ------------------------------------------------------------------
    # Plan 060 / Phase 4a: these two routes are now thin wrappers around
    # CollectionRunWorkflow (news_collector/logic/workflows/
    # collection_run_workflow.py) — request parsing, typed-result-to-HTTP-
    # status mapping, response mapping, nothing else. The `workflow_runs`
    # DB row is the only source of truth; no module-global run state.

    @app.post(
        "/v1/admin/collect",
        response_model=AdminCollectStarted,
        status_code=status.HTTP_202_ACCEPTED,
        responses={
            409: {
                "model": AdminCollectStarted,
                "description": "A collection run is already queued or running.",
            }
        },
    )
    def admin_collect(
        payload: AdminCollectRequest,
        response: Response,
        _: None = Depends(verify_admin_token),
    ) -> AdminCollectStarted:
        """Start a collection cycle (async). Dry-run simulates without
        persisting — used by the GUI's fetch-news action and its dry-run
        toggle. Two concurrent calls yield exactly one 202 (started) and
        one 409 (already_running, carrying the existing run's id)."""
        result = collection_run_workflow.start(dry_run=payload.dry_run)
        if result.status == "already_running":
            response.status_code = status.HTTP_409_CONFLICT
            return AdminCollectStarted(
                run_id=str(result.run_id),
                status="running",
                detail=result.detail,
            )
        response.status_code = status.HTTP_202_ACCEPTED
        return AdminCollectStarted(
            run_id=str(result.run_id),
            status="queued",
            detail=(
                "Collection started (dry-run)"
                if payload.dry_run
                else "Collection started"
            ),
        )

    @app.get(
        "/v1/admin/collect/status",
        response_model=AdminCollectStatus,
        responses={
            404: {
                "model": AdminCollectStatus,
                "description": "run_id was given but does not match any run.",
            }
        },
    )
    def admin_collect_status(
        response: Response,
        run_id: Optional[str] = Query(None, alias="run_id"),
        _: None = Depends(verify_admin_token),
    ) -> AdminCollectStatus:
        """Return the most recent collection run (or the named one via
        ?run_id=). An unrecognized run_id returns 404 — it never falls
        back to the latest run."""
        parsed_run_id: Optional[int] = None
        if run_id is not None:
            try:
                parsed_run_id = int(run_id)
            except ValueError:
                parsed_run_id = None
                if run_id:
                    # Non-numeric run_id can never match a workflow_runs.id
                    # — same "unrecognized id" outcome as a numeric id that
                    # doesn't exist, not a 422 (the caller just gets a 404).
                    response.status_code = status.HTTP_404_NOT_FOUND
                    return AdminCollectStatus()

        result = collection_run_workflow.get_status(parsed_run_id)
        if result.status == "not_found":
            if parsed_run_id is not None:
                response.status_code = status.HTTP_404_NOT_FOUND
            return AdminCollectStatus()

        # Invariant: get_status() only sets status="found" alongside a
        # populated run_status (see CollectionRunStatusResult), and its
        # value always comes from workflow_runs.status, which
        # ck_workflow_runs_status constrains to exactly AdminRunStatus's
        # members — cast documents that DB-enforced invariant for the type
        # checker rather than widening AdminRunStatus's own literal type.
        assert result.run_status is not None
        active = result.run_status in ("queued", "running")
        return AdminCollectStatus(
            run_id=str(result.run_id),
            status=cast(AdminRunStatus, result.run_status),
            started_at=result.started_at.isoformat() if result.started_at else None,
            finished_at=result.finished_at.isoformat() if result.finished_at else None,
            error=result.error_detail,
            summary=result.summary,
            active=active,
        )

    @app.post(
        "/v1/admin/articles/{article_id}/reprocess",
        response_model=AdminMutationResult,
    )
    def admin_reprocess_article(
        article_id: int,
        manager: DatabaseManager = Depends(get_db),
        _: None = Depends(verify_admin_token),
    ) -> AdminMutationResult:
        ok = manager.reset_article_for_reprocess(article_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Article not found")
        return AdminMutationResult(
            status="ok",
            detail=f"Article {article_id} reset to pending",
            updated=1,
        )

    @app.get("/v1/admin/sources", response_model=AdminSourceListEnvelope)
    def admin_list_sources(
        manager: DatabaseManager = Depends(get_db),
        _: None = Depends(verify_admin_token),
    ) -> AdminSourceListEnvelope:
        from news_collector.config.sources import ALL_SOURCES

        items: List[AdminSourceListItem] = []
        for source_id in sorted(ALL_SOURCES):
            config = ALL_SOURCES[source_id] or {}
            circuit = manager.get_source_circuit_state(source_id)
            items.append(
                AdminSourceListItem(
                    source_id=source_id,
                    name=config.get("name"),
                    url=config.get("url"),
                    category=config.get("category"),
                    content_mode=config.get("content_mode"),
                    enrichment_strategy=config.get("enrichment_strategy"),
                    is_active=bool(circuit is None or circuit.get("is_active", True)),
                    circuit=circuit,
                )
            )
        return AdminSourceListEnvelope(sources=items)

    @app.post(
        "/v1/admin/sources/{source_id}/toggle",
        response_model=AdminMutationResult,
    )
    def admin_toggle_source(
        source_id: str,
        payload: AdminSourceToggleRequest,
        manager: DatabaseManager = Depends(get_db),
        _: None = Depends(verify_admin_token),
    ) -> AdminMutationResult:
        ok = manager.set_source_active(source_id, payload.active)
        if not ok:
            raise HTTPException(status_code=404, detail="Source not found")
        return AdminMutationResult(
            status="ok",
            detail=f"Source {source_id} {'activated' if payload.active else 'deactivated'}",
            updated=1,
        )

    @app.post(
        "/v1/admin/sources/{source_id}/reset",
        response_model=AdminMutationResult,
    )
    def admin_reset_source_circuit(
        source_id: str,
        manager: DatabaseManager = Depends(get_db),
        _: None = Depends(verify_admin_token),
    ) -> AdminMutationResult:
        state = manager.get_source_circuit_state(source_id)
        if state is None:
            raise HTTPException(status_code=404, detail="Source not found")
        manager.update_source_circuit_state(source_id, success=True)
        return AdminMutationResult(
            status="ok",
            detail=f"Source {source_id} circuit reset to ACTIVE",
            updated=1,
        )

    @app.post("/v1/admin/config", response_model=AdminConfigSnapshot)
    def admin_save_config(
        payload: Dict[str, Any],
        _: None = Depends(verify_admin_token),
    ) -> AdminConfigSnapshot:
        """Validate and persist config.toml — same contract as the Streamlit
        app's save_toml_config (plan 033).

        The payload may be either (a) a PARTIAL patch (any section dicts)
        or (b) the sanitized snapshot returned by GET /v1/admin/config
        (top-level environment/debug/timezone, plus section dicts that may
        carry None values for optional fields). Both shapes are normalized
        into the full Config shape before schema + business-rule
        validation, then written atomically. Secrets are never accepted.
        """
        from noticiencias.config_manager import Config as _Config
        from noticiencias.config_manager import save_config as _save_config

        normalized = _normalize_config_payload(payload)

        # Merge over the current full config (deep) so partial patches
        # validate against the complete shape.
        current = load_config()
        merged = current.model_dump(mode="python")
        for section, values in normalized.items():
            if isinstance(values, dict) and isinstance(merged.get(section), dict):
                merged[section] = {**merged[section], **values}
            else:
                merged[section] = values

        try:
            validated = _Config.model_validate(merged)
            config_settings.validate_config(validated)
        except Exception as exc:
            raise HTTPException(
                status_code=422, detail=f"Config rejected: {exc}"
            ) from exc

        validated._metadata = current._metadata
        _save_config(validated)
        snapshot = config_settings.refresh_runtime_config(validated)

        return AdminConfigSnapshot(
            environment=validated.app.environment,
            debug=validated.app.debug,
            timezone=validated.app.timezone,
            github={
                "user_name": validated.github.user_name,
                "source_repo_url": validated.github.source_repo_url,
                "target_repo_url": validated.github.target_repo_url,
            },
            ollama={
                "model": validated.ollama.model,
                "translator_model": validated.ollama.translator_model,
                "editor_model": validated.ollama.editor_model,
                "headlines_model": validated.ollama.headlines_model,
                "enrichment_model": validated.ollama.enrichment_model,
            },
            scoring={"weights": validated.scoring.weights.model_dump(mode="python")},
            meta={
                "version": snapshot.version,
                "changed_keys": sorted(snapshot.changed_keys),
                "restart_required_keys": sorted(snapshot.restart_required_keys),
            },
        )

    @app.get("/v1/admin/prompts", response_model=AdminPromptsEnvelope)
    def admin_get_prompts(
        _: None = Depends(verify_admin_token),
    ) -> AdminPromptsEnvelope:
        import yaml

        prompts_path = Path("config/prompts.yaml")
        if not prompts_path.exists():
            return AdminPromptsEnvelope(prompts={})
        try:
            with open(prompts_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise HTTPException(
                status_code=500, detail=f"Failed to read prompts: {exc}"
            ) from exc
        return AdminPromptsEnvelope(
            prompts={k: v for k, v in data.items() if isinstance(v, dict)}
        )

    @app.post("/v1/admin/prompts", response_model=AdminPromptsEnvelope)
    def admin_save_prompts(
        payload: AdminPromptsEnvelope,
        _: None = Depends(verify_admin_token),
    ) -> AdminPromptsEnvelope:
        import tempfile

        import yaml

        prompts_path = Path("config/prompts.yaml")
        prompts_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            # Atomic write: never leave a truncated prompts.yaml on crash.
            serialized = yaml.safe_dump(
                payload.prompts,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            )
            fd, tmp_name = tempfile.mkstemp(
                prefix=".prompts-", dir=str(prompts_path.parent)
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(serialized)
                os.replace(tmp_name, prompts_path)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(tmp_name)
                raise
        except (OSError, yaml.YAMLError) as exc:
            raise HTTPException(
                status_code=500, detail=f"Failed to write prompts: {exc}"
            ) from exc
        return payload

    @app.get("/v1/admin/content", response_model=AdminContentEnvelope)
    def admin_published_content(
        _: None = Depends(verify_admin_token),
    ) -> AdminContentEnvelope:
        from apps.refinery.published_content import resolve_published_content_snapshot

        cfg = load_config()
        try:
            snapshot = resolve_published_content_snapshot(
                target_repo_url=cfg.github.target_repo_url,
                collector_repo_root=Path(".").resolve(),
                temp_target_dir=Path("temp/refinery_target"),
                github_token=str(cfg.github.token or ""),
                refresh_clone=False,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"Content snapshot failed: {exc}"
            ) from exc
        return AdminContentEnvelope(
            source_label=snapshot.source_label,
            freshness_label=snapshot.freshness_label,
            articles=[
                {
                    "file_name": article.file_name,
                    "title": article.title,
                    "refinery_id": article.refinery_id,
                    "modified_at": article.modified_at.isoformat(),
                }
                for article in snapshot.articles
            ],
        )

    @app.get("/v1/admin/images", response_model=AdminImageQueueEnvelope)
    def admin_image_queue(
        _: None = Depends(verify_admin_token),
    ) -> AdminImageQueueEnvelope:
        from news_collector.logic.workflows.image_briefs import ImageBriefStore

        store = ImageBriefStore(Path("data"))
        briefs = store.list_briefs()
        return AdminImageQueueEnvelope(
            briefs=[
                AdminImageBriefItem(
                    slug=brief.slug,
                    article_id=brief.article_id,
                    status=brief.status,
                    reason=brief.reason,
                    topic=brief.topic,
                    news_angle=brief.news_angle,
                    scientific_domain=brief.scientific_domain,
                    subject_scene=brief.subject_scene,
                    draft_alt_text=brief.draft_alt_text,
                    tone=brief.tone,
                    updated_at=(
                        brief.updated_at.isoformat()
                        if getattr(brief, "updated_at", None)
                        else None
                    ),
                )
                for brief in briefs
            ]
        )

    @app.put(
        "/v1/admin/images/{slug}",
        response_model=AdminImageBriefUploadResult,
    )
    def admin_update_image_brief(
        slug: str,
        payload: AdminImageBriefUpdate,
        _: None = Depends(verify_admin_token),
    ) -> AdminImageBriefUploadResult:
        """Edit an image brief's editable fields (no asset upload)."""
        from news_collector.logic.workflows.image_briefs import ImageBriefStore

        store = ImageBriefStore(Path("data"))
        brief = store.load_brief(slug)
        if brief is None:
            raise HTTPException(status_code=404, detail="Brief not found")

        updates = payload.model_dump(exclude_none=True)
        if not updates:
            raise HTTPException(status_code=422, detail="No editable fields provided")
        updated = brief.model_copy(
            update={**updates, "updated_at": datetime.now(timezone.utc)}
        )
        try:
            updated = ImageBriefModel.model_validate(updated.model_dump())
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        store.save_brief(updated)
        return AdminImageBriefUploadResult(
            brief=updated.model_dump(mode="json"),
            asset_path=updated.uploaded_asset_path or "",
        )

    @app.post(
        "/v1/admin/images/{slug}/upload",
        response_model=AdminImageBriefUploadResult,
    )
    def admin_upload_image_brief(
        slug: str,
        file: UploadFile = File(...),
        topic: Optional[str] = Form(None),
        news_angle: Optional[str] = Form(None),
        scientific_domain: Optional[str] = Form(None),
        subject_scene: Optional[str] = Form(None),
        draft_alt_text: Optional[str] = Form(None),
        _: None = Depends(verify_admin_token),
    ) -> AdminImageBriefUploadResult:
        """Stage an image asset for a brief (multipart)."""
        from news_collector.logic.workflows.image_briefs import ImageBriefStore

        store = ImageBriefStore(Path("data"))
        brief = store.load_brief(slug)
        if brief is None:
            raise HTTPException(status_code=404, detail="Brief not found")

        content = file.file.read()
        if not content:
            raise HTTPException(status_code=422, detail="Empty file upload")
        updated = store.stage_upload(
            brief=brief,
            filename=file.filename or f"{slug}.png",
            content=content,
            draft_alt_text=draft_alt_text or brief.draft_alt_text,
            topic=topic or brief.topic,
            news_angle=news_angle or brief.news_angle,
            scientific_domain=scientific_domain or brief.scientific_domain,
            subject_scene=subject_scene or brief.subject_scene,
        )
        return AdminImageBriefUploadResult(
            brief=updated.model_dump(mode="json"),
            asset_path=updated.uploaded_asset_path or "",
        )

    @app.delete(
        "/v1/admin/content/{refinery_id}",
        response_model=AdminMutationResult,
    )
    def admin_unpublish_article(
        refinery_id: str,
        manager: DatabaseManager = Depends(get_db),
        _: None = Depends(verify_admin_token),
    ) -> AdminMutationResult:
        """Unpublish one article: git rm + commit + push + DB delete.

        Dispatches to reset_one_article (plan 017 semantics: DB rows are
        deleted only after the git push succeeds).
        """
        from apps.refinery.published_content import (
            find_published_article_by_refinery_id,
            reset_one_article,
            resolve_published_content_snapshot,
        )

        cfg = load_config()
        try:
            snapshot = resolve_published_content_snapshot(
                target_repo_url=cfg.github.target_repo_url,
                collector_repo_root=Path(".").resolve(),
                temp_target_dir=Path("temp/refinery_target"),
                github_token=str(cfg.github.token or ""),
                refresh_clone=True,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"Content snapshot failed: {exc}"
            ) from exc

        article = find_published_article_by_refinery_id(snapshot.posts_dir, refinery_id)
        if article is None:
            raise HTTPException(status_code=404, detail="Published article not found")

        try:
            reset_one_article(snapshot.repo_root, article, manager)
        except Exception as exc:
            logger.error("Unpublish failed for {}: {}", refinery_id, exc)
            raise HTTPException(
                status_code=500, detail=f"Unpublish failed: {exc}"
            ) from exc
        return AdminMutationResult(
            status="ok",
            detail=f"Unpublished {refinery_id}",
            updated=1,
        )

    @app.post(
        "/v1/admin/content/bulk-reset",
        response_model=AdminBulkResetResult,
    )
    def admin_bulk_reset_content(
        payload: AdminBulkResetRequest,
        manager: DatabaseManager = Depends(get_db),
        _: None = Depends(verify_admin_token),
    ) -> AdminBulkResetResult:
        """Bulk unpublish (batch_cap 5, continue-on-error, per-item report)."""
        from apps.refinery.bulk_helper import run_bulk
        from apps.refinery.published_content import (
            find_published_article_by_refinery_id,
            reset_one_article,
            resolve_published_content_snapshot,
        )

        cfg = load_config()
        try:
            snapshot = resolve_published_content_snapshot(
                target_repo_url=cfg.github.target_repo_url,
                collector_repo_root=Path(".").resolve(),
                temp_target_dir=Path("temp/refinery_target"),
                github_token=str(cfg.github.token or ""),
                refresh_clone=True,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"Content snapshot failed: {exc}"
            ) from exc

        def _reset_one(refinery_id: str) -> None:
            article = find_published_article_by_refinery_id(
                snapshot.posts_dir, refinery_id
            )
            if article is None:
                raise FileNotFoundError(f"No published article for {refinery_id}")
            reset_one_article(snapshot.repo_root, article, manager)

        result = run_bulk(
            items=payload.refinery_ids,
            action=_reset_one,
            batch_cap=5,
        )
        return AdminBulkResetResult(
            succeeded=[str(item) for item in result.succeeded],
            failed=[
                AdminBulkResetFailure(
                    refinery_id=str(item) if item else "",
                    error=error,
                )
                for item, error in [
                    (f.item, f.error) for f in result.failed if f.item is not None
                ]
            ],
            summary=result.summary,
        )

    @app.delete(
        "/v1/admin/sources/{source_id}",
        response_model=AdminMutationResult,
    )
    def admin_delete_source(
        source_id: str,
        manager: DatabaseManager = Depends(get_db),
        _: None = Depends(verify_admin_token),
    ) -> AdminMutationResult:
        """Delete a source: remove from sources.yaml AND drop the DB row."""
        from news_collector.config.sources import ALL_SOURCES, save_sources

        if source_id not in ALL_SOURCES:
            raise HTTPException(status_code=404, detail="Source not found")

        del ALL_SOURCES[source_id]
        save_sources(ALL_SOURCES)
        ok = manager.delete_source(source_id)
        if not ok:
            logger.warning("Source {} removed from yaml but had no DB row.", source_id)
        return AdminMutationResult(
            status="ok",
            detail=f"Source {source_id} deleted",
            updated=1,
        )

    @app.post("/v1/admin/sources", response_model=AdminMutationResult)
    def admin_upsert_source(
        payload: AdminSourceUpsert,
        manager: DatabaseManager = Depends(get_db),
        _: None = Depends(verify_admin_token),
    ) -> AdminMutationResult:
        """Add or update a source (mirrors the old GUI's source editor).

        Merge semantics on update: start from the existing entry and overlay
        only the provided fields, so blacklist/etag/etag-metadata survive.
        On create, seed the old GUI's defaults. Writes sources.yaml, then
        upserts the DB row for circuit state.
        """
        from news_collector.config.sources import ALL_SOURCES, save_sources

        was_present = payload.source_id in ALL_SOURCES
        existing = dict(ALL_SOURCES.get(payload.source_id, {}))
        new_entry = dict(existing)
        new_entry.update(
            {
                "name": payload.name,
                "url": payload.url,
                "credibility_score": payload.credibility_score,
                "category": payload.category,
                "update_frequency": payload.update_frequency,
                "_group": payload.group,
            }
        )
        if not was_present:
            new_entry.setdefault("language", "en")
            new_entry.setdefault("description", "Added via UI")
            new_entry.setdefault("typical_delay", 0)

        ALL_SOURCES[payload.source_id] = new_entry
        save_sources(ALL_SOURCES)
        manager.upsert_source(payload.source_id, new_entry)

        created = not was_present
        return AdminMutationResult(
            status="ok",
            detail=(
                f"Source {payload.source_id} created"
                if created
                else f"Source {payload.source_id} updated"
            ),
            updated=1,
        )

    return app


__all__ = ["create_app"]
