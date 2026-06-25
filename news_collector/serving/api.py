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
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import aliased

from news_collector.storage.database import DatabaseManager, get_database_manager
from news_collector.storage.models import Article, ScoreLog
from news_collector.utils.logger import get_logger
from news_collector.utils.pydantic_compat import get_pydantic_module

logger = get_logger().create_module_logger("serving.api")

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


def _encode_cursor(article: Article) -> str:
    score = article.final_score or 0.0
    collected = article.collected_date or datetime.now(timezone.utc)
    payload = f"{score:.6f}|{collected.isoformat()}|{article.id}"
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("utf-8")


def _extract_topics(article: Article) -> List[str]:
    metadata: Dict[str, Any] = (
        article.article_metadata if isinstance(article.article_metadata, dict) else {}
    )
    enrichment = metadata.get("enrichment") if isinstance(metadata, dict) else {}
    topics = enrichment.get("topics") if isinstance(enrichment, dict) else None
    if isinstance(topics, (list, tuple)):
        return [str(topic) for topic in topics]
    keywords_obj = article.keywords
    keywords: List[Any] = keywords_obj if isinstance(keywords_obj, list) else []
    return [str(keyword) for keyword in keywords] if keywords else []


def _summarize_why_ranked(  # noqa: C901
    article: Article, score_log: Optional[ScoreLog]
) -> List[str]:
    if score_log and isinstance(score_log.score_explanation, dict):
        explanation = score_log.score_explanation
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
        article.score_components if isinstance(article.score_components, dict) else {}
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


def _build_article_payload(
    article: Article, score_log: Optional[ScoreLog]
) -> Dict[str, Any]:
    return {
        "id": article.id,
        "title": article.title,
        "summary": article.summary,
        "url": article.url,
        "source": {"id": article.source_id, "name": article.source_name},
        "category": article.category,
        "topics": _extract_topics(article),
        "published_at": article.published_date,
        "collected_at": article.collected_date,
        "final_score": article.final_score,
        "score_components": article.score_components,
        "why_ranked": _summarize_why_ranked(article, score_log),
    }


def verify_webhook_token(
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> None:
    """Verify Bearer token against WEBHOOK_API_KEY env var (constant-time)."""
    webhook_api_key = os.environ.get("WEBHOOK_API_KEY", "")
    if not webhook_api_key:
        return  # dev mode — skip auth

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

            query = (
                session.query(Article, score_log_alias)
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

            records: List[Tuple[Article, Optional[ScoreLog]]] = query.limit(
                params.page_size + 1
            ).all()

            has_more = len(records) > params.page_size
            if has_more:
                records = records[: params.page_size]

            payload = [_build_article_payload(article, log) for article, log in records]
            next_cursor = _encode_cursor(records[-1][0]) if has_more else None

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
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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

    return app


__all__ = ["create_app"]
