"""Shared contracts for validated pipeline payloads."""

from .collector import CollectorArticleModel, CollectorArticlePayload
from .common import ArticleMetadata, ArticleMetadataModel
from .enrichment import (
    ArticleEnrichment,
    ArticleEnrichmentModel,
    ArticleForEnrichment,
    ArticleForEnrichmentModel,
)
from .image_brief import (
    IMAGE_BRIEF_REASON_VALUES,
    IMAGE_BRIEF_STATUS_VALUES,
    IMAGE_PROMPT_VERSION,
    ImageBriefModel,
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
    "IMAGE_BRIEF_REASON_VALUES",
    "IMAGE_BRIEF_STATUS_VALUES",
    "IMAGE_PROMPT_VERSION",
    "ImageBriefModel",
    "ScoringComponents",
    "ScoringComponentsModel",
    "ScoringRequest",
    "ScoringRequestModel",
]
