"""Shared contracts for validated pipeline payloads."""

from ._constants import MANIFEST_FILENAME, SCHEMA_VERSION
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
from .pipeline_e2e import PipelineE2ERunSummary, PipelineStageSnapshot
from .publication_validation import (
    FrontendCheckResult,
    PublicationAttemptStageResult,
    PublicationAttemptSummary,
    PublicationValidationSummary,
)
from .scoring import (
    ScoringComponents,
    ScoringComponentsModel,
    ScoringRequest,
    ScoringRequestModel,
)
from .source_health import SourceHealthRecord

__all__ = [
    "ArticleEnrichment",
    "ArticleEnrichmentModel",
    "ArticleForEnrichment",
    "ArticleForEnrichmentModel",
    "ArticleMetadata",
    "ArticleMetadataModel",
    "CollectorArticleModel",
    "CollectorArticlePayload",
    "FrontendCheckResult",
    "IMAGE_BRIEF_REASON_VALUES",
    "IMAGE_BRIEF_STATUS_VALUES",
    "IMAGE_PROMPT_VERSION",
    "ImageBriefModel",
    "PublicationAttemptStageResult",
    "PublicationAttemptSummary",
    "PublicationValidationSummary",
    "PipelineE2ERunSummary",
    "PipelineStageSnapshot",
    "ScoringComponents",
    "ScoringComponentsModel",
    "ScoringRequest",
    "ScoringRequestModel",
    "SourceHealthRecord",
]
