"""Contracts for collector outputs."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any, Dict, List, TypedDict

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from news_collector.config.settings import get_runtime_config
from news_collector.utils.url_canonicalizer import canonicalize_url

from .common import ArticleMetadata, ArticleMetadataModel


def _supported_languages() -> set[str]:
    """Read live so a refresh_runtime_config() change takes effect immediately."""
    return set(
        get_runtime_config().text_processing_config.get(
            "supported_languages", ["en", "es"]
        )
    )


def _ensure_not_none(value: Any) -> Any:
    if value is None:
        raise ValueError("published_date is required and cannot be None")
    return value


def _from_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _from_date(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def _from_iso_string(value: str) -> datetime:
    raw_value = value
    normalized = raw_value.strip()
    if not normalized:
        raise ValueError("published_date cannot be empty")
    if normalized.endswith(("Z", "z")):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(
            f"published_date has invalid ISO-8601 value: {raw_value!r}"
        ) from exc
    return _from_datetime(parsed)


def _from_epoch(value: int | float) -> datetime:
    epoch_seconds = float(value)
    # Guard common JSON epoch-milliseconds payloads.
    if abs(epoch_seconds) >= 1e11:
        epoch_seconds /= 1000.0
    try:
        return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise ValueError(
            f"published_date epoch value is out of range: {value!r}"
        ) from exc


def _coerce_published_date(value: Any) -> datetime:
    normalized_value = _ensure_not_none(value)

    if isinstance(normalized_value, datetime):
        return _from_datetime(normalized_value)

    if isinstance(normalized_value, date):
        return _from_date(normalized_value)

    if isinstance(normalized_value, str):
        return _from_iso_string(normalized_value)

    if isinstance(normalized_value, bool):
        raise ValueError(
            f"published_date must not be boolean: received {normalized_value!r}"
        )

    if isinstance(normalized_value, (int, float)):
        return _from_epoch(normalized_value)

    raise ValueError(
        "published_date must be datetime/date/ISO-8601 string/epoch seconds, "
        f"got {type(normalized_value).__name__}: {normalized_value!r}"
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
    image_url: str
    image_alt: str


class CollectorArticleModel(BaseModel):
    """Pydantic model validating collector payloads before persistence."""

    url: AnyHttpUrl
    original_url: str | None = None
    title: str = Field(min_length=10)
    summary: str = Field(min_length=0)  # Relaxed: checked in validator
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
    word_count: int = Field(default=0)
    reading_time_minutes: int = Field(default=1, gt=0)
    article_metadata: ArticleMetadataModel = Field(default_factory=ArticleMetadataModel)
    image_url: str | None = None
    image_alt: str | None = None
    content_mode: str = Field(default="full_text")
    min_summary_length_override: int | None = None
    min_content_length_override: int | None = None
    processing_status_override: str | None = None

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    @field_validator("url", mode="before")
    @classmethod
    def canonicalize_url_field(cls, value: Any) -> str:
        """LAW-4: Canonical URL identity determinism.

        Canonicalization MUST happen at the boundary contract so that
        every persistence and dedup operation uses the canonical form.
        """
        raw = str(value).strip()
        canonical = canonicalize_url(raw)
        if not canonical:
            raise ValueError("URL cannot be empty after canonicalization")
        return canonical

    @field_validator("published_date", mode="before")
    @classmethod
    def ensure_datetime(cls, value: Any) -> datetime:
        return _coerce_published_date(value)

    @field_validator("word_count", mode="before")
    @classmethod
    def sanitize_word_count(cls, value: Any) -> int:
        """Clamp invalid word counts (NaN, negative, non-numeric) to safe values."""
        if value is None:
            return 0
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0
        if numeric != numeric:  # NaN
            return 0
        return max(0, int(numeric))

    @field_validator("reading_time_minutes", mode="before")
    @classmethod
    def sanitize_reading_time(cls, value: Any) -> int:
        """Clamp reading-time to a positive integer; the schema requires > 0."""
        if value is None:
            return 1
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 1
        if numeric != numeric:  # NaN
            return 1
        return max(1, int(numeric))

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
        supported_languages = _supported_languages()
        if normalized not in supported_languages:
            raise ValueError(
                f"language must be one of {sorted(supported_languages)}, got '{value}'"
            )
        return normalized

    @model_validator(mode="after")
    def ensure_valid_content(self) -> "CollectorArticleModel":
        self.article_metadata.ensure_original_url(self.original_url or str(self.url))
        self.original_url = self.article_metadata.original_url

        # Validation: We relax the strict length check here to allow "Discovery" of candidates.
        # The strict 500-char limit will be enforced in the Enrichment stage (Stage B)
        # before marking an article as 'pending' (ready for publishing).

        # We still enforce a sanity check to avoid empty garbage.
        min_sanity_len = 1

        summary_len = len(self.summary.strip()) if self.summary else 0
        content_len = len(self.content.strip()) if self.content else 0

        if summary_len < min_sanity_len and content_len < min_sanity_len:
            # Just a warning log in production, but here we raise if it's truly empty
            raise ValueError("Article content/summary empty. Likely extraction error.")

        return self

    @field_validator("content")
    @classmethod
    def validate_content_quality(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return value
        if len(value.strip()) < 10:
            raise ValueError("Article too short")
        # Removed aggressive quote balancing check which was false-flagging valid articles.
        return value

    @field_validator("authors", mode="after")
    @classmethod
    def validate_authors_meaningful(cls, value: List[str]) -> List[str]:
        generic_names = {"admin", "staff", "editor", "redaction", "anonymous"}
        filtered = [
            a for a in value if a.lower().replace(".", "").strip() not in generic_names
        ]
        if not filtered and value:
            return []
        return filtered

    def model_dump_for_storage(self) -> Dict[str, Any]:
        """Return a dict ready for persistence."""
        data = self.model_dump(mode="python")
        data["url"] = str(self.url)
        if data.get("original_url") is not None:
            data["original_url"] = str(data["original_url"])
        if self.image_url:
            self.article_metadata.image_url = self.image_url
        if self.image_alt:
            self.article_metadata.image_alt = self.image_alt
        data["article_metadata"] = self.article_metadata.model_dump_for_storage()
        return data
