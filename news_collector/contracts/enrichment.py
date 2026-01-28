"""Contracts for enrichment pipeline payloads."""

from __future__ import annotations

from typing import List, TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator

SUPPORTED_LANGUAGES = {"en", "es", "pt", "fr"}


class ArticleForEnrichment(TypedDict, total=False):
    """Minimal payload accepted by the enrichment pipeline."""

    title: str
    summary: str
    content: str
    language: str


class ArticleEnrichment(TypedDict, total=False):
    """Structured enrichment data attached to collector payloads."""

    language: str
    normalized_title: str
    normalized_summary: str
    entities: List[str]
    topics: List[str]
    sentiment: str
    sentiment: str
    model_version: str
    editorial_display_category: str


class ArticleForEnrichmentModel(BaseModel):
    """Pydantic model ensuring enrichment inputs have usable text."""

    title: str = ""
    summary: str = ""
    content: str = ""
    language: str | None = None

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="after")
    def ensure_text_present(self) -> "ArticleForEnrichmentModel":
        if not (self.title or self.summary or self.content):
            raise ValueError(
                "enrichment payload requires at least one of title, summary, or content"
            )
        return self


class ArticleEnrichmentModel(BaseModel):
    """Validated enrichment payload with deterministic structure."""

    language: str = Field(min_length=2)
    normalized_title: str = Field(min_length=0)  # Allow empty if normalization fails
    normalized_summary: str = Field(min_length=0)  # Allow empty
    entities: List[str] = Field(default_factory=list)
    topics: List[str] = Field(default_factory=list)
    sentiment: str = Field(min_length=3)
    model_version: str = Field(min_length=1)
    editorial_display_category: str | None = Field(default=None)

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="after")
    def normalize_fields(self) -> "ArticleEnrichmentModel":
        language = self.language.lower()
        if language not in SUPPORTED_LANGUAGES:
            raise ValueError(
                f"language must be one of {sorted(SUPPORTED_LANGUAGES)}, got '{self.language}'"
            )
        sentiment = self.sentiment.lower()
        if sentiment not in {"positive", "negative", "neutral"}:
            raise ValueError("sentiment must be 'positive', 'negative', or 'neutral'")
        self.language = language
        self.sentiment = sentiment
        self.entities = self.entities[:10]
        self.topics = self.topics[:5] if self.topics else ["general"]
        return self
