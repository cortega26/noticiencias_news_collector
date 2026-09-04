"""Typed contracts for the admin API surface (`/v1/admin/*`).

Phase 1 of the Refinery GUI decoupling: typed payload shapes for the
read-oriented admin surface. Mirrors the plan-045 projection style used by
the public serving API. No I/O, no orchestration imports — pure boundary
shapes (LAW-B1).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


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
    # Phase 4c: True when this article is in the current
    # `data/exports/latest_articles.json` shortlist and not already
    # in-flight/published — i.e. "Refine & Publish" can be triggered for it
    # by id. Articles not in the export are published via the URL box.
    publishable: bool = False
    export_score: Optional[float] = None


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
    # Phase 4c (plan 061): same "Refine & Publish" candidacy as the list
    # rows — the detail view renders its own publish button from these.
    publishable: bool = False
    export_score: Optional[float] = None
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
    meta: Dict[str, Any] = Field(default_factory=dict)


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


class AdminCollectRequest(BaseModel):
    """Body for triggering a collection cycle."""

    dry_run: bool = False


AdminRunStatus = Literal[
    "queued", "running", "succeeded", "failed", "cancelled", "interrupted"
]


class AdminCollectStatus(BaseModel):
    """Status of the most recent (or a named) collection run."""

    run_id: Optional[str] = None
    status: AdminRunStatus = "queued"
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error: Optional[str] = None
    summary: Dict[str, Any] = Field(default_factory=dict)
    active: bool = False


class AdminCollectStarted(BaseModel):
    """Response to POST /v1/admin/collect."""

    run_id: str
    status: AdminRunStatus = "queued"
    detail: str


class AdminPublishRequest(BaseModel):
    """Body for POST /v1/admin/publish — exactly one of article_id / article_url."""

    article_id: Optional[int] = None
    article_url: Optional[str] = None
    dry_run: bool = False


class AdminPublishStarted(BaseModel):
    """Response to POST /v1/admin/publish."""

    run_id: str
    status: AdminRunStatus = "queued"
    detail: str


class AdminPublishStatus(BaseModel):
    """Status of the most recent (or a named) publication run."""

    run_id: Optional[str] = None
    status: AdminRunStatus = "queued"
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error: Optional[str] = None
    summary: Dict[str, Any] = Field(default_factory=dict)
    active: bool = False
    # Pulled from summary for convenience — the two things the GUI shows.
    pr_url: Optional[str] = None
    failure_class: Optional[str] = None
    final_slug: Optional[str] = None


class AdminQualityReadability(BaseModel):
    """Deterministic legibility snapshot (plan 065) for one published
    article, lifted from the run's `readability` stage details. All
    Optional: runs predating plan 065 have no such stage."""

    ifsz: Optional[float] = None
    ifh: Optional[float] = None
    grade: Optional[str] = None
    suitability: Optional[float] = None
    words: Optional[int] = None
    sentences: Optional[int] = None


class AdminQualityStageItem(BaseModel):
    """One stage of a publication attempt (`PublicationAttemptStageResult`
    shape, JSON-safe)."""

    name: str
    success: bool = False
    details: Dict[str, Any] = Field(default_factory=dict)


class AdminQualityRunItem(BaseModel):
    """One row of the quality review loop (plan 066): a publication run
    plus the quality signals its attempt summary persisted."""

    run_id: int
    status: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    article_id: Optional[str] = None
    article_url: Optional[str] = None
    final_slug: Optional[str] = None
    output_filename: Optional[str] = None
    pr_url: Optional[str] = None
    failure_class: Optional[str] = None
    error: Optional[str] = None
    readability: Optional[AdminQualityReadability] = None
    stages: List[AdminQualityStageItem] = Field(default_factory=list)


class AdminQualityAggregate(BaseModel):
    """Page-level rollup over the returned runs."""

    count: int = 0
    succeeded: int = 0
    failed: int = 0
    with_readability: int = 0
    avg_suitability: Optional[float] = None


class AdminQualityRecentEnvelope(BaseModel):
    """Recent publication runs for the quality review page."""

    runs: List[AdminQualityRunItem] = Field(default_factory=list)
    aggregate: AdminQualityAggregate = Field(default_factory=AdminQualityAggregate)
    meta: Dict[str, Any] = Field(default_factory=dict)


class AdminSourceListItem(BaseModel):
    """One row of the source manager (config metadata + circuit state)."""

    source_id: str
    name: Optional[str] = None
    url: Optional[str] = None
    category: Optional[str] = None
    content_mode: Optional[str] = None
    enrichment_strategy: Optional[str] = None
    is_active: bool = True
    circuit: Optional[Dict[str, Any]] = None


class AdminSourceListEnvelope(BaseModel):
    sources: List[AdminSourceListItem] = Field(default_factory=list)


class AdminSourceToggleRequest(BaseModel):
    """Body for activating/deactivating a source."""

    active: bool


class AdminPromptsEnvelope(BaseModel):
    """Prompt lab: top-level agent keys with their prompt bodies."""

    prompts: Dict[str, Any] = Field(default_factory=dict)


class AdminContentEnvelope(BaseModel):
    """Published content snapshot (Live CMS read view)."""

    source_label: str = ""
    freshness_label: str = ""
    articles: List[Dict[str, Any]] = Field(default_factory=list)


class AdminImageBriefItem(BaseModel):
    """One row of the image queue."""

    slug: str
    article_id: str
    status: str
    reason: str
    topic: str
    news_angle: Optional[str] = None
    scientific_domain: Optional[str] = None
    subject_scene: Optional[str] = None
    draft_alt_text: Optional[str] = None
    tone: Optional[str] = None
    updated_at: Optional[str] = None


class AdminImageQueueEnvelope(BaseModel):
    briefs: List[AdminImageBriefItem] = Field(default_factory=list)


class AdminBulkResetRequest(BaseModel):
    """Body for bulk-unpublishing published articles."""

    refinery_ids: List[str] = Field(min_length=1, max_length=50)

    @field_validator("refinery_ids")
    @classmethod
    def _ids_non_empty(cls, v: List[str]) -> List[str]:
        cleaned = [item.strip() for item in v if item and item.strip()]
        if not cleaned:
            raise ValueError("refinery_ids must contain at least one id")
        return cleaned


class AdminBulkResetFailure(BaseModel):
    refinery_id: str
    error: str


class AdminBulkResetResult(BaseModel):
    succeeded: List[str] = Field(default_factory=list)
    failed: List[AdminBulkResetFailure] = Field(default_factory=list)
    summary: str


class AdminImageBriefUpdate(BaseModel):
    """Editable fields of an image brief (all optional)."""

    topic: Optional[str] = None
    news_angle: Optional[str] = None
    scientific_domain: Optional[str] = None
    subject_scene: Optional[str] = None
    draft_alt_text: Optional[str] = None
    tone: Optional[str] = None


class AdminImageBriefUploadResult(BaseModel):
    brief: Dict[str, Any]
    asset_path: str


_SOURCE_CATEGORIES = Literal[
    "technology",
    "science",
    "medicine",
    "space",
    "biology",
    "multidisciplinary",
    "popular_science",
    "artificial_intelligence",
]

_SOURCE_FREQUENCIES = Literal["daily", "weekly", "hourly", "multiple_daily"]

_SOURCE_GROUPS = Literal[
    "ELITE_JOURNALS",
    "SCIENCE_MEDIA",
    "INSTITUTIONAL_SOURCES",
    "AI_LABS",
    "CUSTOM",
]


class AdminSourceUpsert(BaseModel):
    """Add or update a source (mirrors the old GUI's source editor form).

    On update, only provided fields are applied; existing keys (blacklist,
    etag, last_modified, content_mode, ...) are preserved.
    """

    source_id: str = Field(min_length=2, pattern=r"^[a-z0-9_]+$")
    name: str = Field(min_length=2)
    url: str = Field(min_length=5)
    credibility_score: float = Field(default=0.8, ge=0.0, le=1.0)
    category: _SOURCE_CATEGORIES = "science"
    update_frequency: _SOURCE_FREQUENCIES = "daily"
    group: _SOURCE_GROUPS = "CUSTOM"
