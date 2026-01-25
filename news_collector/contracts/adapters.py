"""Adapters to convert between system objects and contracts."""

from typing import Any, Dict, List

from news_collector.contracts.export import ExportArticleModel
from news_collector.contracts.scoring import ArticleScoringData, ScoringInputModel
from news_collector.contracts.validation import (
    ArticleValidationItem,
    ArticleValidationPayload,
)
from news_collector.storage.models import Article


def adapt_article_to_export(article: Article) -> ExportArticleModel:
    """Safely converts an ORM Article to an ExportArticleModel."""

    return ExportArticleModel(
        id=article.id,
        title=article.title,
        url=article.url,
        summary=article.summary,
        content=article.content,
        source_name=article.source_name,
        published_date=(
            article.published_date.isoformat() if article.published_date else None
        ),
        published_at=article.published_at.isoformat() if article.published_at else None,
        published_url=article.published_url,
        collected_date=(
            article.collected_date.isoformat() if article.collected_date else None
        ),
        score=article.final_score,
        image_url=(
            article.article_metadata.get("image_url")
            if article.article_metadata
            else None
        ),
        metadata=article.article_metadata or {},
        authors=article.authors or [],
        category=article.category,
        components=article.score_components or {},
    )


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
    """Converts a list of ORM articles to validation payload."""
    items = []
    for art in articles:
        # We start with to_dict to capture generic fields
        base_data = art.to_dict()
        # Ensure content is present as per current logic
        base_data["content"] = art.content
        items.append(ArticleValidationItem(**base_data))

    return ArticleValidationPayload(articles=items)
