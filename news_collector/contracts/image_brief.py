"""Typed contract for editorial image brief sidecars."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

IMAGE_BRIEF_STATUS_VALUES = (
    "needs_editorial_image",
    "editorial_image_ready",
    "resolved",
)
IMAGE_BRIEF_REASON_VALUES = (
    "missing_source_image",
    "image_download_failed",
    "placeholder_image_debt",
    "unproven_image_rights",
)
IMAGE_PROMPT_VERSION = "editorial-image-v1"

ImageBriefStatus = Literal[
    "needs_editorial_image",
    "editorial_image_ready",
    "resolved",
]
ImageBriefReason = Literal[
    "missing_source_image",
    "image_download_failed",
    "placeholder_image_debt",
    "missing_alt_text",
    "third_party_image_blocked",
    "unproven_image_rights",
]
ImageOrigin = Literal["unknown", "ai_generated", "licensed", "original"]
IMAGE_ORIGIN_VALUES = ("unknown", "ai_generated", "licensed", "original")


class ImageGenerationMetadata(BaseModel):
    """Generation evidence verified against the staged asset's actual bytes."""

    prompt: str = Field(min_length=5, max_length=20000)
    tool: str = Field(min_length=2, max_length=100)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    width: int = Field(gt=0)
    height: int = Field(gt=0)

    model_config = ConfigDict(extra="forbid")


class ImageBriefModel(BaseModel):
    """Editorial task persisted when an article needs a curated image."""

    slug: str = Field(min_length=3)
    article_id: str = Field(min_length=1)
    status: ImageBriefStatus = "needs_editorial_image"
    reason: ImageBriefReason
    topic: str = Field(min_length=5)
    news_angle: str = Field(min_length=10)
    scientific_domain: str = Field(min_length=2)
    subject_scene: str = Field(min_length=5)
    tone: str = Field(min_length=5)
    source_url: str | None = None
    draft_alt_text: str = Field(min_length=5)
    prompt_version: str = Field(default=IMAGE_PROMPT_VERSION, min_length=3)
    generated_prompt: str = Field(min_length=50)
    uploaded_asset_path: str | None = None
    # Provenance recorded at upload; `unknown` keeps legacy sidecars loadable.
    # `ai_generated` drives the visible alt/caption disclosure (plan 169).
    image_origin: ImageOrigin = "unknown"
    generation_metadata: ImageGenerationMetadata | None = None
    asset_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    asset_width: int | None = Field(default=None, gt=0)
    asset_height: int | None = Field(default=None, gt=0)
    updated_at: datetime

    model_config = ConfigDict(extra="forbid")
