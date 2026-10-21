"""Typed contracts for reader-submitted reports (plans 185/186).

These shapes mirror the frontend Worker's report contract
(``workers/src/utils/validate.ts`` in the frontend repo) at the backend
boundary: the same six problem types, the same per-field length caps, the
same ``noticiencias.com`` / ``*.noticiencias.com`` host rule, and an optional
reporter email. Pure Pydantic/dataclasses — no I/O, no storage imports
(LAW-B1). Plan 186 adds the reconciliation outcome shapes shared by the R2
reader, the pure logic, the repository, and the operator script.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Union
from urllib.parse import SplitResult, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Mirrors VALID_PROBLEM_TYPES in the Worker — keep both lists in sync.
ReaderProblemType = Literal[
    "content_factual",
    "content_source",
    "content_interpretation",
    "content_translation",
    "technical_site",
    "technical_visual",
]

READER_PROBLEM_TYPE_VALUES: tuple[ReaderProblemType, ...] = (
    "content_factual",
    "content_source",
    "content_interpretation",
    "content_translation",
    "technical_site",
    "technical_visual",
)

# Mirrors MAX_LENGTHS in the Worker — keep both lists in sync.
MAX_ARTICLE_URL_LENGTH = 2000
MAX_DESCRIPTION_LENGTH = 5000
MAX_CONTENT_SNIPPET_LENGTH = 2000
MAX_EVIDENCE_URL_LENGTH = 2000
MAX_TECH_FIELD_LENGTH = 200
MAX_EMAIL_LENGTH = 320  # RFC 5321 max mailbox length

ReaderReportStatus = Literal[
    "new",
    "triaged",
    "accepted",
    "rejected",
    "duplicate",
    "no_action",
]

READER_REPORT_STATUS_VALUES: tuple[ReaderReportStatus, ...] = (
    "new",
    "triaged",
    "accepted",
    "rejected",
    "duplicate",
    "no_action",
)

ReaderResolutionStatus = Literal["unresolved", "resolved", "ambiguous"]

READER_RESOLUTION_STATUS_VALUES: tuple[ReaderResolutionStatus, ...] = (
    "unresolved",
    "resolved",
    "ambiguous",
)

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def is_noticiencias_host(hostname: str) -> bool:
    """Dot-boundary host check shared by the contract and the resolver.

    Accepts ``noticiencias.com`` and ``*.noticiencias.com`` only — never
    lookalikes such as ``evilnoticiencias.com``. Mirrors
    ``isNoticienciasHost`` in the Worker.
    """
    hostname = hostname.lower()
    return hostname == "noticiencias.com" or hostname.endswith(".noticiencias.com")


def _parse_web_url(value: str, *, field_label: str) -> SplitResult:
    """Parse an absolute http(s) URL without performing any I/O.

    Rejects whitespace and backslashes because browser URL parsers normalize
    them differently from :func:`urllib.parse.urlsplit`; accepting them here
    could validate a URL whose real host differs from the checked host.
    """
    text = value.strip()
    if not text or any(char.isspace() for char in text) or "\\" in text:
        raise ValueError(f"{field_label} no es una URL válida")
    try:
        parsed = urlsplit(text)
        # Force access so an invalid port (e.g. ":abc") raises here.
        _ = parsed.port
    except ValueError as exc:
        raise ValueError(f"{field_label} no es una URL válida") from exc
    if not parsed.scheme or not parsed.hostname:
        raise ValueError(f"{field_label} no es una URL válida")
    if parsed.scheme.lower() not in ("http", "https"):
        raise ValueError(f"{field_label} no es una URL válida")
    return parsed


class ReaderReportPayload(BaseModel):
    """Validated reader report body, matching the Worker payload.

    Every field except ``problem_type`` is optional. Empty optional strings
    are normalized to ``None`` (the Worker treats ``""`` as absent too).
    Unknown keys are rejected, like the Worker's ``ALLOWED_KEYS`` check.
    """

    problem_type: ReaderProblemType
    article_url: Optional[str] = Field(default=None, max_length=MAX_ARTICLE_URL_LENGTH)
    description: Optional[str] = Field(default=None, max_length=MAX_DESCRIPTION_LENGTH)
    content_snippet: Optional[str] = Field(
        default=None, max_length=MAX_CONTENT_SNIPPET_LENGTH
    )
    evidence_url: Optional[str] = Field(
        default=None, max_length=MAX_EVIDENCE_URL_LENGTH
    )
    tech_browser: Optional[str] = Field(default=None, max_length=MAX_TECH_FIELD_LENGTH)
    tech_os: Optional[str] = Field(default=None, max_length=MAX_TECH_FIELD_LENGTH)
    reporter_email: Optional[str] = Field(default=None, max_length=MAX_EMAIL_LENGTH)

    model_config = ConfigDict(extra="forbid")

    @field_validator(
        "article_url",
        "description",
        "content_snippet",
        "evidence_url",
        "tech_browser",
        "tech_os",
        "reporter_email",
        mode="before",
    )
    @classmethod
    def _blank_becomes_absent(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("article_url")
    @classmethod
    def _validate_article_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        parsed = _parse_web_url(value, field_label="URL del artículo")
        if not is_noticiencias_host(parsed.hostname or ""):
            raise ValueError("URL del artículo debe ser de noticiencias.com")
        return value

    @field_validator("evidence_url")
    @classmethod
    def _validate_evidence_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        _parse_web_url(value, field_label="URL de evidencia")
        return value

    @field_validator("reporter_email")
    @classmethod
    def _validate_email(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if not _EMAIL_RE.fullmatch(value):
            raise ValueError("Correo electrónico no es válido")
        return value


class ReportIdentity(BaseModel):
    """Typed outcome of resolving a report URL to a published revision.

    ``resolved`` always carries ``canonical_url`` and ``refinery_id``;
    ``unresolved``/``ambiguous`` never invent one — they carry a stable
    ``reason`` instead. The resolver never guesses an article.
    """

    status: ReaderResolutionStatus
    canonical_url: Optional[str] = None
    refinery_id: Optional[str] = None
    content_sha256: Optional[str] = None
    reason: str = Field(min_length=1, max_length=200)

    model_config = ConfigDict(extra="forbid")


# =============================================================================
# Reconciliation shapes (plan 186)
#
# Internal, cross-module outcomes shared by the R2 reader (infrastructure),
# the pure reconciliation logic (logic/workflows), the repository (storage),
# and the operator script. Frozen dataclasses with a stable scope — not wire
# payloads — so they stay outside the sync-and-mirror contract family.
# =============================================================================

PersistStatus = Literal["created", "duplicate", "db_failed"]


@dataclass(frozen=True)
class R2KeyPage:
    """One page of R2 object keys from the Cloudflare REST listing.

    ``next_cursor`` is the opaque cursor for the next page, or ``None``
    when the listing is exhausted.
    """

    keys: tuple[str, ...]
    next_cursor: Optional[str] = None


@dataclass(frozen=True)
class ValidReportIntake:
    """A Worker R2 record that parsed cleanly against the 185 contract.

    ``idempotency_key`` is the canonical form of the Worker record ``id``
    (UUID rendered lowercase-hyphenated); ``payload`` is the validated
    body; ``submitted_at`` is UTC-normalized. ``environment`` and
    ``user_agent`` are carried for diagnostics — the ``reader_reports``
    row has no columns for them, so persistence ignores them by design.
    """

    key: str
    idempotency_key: str
    payload: ReaderReportPayload
    submitted_at: datetime
    environment: Optional[str] = None
    user_agent: Optional[str] = None


@dataclass(frozen=True)
class InvalidReportIntake:
    """A Worker R2 record that did not parse — counted, never silently dropped.

    ``reason`` is a stable machine string (e.g. ``invalid_json``,
    ``unknown_field:<name>``, ``invalid_submitted_at``); ``detail`` is a
    short human suffix. A record shape the backend does not recognize is
    an *invalid outcome*, not a parse hack.
    """

    key: str
    reason: str
    detail: str = ""


@dataclass(frozen=True)
class PersistOutcome:
    """Result of persisting one valid intake to ``reader_reports``."""

    status: PersistStatus
    reason: Optional[str] = None


OutcomeStatus = Literal[
    "created",
    "duplicate",
    "invalid",
    "skipped",
    "fetch_failed",
    "persist_failed",
]


@dataclass(frozen=True)
class ReportOutcome:
    """Per-object reconciliation result (LAW-B6: every item is an outcome)."""

    key: str
    status: OutcomeStatus
    idempotency_key: Optional[str] = None
    reason: Optional[str] = None


@dataclass
class ReconciliationSummary:
    """Typed run summary (mutable accumulator, like ``PullSummary``).

    ``listed`` = keys seen on pages; ``fetched`` = objects pulled; the
    outcome counters partition ``fetched`` (+ ``skipped``). ``fatal`` is
    set (with a reason) when the listing itself failed — per-object
    failures never set it, the run continues.
    """

    listed: int = 0
    fetched: int = 0
    created: int = 0
    duplicates: int = 0
    invalid: int = 0
    skipped: int = 0
    fetch_failed: int = 0
    persist_failed: int = 0
    truncated: bool = False
    fatal: Optional[str] = None
    outcomes: tuple[ReportOutcome, ...] = ()

    @property
    def processed(self) -> int:
        return sum(
            (
                self.created,
                self.duplicates,
                self.invalid,
                self.skipped,
                self.fetch_failed,
                self.persist_failed,
            )
        )


# =============================================================================
# Admin triage/decision surface (plan 187)
#
# Typed request/response shapes for the /v1/admin/reader-reports endpoints.
# The same privacy law as plans 185/186 applies unchanged: the reporter
# email is NEVER part of a list item; the detail DTO carries it only when
# a contact row exists AND ``contact_purged_at IS NULL`` (see
# ``AdminReaderReportDetail.reporter_email``). Pure Pydantic models — no
# I/O, no storage imports (LAW-B1/LAW-B4).
# =============================================================================

# Admin action families: ``triage`` is a notes-only queue maneuver
# (new → triaged); ``decision`` records one final editorial decision kind.
ReportActionKind = Literal["triage", "decision"]

REPORT_ACTION_KIND_VALUES: tuple[ReportActionKind, ...] = ("triage", "decision")

# Decision kinds — must stay in lockstep with READER_DECISION_VALUES in
# storage/models.py (the ``ck_reader_report_decisions_decision`` CHECK).
ReportDecisionKind = Literal["accepted", "rejected", "duplicate", "no_action"]

REPORT_DECISION_KIND_VALUES: tuple[ReportDecisionKind, ...] = (
    "accepted",
    "rejected",
    "duplicate",
    "no_action",
)

# Free-text bounds for admin payloads (same 5000-char discipline as the
# Worker's description cap; audit notes share it).
MAX_DECISION_ACTOR_LENGTH = 200  # reader_report_decisions.actor column cap
MAX_DECISION_NOTES_LENGTH = 5000
MAX_DECISION_CORRECTION_LENGTH = 5000


class ReportDecisionRequest(BaseModel):
    """One admin action against one reader report (plan 187).

    ``kind`` picks the action family:

    - ``triage`` — notes-only queue maneuver; moves ``new → triaged`` and
      is refused in every other current state. Triage appends NO decision
      row: ``reader_report_decisions.decision`` is CHECK-constrained to
      the four final kinds (plan 185 schema; extending it requires a table
      rebuild, out of plan 187's one-column scope). The triage's own
      audit is the report's ``status``/``updated_at``.
    - ``decision`` — requires ``decision`` and the per-kind evidence
      below; appends an audit row and sets the report status to the
      decision kind.

    Cross-field legality is owned by the pure rules module
    (``logic/workflows/report_decisions.plan_decision``), not here: this
    model validates only field shapes. ``notes`` is REQUIRED for every
    action (audit discipline — no anonymous write). ``corrected_at`` /
    ``correction_summary`` belong to ``accepted``; publication/deploy
    evidence remains plan 188's concern and is intentionally absent.
    """

    kind: ReportActionKind = "decision"
    actor: str = Field(min_length=1, max_length=MAX_DECISION_ACTOR_LENGTH)
    notes: str = Field(min_length=1, max_length=MAX_DECISION_NOTES_LENGTH)
    decision: Optional[ReportDecisionKind] = None
    corrected_at: Optional[datetime] = None
    correction_summary: Optional[str] = Field(
        default=None, max_length=MAX_DECISION_CORRECTION_LENGTH
    )
    duplicate_of_report_id: Optional[int] = Field(default=None, ge=1)

    model_config = ConfigDict(extra="forbid")

    @field_validator("actor", mode="before")
    @classmethod
    def _actor_not_blank(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            raise ValueError("El actor es obligatorio")
        return value

    @field_validator("notes", mode="before")
    @classmethod
    def _notes_not_blank(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            raise ValueError("Las notas son obligatorias")
        return value

    @field_validator("actor", "notes", "correction_summary", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ReaderReportDecisionItem(BaseModel):
    """One persisted decision row, as the admin surface shows it.

    ``publication_ref``/``deploy_evidence`` exist on the table for plan
    188's closure flow; the 187 surface never writes them, so they are
    always ``None`` here.
    """

    id: int
    decision: ReportDecisionKind
    actor: str
    notes: Optional[str] = None
    corrected_at: Optional[datetime] = None
    correction_summary: Optional[str] = None
    publication_ref: Optional[str] = None
    deploy_evidence: Optional[str] = None
    duplicate_of_report_id: Optional[int] = None
    created_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None


FiltersChoice = Literal["all"]


class AdminReaderReportFilters(BaseModel):
    """Echo of the applied list filters (typed, no bare dicts)."""

    status: Union[ReaderReportStatus, FiltersChoice] = "all"
    resolution: Union[ReaderResolutionStatus, FiltersChoice] = "all"
    problem_type: Union[ReaderProblemType, FiltersChoice] = "all"


class AdminReaderReportItem(BaseModel):
    """One report row for admin lists — contact data NEVER included.

    Privacy law (plan 185): contact lives solely in
    ``reader_report_contacts``; the list item has no reporter email field
    at all, so no filter/pagination bug can leak it. Decision history is
    referenced in a bounded way (count + latest row); the full history
    belongs to the detail endpoint.
    """

    id: int
    status: ReaderReportStatus
    resolution_status: ReaderResolutionStatus
    resolved_refinery_id: Optional[str] = None
    resolved_content_sha256: Optional[str] = None
    resolution_reason: Optional[str] = None

    problem_type: ReaderProblemType
    article_url: Optional[str] = None
    description: Optional[str] = None
    content_snippet: Optional[str] = None
    evidence_url: Optional[str] = None
    tech_browser: Optional[str] = None
    tech_os: Optional[str] = None

    submitted_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    contact_purged_at: Optional[datetime] = None

    decision_count: int = 0
    latest_decision: Optional[ReaderReportDecisionItem] = None


class AdminReaderReportDetail(AdminReaderReportItem):
    """Full report + append-only decision history.

    Privacy contract (plan 185 law, mirrored across
    ``storage/models.py`` and ``storage/reader_report_repository.py``):
    ``reporter_email`` is populated ONLY when a ``reader_report_contacts``
    row exists for this report AND ``contact_purged_at IS NULL``. After a
    purge the email never leaves the backend through this endpoint — the
    report body and decisions stay. The list endpoint carries no email
    field under any circumstance.
    """

    reporter_email: Optional[str] = None
    decisions: List[ReaderReportDecisionItem] = Field(default_factory=list)


class AdminReaderReportPagination(BaseModel):
    """Stable descending cursor pagination (created_at, id), article style."""

    next_cursor: Optional[str] = None
    has_more: bool = False
    page_size: int
    returned: int


class AdminReaderReportEnvelope(BaseModel):
    """Typed list envelope for ``GET /v1/admin/reader-reports``."""

    data: List[AdminReaderReportItem]
    pagination: AdminReaderReportPagination
    filters: AdminReaderReportFilters
    meta: Dict[str, Any]


class AdminReaderReportDecisionResult(BaseModel):
    """Response of ``POST /v1/admin/reader-reports/{id}/decisions``.

    ``report`` is the post-decision state (status, decision history, and
    the conditional reporter email); ``action`` echoes the request kind;
    ``replayed`` marks an exact-duplicate payload matched against an
    existing decision row (no row inserted) — its id is
    ``replayed_decision_id``; ``inserted_decision_id`` is the new audit
    row when one was appended (``None`` for triage actions).
    """

    report: AdminReaderReportDetail
    action: ReportActionKind
    inserted_decision_id: Optional[int] = None
    replayed: bool = False
    replayed_decision_id: Optional[int] = None


# --- pure shared context passed into the decision rules (plan 187) ---------


@dataclass(frozen=True)
class DecisionContext:
    """Server-resolved inputs the pure transition rules may not fetch.

    Built by the repository from SELECTs only: ``current_status`` is the
    report's status at snapshot time (older statuses of this report may
    have changed — the repository's CAS re-check makes the apply step
    race-safe), ``duplicate_of_exists`` is True exactly when the
    requested ``duplicate_of_report_id`` points at another existing
    report row, and ``replayed_decision_id`` is the id of an earlier
    decision row with the exact same payload (or None).
    """

    report_id: int
    current_status: str
    duplicate_of_exists: Optional[bool] = None
    replayed_decision_id: Optional[int] = None


@dataclass(frozen=True)
class PlannedDecision:
    """The transition the rules authorized for one request.

    Carries the request echo so the repository can persist it without a
    second (unvalidated) copy of the payload:

    - ``next_status`` is the report status to CAS to (never ``new`` —
      decisions only move reports to ``triaged`` or a final kind — and
      explicitly refused against a ``closed`` report).
    - ``insert_decision_row`` is False for triage (no audit row per the
      185 CHECK constraint; see :class:`ReportDecisionRequest`) and for
      exact-duplicate replays (audit conservation).
    """

    report_id: int
    action: ReportActionKind
    current_status: str
    next_status: Optional[str]
    insert_decision_row: bool
    decision: Optional[ReportDecisionKind] = None
    actor: str = ""
    notes: str = ""
    corrected_at: Optional[datetime] = None
    correction_summary: Optional[str] = None
    duplicate_of_report_id: Optional[int] = None
    replayed_decision_id: Optional[int] = None
