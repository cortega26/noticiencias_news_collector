"""Shared contracts for validated pipeline payloads."""

from .collector import CollectorArticleModel, CollectorArticlePayload
from .common import ArticleMetadata, ArticleMetadataModel
from .enrichment import (
    ArticleEnrichment,
    ArticleEnrichmentModel,
    ArticleForEnrichment,
    ArticleForEnrichmentModel,
)
from .scoring import (
    ScoringComponents,
    ScoringComponentsModel,
    ScoringRequest,
    ScoringRequestModel,
)

__all__ = [
    "ArticleEnrichment",
    "ArticleEnrichmentModel",
    "ArticleForEnrichment",
    "ArticleForEnrichmentModel",
    "ArticleMetadata",
    "ArticleMetadataModel",
    "CollectorArticleModel",
    "CollectorArticlePayload",
    "ScoringComponents",
    "ScoringComponentsModel",
    "ScoringRequest",
    "ScoringRequestModel",
]
