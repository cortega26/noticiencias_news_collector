"""
Contract models for frontend CI webhook callbacks.

Validates and structures inbound POST payloads from the Noticiencias
frontend CI pipelines (Content Guard, GitHub Pages deploy).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field


class DiagnosticResult(BaseModel):
    """A single check result within a webhook event."""

    check: str
    status: Literal["pass", "fail"]
    filesCount: Optional[int] = Field(default=None, alias="filesCount")
    errors: List[Any] = Field(default_factory=list)
    article_count: Optional[int] = Field(default=None, alias="article_count")
    deploy_url: Optional[str] = Field(default=None, alias="deploy_url")

    model_config = {"populate_by_name": True}


class FrontendWebhookEvent(BaseModel):
    """Base model for all frontend webhook events."""

    event: str
    commit_sha: str = Field(alias="commit_sha")
    branch: str
    status: Literal["pass", "fail", "success"]
    diagnostics: List[DiagnosticResult] = Field(default_factory=list)
    frontend_ref: str = Field(alias="frontend_ref")
    run_url: str = Field(alias="run_url")
    timestamp: Optional[datetime] = None

    model_config = {"populate_by_name": True}


class ValidationResultEvent(FrontendWebhookEvent):
    """Webhook payload when Content Guard completes (pass or fail)."""

    event: Literal["validation_result"] = "validation_result"


class PublishCompleteEvent(FrontendWebhookEvent):
    """Webhook payload when deployment to GitHub Pages completes."""

    event: Literal["publish_complete"] = "publish_complete"


# Union type for dispatch
AnyWebhookEvent = Union[ValidationResultEvent, PublishCompleteEvent]


def parse_webhook_payload(payload: Dict[str, Any]) -> AnyWebhookEvent:
    """Parse and validate an inbound webhook payload, dispatching by event type.

    Raises:
        ValueError: If the event type is unknown.
        ValidationError: If the payload fails Pydantic validation.
    """
    event_type = payload.get("event")
    if event_type == "validation_result":
        return ValidationResultEvent.model_validate(payload)
    elif event_type == "publish_complete":
        return PublishCompleteEvent.model_validate(payload)
    else:
        raise ValueError(f"Unknown webhook event type: {event_type!r}")
