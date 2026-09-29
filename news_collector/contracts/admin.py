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
    # Runtime near-duplicate grouping (plan 111): set when this row belongs
    # to a same-page similarity group. Per-page only (no cross-page
    # grouping); absent (None) when ungrouped. Master = first-ranked member.
    similar_group_id: Optional[str] = None
    similar_group_size: Optional[int] = None


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


DashboardHealthStatus = Literal["pass", "warning", "fail", "unknown"]


class AdminDashboardEvidence(BaseModel):
    """One dashboard health area, derived from durable records only.

    ``evidence="none"`` means no record exists to judge from — the consumer
    must render ``unknown``, never infer ``pass`` (plan 060 Phase 5c).
    ``counts`` always carries the area's full known key set (zeros when a
    key has no rows), so the unknown signal lives only in ``evidence``.
    """

    status: DashboardHealthStatus
    evidence: Literal["present", "none"]
    detail: str = ""
    measured_at: Optional[datetime] = None
    oldest_pending_age_seconds: Optional[int] = None
    counts: Dict[str, int] = Field(default_factory=dict)


class AdminDashboardHealthEnvelope(BaseModel):
    """Backend evidence for the admin dashboard health list (plan 060
    Phase 5c). The frontend combines this with its own records (schema,
    hero image, lint) in 5d; areas with no backend evidence stay unknown."""

    generated_at: datetime
    publication: AdminDashboardEvidence
    callbacks: AdminDashboardEvidence
    validation: AdminDashboardEvidence


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
    """Body for POST /v1/admin/publish — exactly one of article_id / article_url.

    NOTE (plan 074): there is intentionally NO dry_run flag here. A previous
    version accepted and threaded one, but nothing on the publish path ever
    consulted it — a "dry-run publish" executed a full real publish. The
    flag was removed rather than left as a dishonest promise. (Collect
    dry-run is real and lives on AdminCollectRequest.)
    """

    article_id: Optional[int] = None
    article_url: Optional[str] = None


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


#: Batch publish cap (plan 109). One batch occupies the single-flight
#: publication slot and refines articles sequentially, so the cap bounds
#: worst-case run time, not parallelism. Enforced here (HTTP 422) and
#: re-asserted defensively by the pipeline wrapper.
BATCH_MAX_IDS = 5


class AdminPublishBatchRequest(BaseModel):
    """Body for POST /v1/admin/publish/batch — 1..5 article ids.

    Ids only (no URLs): URL ingestion is per-article interactive work and
    stays on the single-article route. Every id gets an explicit per-item
    outcome in the run summary (LAW-B6); a duplicate or out-of-range id
    rejects the whole request with 422 rather than silently dropping it.
    """

    article_ids: List[int] = Field(min_length=1, max_length=BATCH_MAX_IDS)

    @field_validator("article_ids")
    @classmethod
    def _ids_must_be_positive_unique(cls, ids: List[int]) -> List[int]:
        if any(i <= 0 for i in ids):
            raise ValueError("article_ids must be positive article ids")
        if len(set(ids)) != len(ids):
            raise ValueError("article_ids must not contain duplicates")
        return ids


class AdminPublishBatchItem(BaseModel):
    """Explicit per-item outcome inside a batch run summary."""

    article_id: int
    status: Literal["succeeded", "failed"]
    pr_url: Optional[str] = None
    failure_class: Optional[str] = None
    final_slug: Optional[str] = None
    message: Optional[str] = None


class AdminPublishBatchStarted(BaseModel):
    """Response to POST /v1/admin/publish/batch."""

    run_id: str
    status: AdminRunStatus = "queued"
    detail: str
    accepted_ids: List[int] = Field(default_factory=list)


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
    # Latest auditor verdict from the article's metadata (`audit.state`),
    # batch-fetched for numeric article ids. None when never audited.
    audit_state: Optional[str] = None
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
    not_processed: List[str] = Field(default_factory=list)
    cap_note: Optional[str] = None


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
