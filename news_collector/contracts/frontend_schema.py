"""
Contract definition for the Frontend Content Schema.
This file MUST match src/content/config.ts in the frontend repository.
Any mismatch here will cause continuous deployment failures.
"""
from __future__ import annotations

from datetime import date as dt_date, datetime as dt_datetime
from typing import List, Literal, Optional, Union

from pydantic import BaseModel, Field, HttpUrl, field_validator


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


class ImageObject(BaseModel):
    """Complex image object support."""
    src: str
    width: int = Field(..., gt=0)
    height: int = Field(..., gt=0)
    alt: Optional[str] = None


class AstroPost(BaseModel):
    """
    Strict contract for Astro Content Collection 'posts'.
    Matches src/content/config.ts v1.
    """
    # Core Fields
    title: str = Field(..., min_length=5, description="Article Title")
    schema_version: int = Field(default=1, ge=1, description="Schema Version")
    excerpt: str = Field(..., min_length=10, description="SEO Meta Description / Excerpt")
    author: str = Field(default="Noticiencias")
    date: Union[dt_date, dt_datetime] = Field(..., description="Publish Date")
    
    # Taxonomy
    categories: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)

    # Media
    # Supports string (legacy/simple) or object (optimized)
    image: Optional[Union[str, ImageObject]] = None
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

    fact_check: Optional[List[FactCheckItem]] = None
    why_it_matters: Optional[List[str]] = None
    series: Optional[str] = None
    sources: Optional[List[SourceItem]] = None

    @field_validator("date")
    @classmethod
    def ensure_date_format(cls, v):
        # We allow datetime but clean it to date if time is 00:00:00?
        # Astro handles both.
        return v
