"""Typed contracts for the admin API surface (`/v1/admin/*`).

Phase 1 of the Refinery GUI decoupling: typed payload shapes for the
read-oriented admin surface. Mirrors the plan-045 projection style used by
the public serving API. No I/O, no orchestration imports — pure boundary
shapes (LAW-B1).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class AdminArticleListItem(BaseModel):
    """One row of the admin triage queue (explicit projection)."""

    id: int
    title: str
    summary: Optional[str] = None
    url: str
    source: Dict[str, Any]
    category: Optional[str] = None
    topics: List[str] = Field(default_factory=list)
    published_at: Optional[datetime] = None
    collected_at: Optional[datetime] = None
    final_score: Optional[float] = None
    score_components: Optional[Dict[str, Optional[float]]] = None
    why_ranked: List[str] = Field(default_factory=list)
    processing_status: Optional[str] = None
    error_message: Optional[str] = None
    published_url: Optional[str] = None
    refinery_id: Optional[str] = None


class AdminArticlePagination(BaseModel):
    """Deterministic cursor pagination (same shape as the public API)."""

    next_cursor: Optional[str] = None
    has_more: bool = False
    page_size: int
    returned: int


class AdminArticleListEnvelope(BaseModel):
    data: List[AdminArticleListItem]
    pagination: AdminArticlePagination
    filters: Dict[str, Any]
    meta: Dict[str, Any]


class AdminArticleDetail(BaseModel):
    """Full article detail: list-row fields + content + state snapshots."""

    id: int
    title: str
    summary: Optional[str] = None
    url: str
    source: Dict[str, Any]
    category: Optional[str] = None
    topics: List[str] = Field(default_factory=list)
    published_at: Optional[datetime] = None
    collected_at: Optional[datetime] = None
    final_score: Optional[float] = None
    score_components: Optional[Dict[str, Optional[float]]] = None
    why_ranked: List[str] = Field(default_factory=list)
    processing_status: Optional[str] = None
    error_message: Optional[str] = None
    published_url: Optional[str] = None
    refinery_id: Optional[str] = None
    content: Optional[str] = None
    cluster_id: Optional[str] = None
    article_metadata: Dict[str, Any] = Field(default_factory=dict)
    publication: Dict[str, Any] = Field(default_factory=dict)
    audit: Dict[str, Any] = Field(default_factory=dict)
    latest_score: Optional[float] = None
    latest_score_explanation: Optional[Dict[str, Any]] = None


class AdminSourceHealthEnvelope(BaseModel):
    """Source health records parsed from the collector export artifact."""

    sources: List[Dict[str, Any]] = Field(default_factory=list)


class AdminAnalyticsEnvelope(BaseModel):
    """Analytics read model (build_analytics_read_model) plus as_of."""

    stats: List[Dict[str, Any]] = Field(default_factory=list)
    total_articles: int = 0
    source_perf: List[Dict[str, Any]] = Field(default_factory=list)
    avg_score_overall: float = 0.0
    dist: Dict[str, Any] = Field(default_factory=dict)
    cats: List[Dict[str, Any]] = Field(default_factory=list)
    top_sources: List[Dict[str, Any]] = Field(default_factory=list)
    as_of: str


class AdminConfigSnapshot(BaseModel):
    """Sanitized, allowlisted config read — never tokens or keys."""

    environment: str
    debug: bool = False
    timezone: str = "UTC"
    github: Dict[str, Any] = Field(default_factory=dict)
    ollama: Dict[str, Any] = Field(default_factory=dict)
    scoring: Dict[str, Any] = Field(default_factory=dict)
    sources: List[Dict[str, Any]] = Field(default_factory=list)


class AdminAuditStatusUpdate(BaseModel):
    """Body for recording an auditor outcome (metadata only)."""

    audit_status: str = Field(min_length=1)
    reason: str = ""


class AdminRejectRequest(BaseModel):
    """Body for rejecting a named publication attempt."""

    reason: str = ""


AdminMutationStatus = Literal["ok", "not_found", "noop"]


class AdminMutationResult(BaseModel):
    status: AdminMutationStatus
    detail: str
    updated: int = 0
