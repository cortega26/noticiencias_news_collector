"""Contracts for enrichment pipeline payloads."""

from __future__ import annotations

from typing import List, TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator

SUPPORTED_LANGUAGES = {"en", "es"}


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


class ArticleForEnrichmentModel(BaseModel):
    """Pydantic model ensuring enrichment inputs have usable text."""

    title: str = ""
    summary: str = ""
    content: str = ""
    language: str | None = None

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="after")
    def ensure_text_present(
        cls, model: "ArticleForEnrichmentModel"
    ) -> "ArticleForEnrichmentModel":
        if not (model.title or model.summary or model.content):
            raise ValueError(
                "enrichment payload requires at least one of title, summary, or content"
            )
        return model


class ArticleEnrichmentModel(BaseModel):
    """Validated enrichment payload with deterministic structure."""

    language: str = Field(min_length=2)
    normalized_title: str = Field(min_length=1)
    normalized_summary: str = Field(min_length=1)
    entities: List[str] = Field(default_factory=list)
    topics: List[str] = Field(default_factory=list)
    sentiment: str = Field(min_length=3)

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="after")
    def normalize_fields(
        cls, model: "ArticleEnrichmentModel"
    ) -> "ArticleEnrichmentModel":
        language = model.language.lower()
        if language not in SUPPORTED_LANGUAGES:
            raise ValueError(
                f"language must be one of {sorted(SUPPORTED_LANGUAGES)}, got '{model.language}'"
            )
        sentiment = model.sentiment.lower()
        if sentiment not in {"positive", "negative", "neutral"}:
            raise ValueError("sentiment must be 'positive', 'negative', or 'neutral'")
        model.language = language
        model.sentiment = sentiment
        model.entities = model.entities[:10]
        model.topics = model.topics[:5] if model.topics else ["general"]
        return model
