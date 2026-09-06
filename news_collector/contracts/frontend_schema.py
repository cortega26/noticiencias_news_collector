"""
Contract definition for the Frontend Content Schema.
This file MUST match src/content.config.ts in the frontend repository.
Any mismatch here will cause continuous deployment failures.
"""

from __future__ import annotations

from datetime import date as dt_date
from datetime import datetime as dt_datetime
from typing import List, Optional, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)

from ._constants import SCHEMA_VERSION

# Social distribution identity (plan social-distribution §8/§9). A `social.id`
# is the lowercase SHA-256 hex digest that keys the distribution ledger; it is
# never derived from title, permalink, or deploy SHA.
SOCIAL_ID_PATTERN = r"^[0-9a-f]{64}$"


class HeadlinesVariants(BaseModel):
    """Variants of headlines for A/B testing or display."""

    question: Optional[str] = None
    benefit: Optional[str] = None


class FactCheckItem(BaseModel):
    """Fact check status item."""

    label: str
    status: str


class SourceItem(BaseModel):
    """Source citation item."""

    title: str = Field(..., min_length=1)
    url: HttpUrl
    publisher: Optional[str] = None
    date: Optional[str] = None


class GlossaryItem(BaseModel):
    """Glossary term and definition."""

    term: str = Field(..., min_length=1)
    definition: str = Field(..., min_length=1)


class ImageObject(BaseModel):
    """Complex image object support."""

    src: str
    width: int = Field(..., gt=0)
    height: int = Field(..., gt=0)
    alt: Optional[str] = None


class SocialConfig(BaseModel):
    """Opt-in social distribution decision for a post (plan social-distribution §9).

    Optional and non-nullable. Mirrors the ``social`` object in
    ``src/content.config.ts``. ``publish`` is a strict boolean (no ``"true"`` /
    ``0`` / ``1`` coercion); ``id`` is a 64-char lowercase hex digest, required
    and non-empty when ``publish`` is true and validated against the pattern
    whenever supplied.
    """

    model_config = ConfigDict(extra="forbid")

    publish: bool = Field(default=False)
    id: Optional[str] = Field(default=None, pattern=SOCIAL_ID_PATTERN)

    @field_validator("publish", mode="before")
    @classmethod
    def _publish_must_be_bool(cls, v):
        # Strict: reject "true", 1, 0, None — the frontend Zod contract uses a
        # bare z.boolean() which does not coerce.
        if not isinstance(v, bool):
            raise ValueError("social.publish must be a boolean")
        return v

    @model_validator(mode="after")
    def _id_required_when_publishing(self) -> "SocialConfig":
        if self.publish and not (self.id or "").strip():
            raise ValueError(
                "social.id is required and non-empty when social.publish is true"
            )
        return self


class AstroPost(BaseModel):
    """
    Strict contract for Astro Content Collection 'posts'.
    Matches src/content.config.ts v1.
    """

    # Core Fields
    title: str = Field(..., min_length=5, description="Article Title")
    schema_version: int = Field(
        default=SCHEMA_VERSION, ge=1, description="Schema Version"
    )
    excerpt: str = Field(
        ..., min_length=10, description="SEO Meta Description / Excerpt"
    )
    author: str = Field(default="Noticiencias")
    date: Union[dt_date, dt_datetime] = Field(..., description="Publish Date")

    # Taxonomy
    categories: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)

    # Media
    # Supports string (legacy/simple) or object (optimized)
    image: Union[str, ImageObject]
    image_alt: Optional[str] = None

    # Legacy / Compatibility
    permalink: Optional[str] = None

    # Backend / Refinery Fields
    source_url: Optional[HttpUrl] = None
    refinery_id: Optional[str] = None
    headlines_variants: Optional[HeadlinesVariants] = None

    # Custom Noticiencias Fields
    translation_method: Optional[str] = None
    editorial_score: Optional[float] = None
    review_status: Optional[str] = None
    confidence: Optional[str] = None
    investigation: bool = Field(default=False)
    featured: bool = Field(default=False)
    featured_rank: Optional[int] = None
    summary_points: Optional[List[str]] = None
    uncertainty_note: Optional[str] = None
    glossary: Optional[List[GlossaryItem]] = None
    requires_uncertainty_note: bool = Field(default=False)

    fact_check: Optional[List[FactCheckItem]] = None
    why_it_matters: Optional[List[str]] = None
    series: Optional[str] = None
    sources: Optional[List[SourceItem]] = None

    # Social distribution opt-in (plan social-distribution §9). Absent by
    # default; an explicit `social: null` is rejected (the Zod contract is
    # `.optional()`, not `.nullish()`).
    social: Optional[SocialConfig] = None

    @field_validator("social", mode="before")
    @classmethod
    def _social_not_null(cls, v):
        if v is None:
            raise ValueError(
                "social must be an object, not null (omit the key to disable)"
            )
        return v

    @field_validator("date")
    @classmethod
    def ensure_date_format(cls, v):
        # We allow datetime but clean it to date if time is 00:00:00?
        # Astro handles both.
        return v

    @model_validator(mode="after")
    def ensure_alt_text_contract(self) -> "AstroPost":
        object_alt = (
            self.image.alt.strip()
            if isinstance(self.image, ImageObject) and self.image.alt
            else ""
        )
        if not object_alt and not (self.image_alt or "").strip():
            raise ValueError(
                "image_alt is required when image does not provide inline alt text"
            )
        return self
