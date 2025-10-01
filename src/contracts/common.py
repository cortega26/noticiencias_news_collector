"""Common shared contract definitions."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, TypedDict

from src.utils.pydantic_compat import get_pydantic_module

_pydantic = get_pydantic_module()
BaseModel = _pydantic.BaseModel
ConfigDict = _pydantic.ConfigDict
Field = _pydantic.Field
model_validator = _pydantic.model_validator

from .enrichment import ArticleEnrichment, ArticleEnrichmentModel


class ArticleMetadata(TypedDict, total=False):
    """Metadata stored alongside collector payloads."""

    source_metadata: Dict[str, Any]
    credibility_score: float
    processing_timestamp: str
    original_url: str
    enrichment: ArticleEnrichment


class ArticleMetadataModel(BaseModel):
    """Validated metadata attached to collected articles."""

    source_metadata: Dict[str, Any] = Field(default_factory=dict)
    credibility_score: float | None = None
    processing_timestamp: datetime | None = None
    original_url: str | None = None
    enrichment: ArticleEnrichmentModel | None = None

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="after")
    def validate_ranges(cls, model: "ArticleMetadataModel") -> "ArticleMetadataModel":
        credibility = model.credibility_score
        if credibility is not None and not (0.0 <= credibility <= 1.0):
            raise ValueError("credibility_score must be between 0 and 1 inclusive")
        if model.original_url is not None and not model.original_url.startswith("http"):
            raise ValueError("original_url must start with http or https")
        return model

    def ensure_original_url(self, fallback: str) -> "ArticleMetadataModel":
        """Ensure original_url is populated with a sensible fallback."""

        if not self.original_url:
            self.original_url = fallback
        return self

    def model_dump_for_storage(self) -> Dict[str, Any]:
        """Return metadata serialized for persistence."""

        data = self.model_dump(mode="python")
        timestamp = data.get("processing_timestamp")
        if timestamp is not None:
            data["processing_timestamp"] = timestamp.isoformat()
        if self.enrichment is not None:
            data["enrichment"] = self.enrichment.model_dump(mode="python")
        return data
