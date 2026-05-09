"""Typed contract for per-source health and reliability reporting."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

SourceOperationalState = Literal[
    "healthy_full_text",
    "healthy_summary_only",
    "partial_yield_flaky",
    "failing_suppressed_candidate",
]

SourceFailureTaxonomy = Literal[
    "feed_fetch_failure",
    "article_fetch_blocked",
    "content_too_short",
    "js_render_required",
    "anti_bot_block",
    "extraction_parser_mismatch",
    "editorial_relevance_rejection",
    "publication_contract_failure",
    "unknown_failure",
]


class SourceHealthRecord(BaseModel):
    """Stable record shape for `data/exports/source_health.json`."""

    source_id: str
    source_name: Optional[str] = None
    language: Optional[str] = None
    content_mode: str = "unknown"
    enrichment_strategy: str = "http"
    fetch_mode: Optional[str] = None
    feed_ok: bool = False
    pipeline_ok: bool = False
    content_ok: bool = False
    articles_found: int = Field(default=0, ge=0)
    articles_saved: int = Field(default=0, ge=0)
    save_ratio: float = Field(default=0.0, ge=0.0)
    total_enrichment_attempted: int = Field(default=0, ge=0)
    total_publishable: int = Field(default=0, ge=0)
    publishable_ratio: float = Field(default=0.0, ge=0.0)
    avg_enrichment_time: float = Field(default=0.0, ge=0.0)
    avg_content_length: float = Field(default=0.0, ge=0.0)
    http_attempts: int = Field(default=0, ge=0)
    plain_http_attempts: int = Field(default=0, ge=0)
    plain_http_success: int = Field(default=0, ge=0)
    plain_http_success_rate: float = Field(default=0.0, ge=0.0)
    scrapling_http_attempts: int = Field(default=0, ge=0)
    scrapling_http_success: int = Field(default=0, ge=0)
    scrapling_http_success_rate: float = Field(default=0.0, ge=0.0)
    headless_attempts: int = Field(default=0, ge=0)
    scrapling_stealth_attempts: int = Field(default=0, ge=0)
    scrapling_stealth_success: int = Field(default=0, ge=0)
    scrapling_stealth_success_rate: float = Field(default=0.0, ge=0.0)
    proxy_attempts: int = Field(default=0, ge=0)
    scholarly_attempts: int = Field(default=0, ge=0)
    proxy_requests_used: int = Field(default=0, ge=0)
    headless_seconds_used: float = Field(default=0.0, ge=0.0)
    last_run: Optional[str] = None
    latency: float = Field(default=0.0, ge=0.0)
    last_error_message: Optional[str] = None
    failure_taxonomy: Optional[SourceFailureTaxonomy] = None
    operational_state: SourceOperationalState
