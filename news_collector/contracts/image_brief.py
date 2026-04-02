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
]


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
    updated_at: datetime

    model_config = ConfigDict(extra="forbid")
