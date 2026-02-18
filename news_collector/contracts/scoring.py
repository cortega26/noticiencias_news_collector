"""Contracts for scoring requests passed to storage."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Mapping, TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ScoringComponents(TypedDict, total=False):
    """Components contributing to a final article score."""

    source_credibility: float
    recency: float
    content_quality: float
    engagement: float
    engagement_potential: float


class ScoringComponentsModel(BaseModel):
    """Validated representation of score components."""

    source_credibility: float
    recency: float
    content_quality: float
    engagement: float | None = None
    engagement_potential: float | None = None

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="after")
    def validate_component_ranges(self) -> "ScoringComponentsModel":
        for field_name in (
            "source_credibility",
            "recency",
            "content_quality",
            "engagement",
            "engagement_potential",
        ):
            value = getattr(self, field_name)
            if value is None:
                continue
            if not (0.0 <= value <= 1.0):
                raise ValueError(
                    f"{field_name.replace('_', ' ')} must be between 0 and 1 inclusive"
                )
        if self.engagement is None and self.engagement_potential is None:
            raise ValueError(
                "components must define either 'engagement' or 'engagement_potential'"
            )
        return self

    def get_engagement_value(self) -> float:
        """Return whichever engagement field is populated."""

        return (
            self.engagement
            if self.engagement is not None
            else self.engagement_potential or 0.0
        )


class ScoringRequest(TypedDict, total=False):
    """Payload used when persisting article scores."""

    final_score: float
    should_include: bool
    components: ScoringComponents
    weights: Mapping[str, float]
    version: str
    explanation: Dict[str, Any]
    penalties: Dict[str, Any]
    calculated_at: str


class ScoringRequestModel(BaseModel):
    """Validated scoring payload ensuring numeric stability."""

    final_score: float
    should_include: bool
    components: ScoringComponentsModel
    weights: Dict[str, float] = Field(default_factory=dict)
    version: str = "1.0"
    explanation: Dict[str, Any] = Field(default_factory=dict)
    penalties: Dict[str, Any] | None = None
    calculated_at: datetime | None = None

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="after")
    def validate_ranges(self) -> "ScoringRequestModel":
        if not (0.0 <= self.final_score <= 1.0):
            raise ValueError("final_score must be between 0 and 1 inclusive")
        if self.weights:
            total = 0.0
            for key, value in self.weights.items():
                if not (0.0 <= value <= 1.0):
                    raise ValueError(
                        f"weight '{key}' must be between 0 and 1 inclusive"
                    )
                total += value
            if not (0.99 <= total <= 1.01):
                raise ValueError("weights must sum to approximately 1.0")
        return self

    def model_dump_for_storage(self) -> Dict[str, Any]:
        """Return a serializable scoring payload."""

        return self.model_dump()


class ArticleScoringData(BaseModel):
    """Raw article data required for scoring."""

    id: int
    title: str
    summary: str | None = None
    url: str
    published_date: datetime | str | None = None
    collected_date: datetime | str | None = None
    source_id: str
    article_metadata: Dict[str, Any] = Field(default_factory=dict)
    peer_reviewed: bool | None = None
    is_preprint: bool | None = None
    doi: str | None = None
    journal: str | None = None
    content: str | None = None
    duplication_confidence: float = 0.0
    word_count: int = 0

    model_config = ConfigDict(extra="ignore")


class ScoringInputModel(BaseModel):
    """Validated input payload for the scorer."""

    article: ArticleScoringData
    source_config: Dict[str, Any] | None = None

    model_config = ConfigDict(extra="ignore")
