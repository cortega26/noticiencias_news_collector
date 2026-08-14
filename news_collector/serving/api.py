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
import hmac
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Sequence, Tuple

from dateutil import parser as date_parser
from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from noticiencias.config_manager import load_config
from sqlalchemy import and_, func, or_
from sqlalchemy.engine import Row as RowType
from sqlalchemy.orm import aliased

from news_collector.config.settings import get_runtime_config
from news_collector.contracts.admin import (
    AdminAnalyticsEnvelope,
    AdminArticleDetail,
    AdminArticleListEnvelope,
    AdminArticleListItem,
    AdminArticlePagination,
    AdminAuditStatusUpdate,
    AdminConfigSnapshot,
    AdminMutationResult,
    AdminRejectRequest,
    AdminSourceHealthEnvelope,
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
    app = FastAPI(title="Noticiencias API", version="1.0.0")

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

    return app


__all__ = ["create_app"]
