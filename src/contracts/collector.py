"""Contracts for collector outputs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, TypedDict

from src.utils.pydantic_compat import get_pydantic_module

_pydantic = get_pydantic_module()
AnyHttpUrl = _pydantic.AnyHttpUrl
BaseModel = _pydantic.BaseModel
ConfigDict = _pydantic.ConfigDict
Field = _pydantic.Field
field_validator = _pydantic.field_validator
model_validator = _pydantic.model_validator

from config.settings import TEXT_PROCESSING_CONFIG

from .common import ArticleMetadata, ArticleMetadataModel

SUPPORTED_LANGUAGES = set(
    TEXT_PROCESSING_CONFIG.get("supported_languages", ["en", "es"])
)


class CollectorArticlePayload(TypedDict, total=False):
    """Serialized representation of an article produced by collectors."""

    url: str
    original_url: str
    title: str
    summary: str
    content: str
    source_id: str
    source_name: str
    category: str
    published_date: datetime
    published_tz_offset_minutes: int
    published_tz_name: str
    authors: List[str]
    language: str
    doi: str
    journal: str
    is_preprint: bool
    word_count: int
    reading_time_minutes: int
    article_metadata: ArticleMetadata


class CollectorArticleModel(BaseModel):
    """Pydantic model validating collector payloads before persistence."""

    url: AnyHttpUrl
    original_url: str | None = None
    title: str = Field(min_length=10)
    summary: str = Field(
        min_length=TEXT_PROCESSING_CONFIG.get("min_content_length", 50)
    )
    content: str | None = None
    source_id: str = Field(min_length=2)
    source_name: str = Field(min_length=2)
    category: str = Field(min_length=2)
    published_date: datetime
    published_tz_offset_minutes: int | None = None
    published_tz_name: str | None = None
    authors: List[str] = Field(default_factory=list)
    language: str = Field(default="en")
    doi: str | None = None
    journal: str | None = None
    is_preprint: bool = False
    word_count: int = Field(gt=0)
    reading_time_minutes: int = Field(gt=0)
    article_metadata: ArticleMetadataModel = Field(default_factory=ArticleMetadataModel)

    model_config = ConfigDict(from_attributes=True, extra="allow")

    @field_validator("published_date", mode="before")
    @classmethod
    def ensure_datetime(cls, value: Any) -> datetime:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)
        raise TypeError("published_date must be a datetime instance")

    @field_validator("authors", mode="before")
    @classmethod
    def normalize_authors(cls, value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, (list, tuple)):
            return [str(author).strip() for author in value if str(author).strip()]
        raise TypeError("authors must be a list of strings")

    @field_validator("language", mode="before")
    @classmethod
    def normalize_language(cls, value: Any) -> str:
        if value is None:
            return "en"
        normalized = str(value).lower()
        if normalized not in SUPPORTED_LANGUAGES:
            raise ValueError(
                f"language must be one of {sorted(SUPPORTED_LANGUAGES)}, got '{value}'"
            )
        return normalized

    @model_validator(mode="after")
    def ensure_metadata(cls, model: "CollectorArticleModel") -> "CollectorArticleModel":
        model.article_metadata.ensure_original_url(model.original_url or str(model.url))
        model.original_url = model.article_metadata.original_url
        if model.word_count < len(model.summary.split()):
            raise ValueError(
                "word_count must be greater or equal to the number of words in summary"
            )
        return model

    def model_dump_for_storage(self) -> Dict[str, Any]:
        """Return a dict ready for persistence."""
        data = self.model_dump(mode="python")
        data["url"] = str(self.url)
        if data.get("original_url") is not None:
            data["original_url"] = str(data["original_url"])
        data["article_metadata"] = self.article_metadata.model_dump_for_storage()
        return data
