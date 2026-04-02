"""
Module role: Adapters to safely convert between raw ORM/system objects and validated Pydantic contracts.

Inputs:
- ORM Article objects or raw dictionaries representing articles.
- Source configuration dictionaries.

Outputs:
- Strictly validated Pydantic models (ExportArticleModel, ArticleScoringData, ArticleValidationPayload).

Side effects:
- None. This module is purely functional and performs no I/O.

Invariants:
- LAW-1: Data Contracts Are Mandatory. Must encapsulate all data crossing system boundaries.
- LAW-2: Adapters Are the Only Conversion Layer. All transformations to contracts must occur here.
- Must not perform external network calls or database writes.

Failure modes:
- Missing required fields in input will raise Pydantic validation errors.
- Type mismatches will raise Pydantic validation errors.
"""

from typing import Any, Dict, List, Mapping, cast

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import NoInspectionAvailable
from sqlalchemy.orm.exc import DetachedInstanceError

from news_collector.contracts.export import ExportArticleModel
from news_collector.contracts.scoring import ArticleScoringData, ScoringInputModel
from news_collector.contracts.validation import (
    ArticleValidationItem,
    ArticleValidationPayload,
)
from news_collector.storage.models import Article


def _optional_article_attr(article: Any, attr_name: str, default: Any = None) -> Any:
    """Read optional ORM attributes without triggering lazy loads on detached instances."""
    try:
        state = sa_inspect(article)
    except (NoInspectionAvailable, TypeError):
        return getattr(article, attr_name, default)

    unloaded = getattr(state, "unloaded", set())
    expired = getattr(state, "expired_attributes", set())
    if attr_name in unloaded or attr_name in expired:
        return default

    try:
        return getattr(article, attr_name)
    except DetachedInstanceError:
        return default


def adapt_article_to_export(article: Article) -> ExportArticleModel:
    """Safely converts an ORM Article to an ExportArticleModel."""
    published_at = _optional_article_attr(article, "published_at")
    published_url = _optional_article_attr(article, "published_url")
    collected_date = _optional_article_attr(article, "collected_date")
    final_score = _optional_article_attr(article, "final_score")
    article_metadata = cast(
        Dict[str, Any],
        _optional_article_attr(article, "article_metadata", {}) or {},
    )
    authors = cast(List[str], _optional_article_attr(article, "authors", []) or [])
    category = cast(str | None, _optional_article_attr(article, "category"))
    score_components = cast(
        Dict[str, Any],
        _optional_article_attr(article, "score_components", {}) or {},
    )

    return ExportArticleModel(
        id=cast(int, article.id),
        title=cast(str, article.title),
        url=cast(str, article.url),
        summary=cast(str, article.summary),
        content=cast(str, article.content),
        source_name=cast(str, article.source_name),
        source_id=cast(str, article.source_id),
        published_date=(
            article.published_date.isoformat() if article.published_date else None
        ),
        published_at=published_at.isoformat() if published_at else None,
        published_url=cast(str | None, published_url),
        collected_date=collected_date.isoformat() if collected_date else None,
        score=cast(float | None, final_score),
        image_url=article_metadata.get("image_url") if article_metadata else None,
        metadata=article_metadata,
        authors=authors,
        category=category,
        components=score_components,
    )


def adapt_export_article_to_collector_payload(
    article: Mapping[str, Any],
    *,
    source_name_to_id: Mapping[str, str] | None = None,
) -> Dict[str, Any]:
    """
    Normalizes legacy/export payloads so CollectorArticleModel can validate them.

    Enforces source identity deterministically:
    - Keep canonical `source_id` when present.
    - Accept equivalent key spellings from legacy payloads.
    - Optionally resolve from `source_name` via an explicit deterministic map.
    - Strips keys not declared on CollectorArticleModel (CRIT-03 / LAW-1).
    """
    from news_collector.contracts.collector import CollectorArticleModel

    payload = dict(article)

    def _clean(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    source_id = (
        _clean(payload.get("source_id"))
        or _clean(payload.get("sourceId"))
        or _clean(payload.get("source_slug"))
    )

    if not source_id:
        metadata = payload.get("metadata")
        if isinstance(metadata, dict):
            source_meta = metadata.get("source_metadata")
            source_id = _clean(metadata.get("source_id"))
            if not source_id and isinstance(source_meta, dict):
                source_id = _clean(source_meta.get("source_id")) or _clean(
                    source_meta.get("id")
                )

    if not source_id and source_name_to_id:
        source_name = _clean(payload.get("source_name"))
        if source_name:
            source_id = source_name_to_id.get(source_name.casefold())

    if not source_id:
        raise ValueError(
            "Missing source_id in export payload and deterministic fallback failed"
        )

    payload["source_id"] = source_id

    # Map legacy export 'metadata' block to 'article_metadata' expected by collector payload
    if "metadata" in payload and "article_metadata" not in payload:
        payload["article_metadata"] = payload.pop("metadata")

    # Strip keys not on CollectorArticleModel to comply with extra="forbid" (CRIT-03)
    _ALLOWED = frozenset(CollectorArticleModel.model_fields.keys())
    return {k: v for k, v in payload.items() if k in _ALLOWED}


def adapt_article_to_scoring(article: Any) -> ArticleScoringData:  # Updated return type
    """
    Prepares ORM article for scoring using strict contract.
    """
    return ArticleScoringData(
        id=article.id,
        title=article.title,
        summary=article.summary,
        url=article.url,
        published_date=article.published_date,
        collected_date=article.collected_date,
        source_id=article.source_id,
        article_metadata=article.article_metadata or {},
        peer_reviewed=article.peer_reviewed,
        is_preprint=article.is_preprint,
        doi=article.doi,
        journal=article.journal,
        content=article.content,
        duplication_confidence=getattr(article, "duplication_confidence", 0.0),
        word_count=getattr(article, "word_count", 0),
    )


def adapt_to_scoring_input(
    article: Any, source_config: Dict[str, Any] | None
) -> ScoringInputModel:
    """Creates a validated scoring payload."""
    data = adapt_article_to_scoring(article)
    return ScoringInputModel(article=data, source_config=source_config)


def adapt_to_validation_payload(articles: List[Any]) -> ArticleValidationPayload:
    """Converts a list of ORM articles to validation payload.

    Only declared ArticleValidationItem fields are forwarded to
    enforce the sealed boundary contract (CRIT-03 / LAW-1).
    """
    _VALIDATION_FIELDS = frozenset(ArticleValidationItem.model_fields.keys())
    items = []
    for art in articles:
        base_data = art.to_dict()
        # Ensure content is present as per current logic
        base_data["content"] = art.content
        # Only pass declared fields — extras are forbidden at boundary
        filtered = {k: v for k, v in base_data.items() if k in _VALIDATION_FIELDS}
        items.append(ArticleValidationItem(**filtered))

    return ArticleValidationPayload(articles=items)
