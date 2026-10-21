"""Module role: Own the admin reader-report HTTP surface (plan 187).

Owns:
- The three reader-report routes — ``GET /v1/admin/reader-reports``,
  ``GET /v1/admin/reader-reports/{report_id}`` and
  ``POST /v1/admin/reader-reports/{report_id}/decisions`` — with their
  bounded page size, cursor codec and ORM→contract DTO mapping.
- The reason→HTTP-status mapping for the pure transition rules.

Does NOT own:
- Authentication: ``build_router`` receives ``verify_admin_token`` from
  ``serving/api.py`` (same factory pattern as ``admin_images.py``).
- Transition legality: every POST delegates to the pure rules in
  ``logic/workflows/report_decisions.plan_decision``.
- Mutation storage: every POST dispatches to
  ``storage/report_decision_repository.apply_report_decision`` (CAS +
  audit row in one transaction owned by ``manager.get_session()``) — no
  editorial write workflow lives here (LAW-B4 §3.6).

Invariants:
- Privacy (plan 185 law): list NEVER carries contact data — there is no
  email field on the list item DTO; the detail endpoint exposes
  ``reporter_email`` only when a contact row exists AND
  ``contact_purged_at IS NULL`` (post-purge the email never leaves the
  backend).
- ``closed`` is unreachable from these endpoints: the rules refuse it,
  the CAS refuses it again, and no route writes a closed status (plan
  188 owns closure).
- Exact-duplicate decision payloads are idempotent: the repository
  matches the existing identical row first and the route answers with
  the current state (``X-Reader-Report-Decision: replayed``), never a
  second audit row.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Callable, Optional, Sequence

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import and_, or_

from news_collector.contracts.reader_reports import (
    READER_PROBLEM_TYPE_VALUES,
    READER_REPORT_STATUS_VALUES,
    READER_RESOLUTION_STATUS_VALUES,
    AdminReaderReportDecisionResult,
    AdminReaderReportDetail,
    AdminReaderReportEnvelope,
    AdminReaderReportFilters,
    AdminReaderReportItem,
    AdminReaderReportPagination,
    ReaderReportDecisionItem,
    ReportDecisionRequest,
)
from news_collector.logic.workflows.report_decisions import (
    VIOLATION_ACCEPTED_MISSING_CORRECTION,
    VIOLATION_CLOSED_LOCKED,
    VIOLATION_DECISION_EXTRA_FIELDS,
    VIOLATION_DUPLICATE_MISSING_REF,
    VIOLATION_DUPLICATE_REF_NOT_APPLICABLE,
    VIOLATION_DUPLICATE_SELF_REFERENCE,
    VIOLATION_DUPLICATE_TARGET_MISSING,
    VIOLATION_EMPTY_ACTOR,
    VIOLATION_EMPTY_NOTES,
    VIOLATION_MISSING_DECISION_KIND,
    VIOLATION_TRIAGE_EXTRA_FIELDS,
    VIOLATION_TRIAGE_ONLY_FROM_NEW,
    VIOLATION_UNKNOWN_CURRENT_STATUS,
    ReportDecisionRuleViolation,
    plan_decision,
)
from news_collector.storage.database import DatabaseManager
from news_collector.storage.models import (
    ReaderReport,
    ReaderReportContact,
    ReaderReportDecision,
)
from news_collector.storage.report_decision_repository import (
    StaleReportStateConflict,
    apply_report_decision,
    build_decision_context,
    list_report_decisions,
    load_reader_report,
)

# Stable refusal reason → HTTP status: request-shape problems are 422,
# state/transition conflicts are 409 (both carry the machine reason in
# the detail string).
_RULE_HTTP_STATUS = {
    VIOLATION_EMPTY_ACTOR: 422,
    VIOLATION_EMPTY_NOTES: 422,
    VIOLATION_CLOSED_LOCKED: 409,
    VIOLATION_UNKNOWN_CURRENT_STATUS: 409,
    VIOLATION_TRIAGE_EXTRA_FIELDS: 422,
    VIOLATION_TRIAGE_ONLY_FROM_NEW: 409,
    VIOLATION_MISSING_DECISION_KIND: 422,
    VIOLATION_DECISION_EXTRA_FIELDS: 422,
    VIOLATION_ACCEPTED_MISSING_CORRECTION: 422,
    VIOLATION_DUPLICATE_MISSING_REF: 422,
    VIOLATION_DUPLICATE_REF_NOT_APPLICABLE: 422,
    VIOLATION_DUPLICATE_SELF_REFERENCE: 409,
    VIOLATION_DUPLICATE_TARGET_MISSING: 409,
}

# X-Reader-Report-Decision values (declared in the OpenAPI responses).
_DECISION_HEADER_APPLIED = "applied"
_DECISION_HEADER_REPLAYED = "replayed"
_DECISION_HEADER_TRIAGED = "triaged"

# Bounded list page — same ceiling as the admin article list.
_MIN_PAGE_SIZE = 1
_MAX_PAGE_SIZE = 50


# ---------------------------------------------------------------------------
# Cursor codec (same discipline as the admin article list: opaque, 400 on
# malformed input, deterministic ordering underneath).
# ---------------------------------------------------------------------------


def _encode_report_cursor(row: ReaderReport) -> str:
    """Encode the next-page cursor from the page's LAST report row.

    Ordering is ``created_at DESC, id DESC``; the cursor carries exactly
    those two fields. Datetimes are encoded as the engine reads them
    back (aware on PostgreSQL, naive on SQLite) so the filter always
    compares like with like.
    """
    created = row.created_at or datetime(1970, 1, 1)
    payload = json.dumps([created.isoformat(), row.id], separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def _decode_report_cursor(raw_cursor: str) -> tuple[datetime, int]:
    """Decode a report cursor; 400 on anything malformed or reshaped."""
    try:
        payload = json.loads(
            base64.urlsafe_b64decode(raw_cursor.encode("ascii")).decode("utf-8")
        )
        if not isinstance(payload, list) or len(payload) != 2:
            raise ValueError("cursor payload must be a two-element list")
        created = datetime.fromisoformat(str(payload[0]))
        report_id = int(payload[1])
        if report_id < 1:
            raise ValueError("cursor report id must be positive")
        return created, report_id
    except (ValueError, UnicodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid cursor") from exc


# ---------------------------------------------------------------------------
# Filter validation (mirrors admin_list_articles' 422-with-valid-list idiom)
# ---------------------------------------------------------------------------


def _validated_status_filter(value: str) -> str:
    if value != "all" and value not in READER_REPORT_STATUS_VALUES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid status '{value}'. "
                f"Valid: {sorted(READER_REPORT_STATUS_VALUES) + ['all']}"
            ),
        )
    return value


def _validated_resolution_filter(value: str) -> str:
    if value != "all" and value not in READER_RESOLUTION_STATUS_VALUES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid resolution '{value}'. "
                f"Valid: {sorted(READER_RESOLUTION_STATUS_VALUES) + ['all']}"
            ),
        )
    return value


def _validated_problem_type_filter(value: str) -> str:
    if value != "all" and value not in READER_PROBLEM_TYPE_VALUES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid problem_type '{value}'. "
                f"Valid: {sorted(READER_PROBLEM_TYPE_VALUES) + ['all']}"
            ),
        )
    return value


# ---------------------------------------------------------------------------
# ORM → contract DTO mapping (module-level so unit tests can hit them
# directly; the routes stay thin).
# ---------------------------------------------------------------------------


def build_decision_item(row: ReaderReportDecision) -> ReaderReportDecisionItem:
    """Map one decision row onto its (bounded) transport item."""
    return ReaderReportDecisionItem(
        id=row.id,
        decision=row.decision,
        actor=row.actor,
        notes=row.notes,
        corrected_at=row.corrected_at,
        correction_summary=row.correction_summary,
        publication_ref=row.publication_ref,
        deploy_evidence=row.deploy_evidence,
        duplicate_of_report_id=row.duplicate_of_report_id,
        created_at=row.created_at,
        closed_at=row.closed_at,
    )


def build_report_item(
    report: ReaderReport,
    *,
    decision_count: int,
    latest_decision: Optional[ReaderReportDecision],
) -> AdminReaderReportItem:
    """Map one report row onto a list item — contact data never mapped.

    The list item has no reporter-email field at all (plan 185 privacy
    law): the absent field is the guarantee, not a filter.
    """
    return AdminReaderReportItem(
        id=report.id,
        status=report.status,
        resolution_status=report.resolution_status,
        resolved_refinery_id=report.resolved_refinery_id,
        resolved_content_sha256=report.resolved_content_sha256,
        resolution_reason=report.resolution_reason,
        problem_type=report.problem_type,
        article_url=report.article_url,
        description=report.description,
        content_snippet=report.content_snippet,
        evidence_url=report.evidence_url,
        tech_browser=report.tech_browser,
        tech_os=report.tech_os,
        submitted_at=report.submitted_at,
        created_at=report.created_at,
        updated_at=report.updated_at,
        contact_purged_at=report.contact_purged_at,
        decision_count=decision_count,
        latest_decision=(
            build_decision_item(latest_decision)
            if latest_decision is not None
            else None
        ),
    )


def build_report_detail(
    session,
    report: ReaderReport,
    decisions: Sequence[ReaderReportDecision],
) -> AdminReaderReportDetail:
    """Full report + append-only history + CONDITIONAL reporter email.

    Privacy contract (plan 185; mirrored on
    ``AdminReaderReportDetail.reporter_email``): included ONLY when a
    ``reader_report_contacts`` row exists AND ``contact_purged_at IS
    NULL``. Contact read is a plain SELECT here in the serving edge —
    never copied anywhere else, never logged, never hashed.
    """
    reporter_email: Optional[str] = None
    if report.contact_purged_at is None:
        contact = (
            session.query(ReaderReportContact)
            .filter(ReaderReportContact.report_id == report.id)
            .one_or_none()
        )
        if contact is not None:
            reporter_email = contact.email

    return AdminReaderReportDetail(
        **build_report_item(
            report,
            decision_count=len(decisions),
            latest_decision=decisions[-1] if decisions else None,
        ).model_dump(),
        reporter_email=reporter_email,
        decisions=[build_decision_item(decision_row) for decision_row in decisions],
    )


def _decision_history(
    session, report_ids: Sequence[int]
) -> dict[int, list[ReaderReportDecision]]:
    """Group decisions for a bounded page of reports (audit order)."""
    if not report_ids:
        return {}
    rows = (
        session.query(ReaderReportDecision)
        .filter(ReaderReportDecision.report_id.in_(tuple(set(report_ids))))
        .order_by(
            ReaderReportDecision.created_at.asc(),
            ReaderReportDecision.id.asc(),
        )
        .all()
    )
    grouped: dict[int, list[ReaderReportDecision]] = {}
    for row in rows:
        grouped.setdefault(row.report_id, []).append(row)
    return grouped


# ---------------------------------------------------------------------------
# Router factory (mirrors admin_images.build_router; the second injected
# callable resolves the app's DatabaseManager without importing api.py).
# ---------------------------------------------------------------------------


def build_router(  # noqa: C901
    verify_admin_token: Callable[..., None],
    get_db_manager: Callable[..., DatabaseManager],
) -> APIRouter:
    """Build the reader-report admin router with the caller's auth + db."""
    router = APIRouter()

    @router.get(
        "/v1/admin/reader-reports",
        response_model=AdminReaderReportEnvelope,
    )
    def admin_list_reader_reports(
        status_filter: str = Query("all", alias="status"),
        resolution_filter: str = Query("all", alias="resolution"),
        problem_type_filter: str = Query("all", alias="problem_type"),
        page_size: int = Query(
            20, ge=_MIN_PAGE_SIZE, le=_MAX_PAGE_SIZE, alias="page_size"
        ),
        cursor: Optional[str] = Query(None, alias="cursor"),
        manager: DatabaseManager = Depends(get_db_manager),
        _: None = Depends(verify_admin_token),
    ) -> AdminReaderReportEnvelope:
        """Bounded, cursor-paginated report queue.

        Anti-leak note: the envelope's items carry no contact data and
        no email field exists on the item contract (plan 185 privacy
        law); the conditional email lives only on the detail endpoint.
        """
        status_filter = _validated_status_filter(status_filter)
        resolution_filter = _validated_resolution_filter(resolution_filter)

        # problem_type has no canonical 'all-of-them' value besides the
        # literal 'all'; validate the same way.
        _validated_problem_type_filter(problem_type_filter)

        with manager.get_session() as session:
            query = session.query(ReaderReport)
            if status_filter != "all":
                query = query.filter(ReaderReport.status == status_filter)
            if resolution_filter != "all":
                query = query.filter(
                    ReaderReport.resolution_status == resolution_filter
                )
            if problem_type_filter != "all":
                query = query.filter(ReaderReport.problem_type == problem_type_filter)

            if cursor:
                cursor_created, cursor_id = _decode_report_cursor(cursor)
                query = query.filter(
                    or_(
                        ReaderReport.created_at < cursor_created,
                        and_(
                            ReaderReport.created_at == cursor_created,
                            ReaderReport.id < cursor_id,
                        ),
                    )
                )

            query = query.order_by(
                ReaderReport.created_at.desc(),
                ReaderReport.id.desc(),
            )

            records = query.limit(page_size + 1).all()
            has_more = len(records) > page_size
            if has_more:
                records = records[:page_size]

            grouped = _decision_history(session, [record.id for record in records])

            data = [
                build_report_item(
                    record,
                    decision_count=len(grouped.get(record.id, ())),
                    latest_decision=(
                        grouped[record.id][-1] if grouped.get(record.id) else None
                    ),
                )
                for record in records
            ]

            return AdminReaderReportEnvelope(
                data=data,
                pagination=AdminReaderReportPagination(
                    next_cursor=(
                        _encode_report_cursor(records[-1]) if has_more else None
                    ),
                    has_more=has_more,
                    page_size=page_size,
                    returned=len(data),
                ),
                filters=AdminReaderReportFilters(
                    status=status_filter,  # type: ignore[arg-type]
                    resolution=resolution_filter,  # type: ignore[arg-type]
                    problem_type=problem_type_filter,  # type: ignore[arg-type]
                ),
                meta={"generated_at": datetime.now(timezone.utc).isoformat()},
            )

    @router.get(
        "/v1/admin/reader-reports/{report_id}",
        response_model=AdminReaderReportDetail,
    )
    def admin_reader_report_detail(
        report_id: int,
        manager: DatabaseManager = Depends(get_db_manager),
        _: None = Depends(verify_admin_token),
    ) -> AdminReaderReportDetail:
        """Full report + audit history + conditional reporter email.

        Privacy contract: ``reporter_email`` is included ONLY when a
        contact row exists AND ``contact_purged_at IS NULL`` (plan 185
        law; the email is purged by deleting the contact row and
        stamping ``contact_purged_at`` — the report body and decisions
        stay). The list endpoint carries no email under any condition.
        """
        with manager.get_session() as session:
            report = load_reader_report(session, report_id)
            if report is None:
                raise HTTPException(status_code=404, detail="Reader report not found")
            history = list_report_decisions(session, report_id)
            return build_report_detail(session, report, history)

    @router.post(
        "/v1/admin/reader-reports/{report_id}/decisions",
        response_model=AdminReaderReportDecisionResult,
        responses={
            200: {
                "description": (
                    "Decision state (append or exact-duplicate replay) with "
                    "the post-decision report."
                ),
                "headers": {
                    "X-Reader-Report-Decision": {
                        "description": (
                            "Whether the request appended a new audit row "
                            "(``applied``), matched an existing identical "
                            "row (``replayed`` — no row added), or recorded "
                            "a triage status change (``triaged``)."
                        ),
                        "schema": {
                            "type": "string",
                            "enum": [
                                _DECISION_HEADER_APPLIED,
                                _DECISION_HEADER_REPLAYED,
                                _DECISION_HEADER_TRIAGED,
                            ],
                        },
                    }
                },
            }
        },
    )
    def admin_decide_reader_report(
        report_id: int,
        payload: ReportDecisionRequest,
        response: Response,
        manager: DatabaseManager = Depends(get_db_manager),
        _: None = Depends(verify_admin_token),
    ) -> AdminReaderReportDecisionResult:
        """Record one triage/decision action on one reader report.

        Legality comes from ``plan_decision`` (pure rules; reasons, not
        prose), persistence from ``apply_report_decision`` (CAS + audit
        row, one transaction). Idempotency: the repository matches an
        exact-duplicate pending decision payload BEFORE inserting — the
        response then carries the current state with
        ``X-Reader-Report-Decision: replayed`` and no second audit row;
        changed payloads (re-decisions) append new rows while the report
        is not closed. ``closed`` is unreachable here: the rules refuse
        it and no transition writes it (plan 188 owns closure).

        The returned ``report.reporter_email`` follows the same privacy
        contract as the detail endpoint (only when a contact row exists
        AND ``contact_purged_at IS NULL``).
        """
        with manager.get_session() as session:
            report = load_reader_report(session, report_id)
            if report is None:
                raise HTTPException(status_code=404, detail="Reader report not found")

            context = build_decision_context(session, report, payload)
            try:
                planned = plan_decision(context, payload)
                applied = apply_report_decision(session, planned)
            except ReportDecisionRuleViolation as violation:
                raise HTTPException(
                    status_code=_RULE_HTTP_STATUS[violation.reason],
                    detail=(
                        f"Reader report action refused: {violation.reason}; "
                        f"{violation.detail}"
                    ),
                ) from violation
            except StaleReportStateConflict as conflict:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Reader report changed concurrently; "
                        f"{conflict}. Re-read and retry."
                    ),
                ) from conflict

            history = list_report_decisions(session, report_id)
            detail = build_report_detail(session, applied.report, history)

            header = _DECISION_HEADER_APPLIED
            replayed = False
            replayed_decision_id: Optional[int] = None
            inserted_decision_id: Optional[int] = None
            action: str = planned.action

            if applied.replayed_decision_id is not None:
                header = _DECISION_HEADER_REPLAYED
                replayed = True
                replayed_decision_id = applied.replayed_decision_id
            elif action == "triage":
                header = _DECISION_HEADER_TRIAGED
            elif applied.inserted_decision is not None:
                inserted_decision_id = applied.inserted_decision.id

            response.headers["X-Reader-Report-Decision"] = header

            return AdminReaderReportDecisionResult(
                report=detail,
                action=action,  # type: ignore[arg-type]
                inserted_decision_id=inserted_decision_id,
                replayed=replayed,
                replayed_decision_id=replayed_decision_id,
            )

    return router
