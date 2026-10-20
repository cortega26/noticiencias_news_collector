"""Pure reader-report interpretation and reconciliation (plan 186).

The Worker (frontend repo, ``workers/src/handlers/report.ts``) stores every
accepted report as a pretty-printed JSON object under
``reports/YYYY-MM-DD/<uuid>.json``. This module turns one such R2 object
into a typed intake outcome and drives the idempotent reconciliation pass:

    list keys -> fetch bytes -> parse -> resolve identity -> persist -> outcome

Parsing is strict on purpose (LAW-B6 / plan STOP condition): a record whose
shape the backend does not recognize becomes a *counted invalid outcome*
with a stable reason — never a silent drop, never a guess, never an
upward-compat parse hack. The same object reconciled any number of times
still yields exactly one ``reader_reports`` row (deduped on the Worker's
UUID ``id`` as ``idempotency_key``), with duplicates counted, not dropped.

Pure module: no storage or network imports (LAW-B4 / plan 186 constraint).
I/O collaborators are injected — an :class:`ReportIntakeFeed` for R2
access, an identity resolver callable (plan 185's resolver bound to its
database by the script), and a persist callable (the repository's
idempotent upsert, or a read-only dry-run stand-in) — so tests and the
pure logic run without network or database.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Callable, Optional, Protocol

from pydantic import ValidationError

from news_collector.contracts.reader_reports import (
    InvalidReportIntake,
    PersistOutcome,
    R2KeyPage,
    ReaderReportPayload,
    ReconciliationSummary,
    ReportIdentity,
    ReportOutcome,
    ValidReportIntake,
)
from news_collector.utils.logger import get_logger

logger = get_logger().create_module_logger(__name__)

# Stable invalid-intake reasons (persisted/logged verbatim).
REASON_INVALID_JSON = "invalid_json"
REASON_RECORD_NOT_AN_OBJECT = "record_not_an_object"
REASON_MISSING_ID = "missing_report_id"
REASON_INVALID_REPORT_ID = "invalid_report_id"
REASON_INVALID_META_PREFIX = "invalid_meta:"
REASON_MISSING_SUBMITTED_AT = "missing_submitted_at"
REASON_INVALID_SUBMITTED_AT = "invalid_submitted_at"
REASON_UNKNOWN_FIELD_PREFIX = "unknown_field:"
REASON_INVALID_PAYLOAD_PREFIX = "invalid_payload:"
REASON_BEFORE_SINCE = "before_since"

# Per-object failure reasons (typed; the signal is the exception type so
# nothing user-supplied can leak into logs).
REASON_FETCH_MISSING = "r2_object_missing"
REASON_FETCH_TRANSPORT = "r2_transport_error"
REASON_PERSIST_FAILED = "persist_error"

# Worker record fields *outside* the validated payload contract
# (workers/src/handlers/report.ts). Anything else outside the payload
# contract is record-shape drift, not a parse hack.
WORKER_META_KEYS = ("id", "submitted_at", "environment", "user_agent")

# Cloudflare REST list endpoint per-page maximum (developers.cloudflare.com).
MAX_LIST_PER_PAGE = 1000

REASON_CAP = 200

# Shared lookup sets for the strict-shape walk (computed once per process).
_META_KEYS = frozenset(WORKER_META_KEYS)
_PAYLOAD_FIELDS = frozenset(ReaderReportPayload.model_fields)


class ReportIntakeFeed(Protocol):
    """Structural type for the R2 object feed edge (no network import).

    ``news_collector.infrastructure.r2_client.R2ReportClient`` satisfies
    this structurally; tests inject statically typed fakes.
    """

    def list_report_keys(
        self, *, prefix: str, limit: int, cursor: Optional[str] = None
    ) -> R2KeyPage:
        """One listing page: keys plus the next opaque cursor (or None)."""
        ...

    def get_object(self, key: str) -> bytes:
        """Object body bytes; 404 must surface as a missing-object error."""
        ...


#: ``resolve_identity(url) -> ReportIdentity`` — the script binds plan 185's
#: ``resolve_report_identity(url, db)`` to a concrete database manager.
IdentityResolver = Callable[[str], ReportIdentity]

#: ``persist(intake, identity) -> PersistOutcome`` — the script binds the
#: repository's idempotent upsert (or the dry-run read-only classifier).
ReportPersister = Callable[[ValidReportIntake, ReportIdentity], PersistOutcome]


def _canonical_report_id(value: object) -> Optional[str]:
    """Canonical UUID string from a Worker record ``id``, else ``None``.

    The Worker writes ``crypto.randomUUID()`` (UUIDv4, hyphenated). Any
    parseable UUID string is accepted and canonicalized so formatting
    differences cannot fork the idempotency key; non-UUID junk is a typed
    invalid outcome.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return str(uuid.UUID(value.strip()))
    except ValueError:
        return None


def _parse_submitted_at(value: object) -> Optional[datetime]:
    """UTC-normalized ``datetime`` from the record's ISO ``submitted_at``.

    The Worker writes ``new Date().toISOString()`` (UTC, ``Z`` suffix,
    which ``datetime.fromisoformat`` accepts). Missing/unparseable values
    are typed failures — the field is the record's timestamp of truth and
    is never guessed.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None:
        # ISO timestamps without a timezone are interpreted once, as UTC,
        # so the stored value is always aware.
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _locator_reason(prefix: str, locator: str, cap: int = REASON_CAP) -> str:
    """A stable bounded reason string (<cap chars), never empty/colonly."""
    text = f"{prefix}{locator or '?'}"
    if len(text) > cap:
        text = text[:cap]
    if text.endswith(":"):
        text = f"{text}?"
    return text


def _json_record(key: str, body: bytes) -> "dict[str, object] | InvalidReportIntake":
    """Decode + JSON-parse one object body; invalid bodies are outcomes."""
    try:
        text = body.decode("utf-8")
        raw = json.loads(text)
    except UnicodeDecodeError:
        return InvalidReportIntake(
            key=key, reason=REASON_INVALID_JSON, detail="unicode"
        )
    except (json.JSONDecodeError, ValueError):
        return InvalidReportIntake(key=key, reason=REASON_INVALID_JSON)
    if not isinstance(raw, dict):
        return InvalidReportIntake(key=key, reason=REASON_RECORD_NOT_AN_OBJECT)
    return dict(raw)


def _validated_record(
    key: str, record: "dict[str, object]"
) -> "tuple[str, datetime] | InvalidReportIntake":
    """Validated ``(record_id, submitted_at)`` from the record, or invalid.

    ``record_id`` is the canonical Worker UUID (idempotency key) and
    ``submitted_at`` the UTC-normalized timestamp; anything the backend
    does not recognize (missing/malformed id, missing/malformed
    ``submitted_at``, unknown keys — record-shape drift) is a typed invalid
    outcome instead of a guess.
    """
    record_id = _canonical_report_id(record.get("id"))
    if record_id is None:
        id_present = "id" in record
        return InvalidReportIntake(
            key=key,
            reason=REASON_MISSING_ID if not id_present else REASON_INVALID_REPORT_ID,
            detail=str(record.get("id"))[:80] if id_present else "",
        )

    submitted_at = _parse_submitted_at(record.get("submitted_at"))
    if submitted_at is None:
        return InvalidReportIntake(
            key=key,
            reason=(
                REASON_MISSING_SUBMITTED_AT
                if "submitted_at" not in record
                else REASON_INVALID_SUBMITTED_AT
            ),
        )

    unknown = sorted(
        k for k in record if k not in _META_KEYS and k not in _PAYLOAD_FIELDS
    )
    if unknown:
        return InvalidReportIntake(
            key=key, reason=_locator_reason(REASON_UNKNOWN_FIELD_PREFIX, unknown[0])
        )
    return record_id, submitted_at


def parse_report_object(
    key: str, body: bytes
) -> ValidReportIntake | InvalidReportIntake:
    """Interpret one R2 object body into a typed intake outcome.

    Always returns an outcome; per-record failures are values, never raised
    (LAW-B6). Strictness mirrors the Worker's own validation: unknown keys
    (record-shape change), malformed ``id``/``submitted_at`` and payload
    contract violations (unknown ``problem_type``, too-long fields, bad
    URLs/emails) are typed invalid outcomes with stable reasons.
    """
    json_outcome = _json_record(key, body)
    if isinstance(json_outcome, InvalidReportIntake):
        return json_outcome
    record = json_outcome

    validated = _validated_record(key, record)
    if isinstance(validated, InvalidReportIntake):
        return validated
    record_id, submitted_at = validated

    environment = record.get("environment")
    user_agent = record.get("user_agent")
    for name, value in (("environment", environment), ("user_agent", user_agent)):
        if value is not None and not isinstance(value, str):
            return InvalidReportIntake(
                key=key, reason=_locator_reason(REASON_INVALID_META_PREFIX, name)
            )

    payload_body = {k: v for k, v in record.items() if k not in _META_KEYS}
    try:
        payload = ReaderReportPayload.model_validate(payload_body)
    except ValidationError as exc:
        errors_ = exc.errors()
        first_loc = ""
        if errors_:
            first_loc = ".".join(str(part) for part in errors_[0].get("loc", ()))
        return InvalidReportIntake(
            key=key,
            reason=_locator_reason(
                REASON_INVALID_PAYLOAD_PREFIX, first_loc or "record"
            ),
        )

    return ValidReportIntake(
        key=key,
        idempotency_key=record_id,
        payload=payload,
        submitted_at=submitted_at,
        environment=environment if isinstance(environment, str) else None,
        user_agent=user_agent if isinstance(user_agent, str) else None,
    )


def _before_since(intake: ValidReportIntake, since: Optional[datetime]) -> bool:
    """``--since`` guard: reports submitted before it are skipped, counted."""
    if since is None:
        return False
    since_utc = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
    return intake.submitted_at < since_utc.astimezone(timezone.utc)


def _identity_for_payload(
    payload: ReaderReportPayload, resolve_identity: IdentityResolver
) -> ReportIdentity:
    """Resolve identity from the reported URL; no/empty URL -> typed unresolved.

    Passing the empty string through plan 185's resolver yields the stable
    ``invalid_article_url`` unresolved outcome, so "no URL" and "bad URL"
    take the same code path. Resolver exceptions are converted into an
    ``identity_error:<type>`` unresolved identity — never a crash, never a
    guess.
    """
    url = payload.article_url or ""
    try:
        return resolve_identity(url)
    except Exception as exc:  # noqa: BLE001 - converted to a typed outcome
        logger.warning("Identity resolution failed (error_type={})", type(exc).__name__)
        return ReportIdentity(
            status="unresolved", reason=f"identity_error:{type(exc).__name__}"
        )


def _is_r2_object_missing(exc: BaseException) -> bool:
    """Duck-typed check for the infrastructure ``R2ObjectMissing`` type.

    The client's missing-object error carries the class attribute
    ``r2_object_missing = True``; checking the flag keeps this pure module
    free of an infrastructure import (LAW-B4).
    """
    return getattr(exc, "r2_object_missing", False) is True


def _run_object(
    key: str,
    *,
    feed: ReportIntakeFeed,
    resolve_identity: IdentityResolver,
    persist_report: ReportPersister,
    since: Optional[datetime],
) -> ReportOutcome:
    """Fetch, interpret, resolve and persist one object — failures are
    outcomes, the run continues (LAW-B6)."""
    try:
        body = feed.get_object(key)
    except Exception as exc:  # noqa: BLE001 - per-object failure, run continues
        if _is_r2_object_missing(exc):
            return ReportOutcome(
                key=key, status="fetch_failed", reason=REASON_FETCH_MISSING
            )
        logger.warning("Object fetch failed (error_type={})", type(exc).__name__)
        return ReportOutcome(
            key=key, status="fetch_failed", reason=REASON_FETCH_TRANSPORT
        )

    intake = parse_report_object(key, body)
    if isinstance(intake, InvalidReportIntake):
        return ReportOutcome(
            key=key, status="invalid", reason=intake.reason, idempotency_key=None
        )

    if _before_since(intake, since):
        return ReportOutcome(
            key=key,
            status="skipped",
            idempotency_key=intake.idempotency_key,
            reason=REASON_BEFORE_SINCE,
        )

    identity = _identity_for_payload(intake.payload, resolve_identity)
    try:
        persist = persist_report(intake, identity)
    except Exception as exc:  # noqa: BLE001 - per-object failure, run continues
        logger.warning("Persist failed (error_type={})", type(exc).__name__)
        return ReportOutcome(
            key=key,
            status="persist_failed",
            idempotency_key=intake.idempotency_key,
            reason=REASON_PERSIST_FAILED,
        )

    return ReportOutcome(
        key=key,
        status=persist.status,  # created | duplicate | db_failed
        idempotency_key=intake.idempotency_key,
        reason=persist.reason,
    )


def _bump(summary: ReconciliationSummary, outcome: ReportOutcome) -> None:
    """One typed outcome -> one summary counter (total ≡ processed)."""
    if outcome.status == "created":
        summary.created += 1
    elif outcome.status == "duplicate":
        summary.duplicates += 1
    elif outcome.status == "invalid":
        summary.invalid += 1
    elif outcome.status == "skipped":
        summary.skipped += 1
    elif outcome.status == "persist_failed":
        summary.persist_failed += 1
    else:  # "fetch_failed" and any future status default to fetch accounting
        summary.fetch_failed += 1


def reconcile_report_objects(
    *,
    feed: ReportIntakeFeed,
    resolve_identity: IdentityResolver,
    persist_report: ReportPersister,
    prefix: str = "reports/",
    limit: int = 100,
    since: Optional[datetime] = None,
) -> ReconciliationSummary:
    """Idempotently reconcile up to ``limit`` R2 report objects.

    Pages the listing and, per key, fetches bytes, interprets, resolves
    identity (185) and persists — every object producing a typed
    ``ReportOutcome``. Per-object failures never abort the run; the pass
    only stops early on a listing failure (recorded in ``summary.fatal``).
    ``truncated`` marks a pass that reached ``limit`` while more keys
    remained (non-empty next cursor).
    """
    if limit < 1:
        raise ValueError("limit must be at least 1")

    summary = ReconciliationSummary()
    outcomes: list[ReportOutcome] = []
    cursor: Optional[str] = None

    while summary.processed < limit:
        page_size = min(limit - summary.processed, MAX_LIST_PER_PAGE)
        try:
            page = feed.list_report_keys(prefix=prefix, limit=page_size, cursor=cursor)
        except Exception as exc:  # noqa: BLE001 - run-level, converts to fatal
            summary.fatal = f"list_failed:{type(exc).__name__}"
            logger.error("Report listing failed (error_type={})", type(exc).__name__)
            break

        page_keys = list(page.keys)
        summary.listed += len(page_keys)

        truncated_by_limit = False
        for key in page_keys:
            if summary.processed >= limit:
                # Limit hit while this still-held page had unprocessed keys.
                truncated_by_limit = True
                break
            outcome = _run_object(
                key,
                feed=feed,
                resolve_identity=resolve_identity,
                persist_report=persist_report,
                since=since,
            )
            outcomes.append(outcome)
            _bump(summary, outcome)
            summary.fetched += 1  # every processed object was fetched once

        if summary.processed >= limit and (
            truncated_by_limit or page.next_cursor is not None
        ):
            summary.truncated = True
        if summary.processed >= limit:
            break
        if page.next_cursor is None:
            break
        cursor = page.next_cursor

    summary.outcomes = tuple(outcomes)
    return summary
