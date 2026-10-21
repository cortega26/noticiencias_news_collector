"""Durable editorial checkpoint, independent of the frontend media contract."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from news_collector.contracts.editorial_draft import EditorialDraft


class CheckpointIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    final_slug: str
    canonical_date: str
    output_filename: str
    is_new: bool


class PublicationCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    article_id: str
    article: dict[str, JsonValue]
    draft: EditorialDraft
    identity: CheckpointIdentity
    fingerprint: str = Field(min_length=64, max_length=64)
    status: Literal["ready", "waiting_for_image", "succeeded", "failed"] = "ready"
    image_reason: str | None = None
    image_brief_slug: str | None = None
    pr_url: str | None = None


class PublicationItemOutcome(BaseModel):
    """Per-item terminal/pending evidence, including rejection before a draft exists."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    article_id: str
    status: Literal["succeeded", "failed", "waiting_for_image"]
    processed_count: int = 0
    editorial_completed_count: int = 0
    image_reason: str | None = None
    image_brief_slug: str | None = None
    pr_url: str | None = None
    message: str | None = None
    error_code: str | None = None
