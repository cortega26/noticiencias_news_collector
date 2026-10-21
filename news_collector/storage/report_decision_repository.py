"""Transactional admin decisions for reader reports (plan 187).

One admin action = one database transaction: the report's status change
(compare-and-set, CAS) and the append-only decision row commit together
through the caller's session (``DatabaseManager.get_session`` owns
commit/rollback). This mirrors ``lifecycle_repository``'s audited
transitions — a CAS ``UPDATE ... WHERE id = ? AND status = <_expected>``
guards the ORM-object path so a report that changed under a concurrent
request can never be silently overwritten; a lost race raises
:class:`StaleReportStateConflict` instead of writing a corrupt audit.

Race discipline (plan 187):

- ``with_for_update()`` row-locking is requested for the loaded row (a
  no-op on SQLite whose dialect drops the clause, decisive on
  PostgreSQL).
- The decision row is inserted only AFTER the CAS won, so a lost race
  never leaves an audit row without its status change (append-only
  ordering preserved: rows only ever follow transitions, in one
  transaction).
- Exact-duplicate replay is matched BEFORE the CAS: the identical
  (actor+decision+notes+corrected_at+correction_summary+
  duplicate_of_report_id) payload returns the current state and writes
  nothing, so a retried admin POST cannot double-append.

Privacy (plan 185 law, unchanged): this module never reads nor copies
``reader_report_contacts``; the email column lives only in the contact
row and only the serving detail endpoint surfaces it, conditionally.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from news_collector.contracts.reader_reports import (
    DecisionContext,
    PlannedDecision,
    ReportDecisionRequest,
)
from news_collector.storage.models import ReaderReport, ReaderReportDecision

# The status value plan 188 introduces; this surface may neither read it
# as a legal target nor write it (defense against a later caller mistake
# in the apply path).
_STATUS_CLOSED = "closed"


@dataclass(frozen=True)
class DecisionApplyResult:
    """Outcome of one applied decision (detail for typed responses).

    ``report`` is the refreshed row (its attributes are current for this
    session, including the CAS'd status); ``inserted_decision`` is the
    new audit row (``None`` for replays and for triage actions, which
    append no row by design).
    """

    report: ReaderReport
    inserted_decision: Optional[ReaderReportDecision]
    replayed_decision_id: Optional[int] = None


class StaleReportStateConflict(Exception):
    """CAS miss: the report row changed since the decision was planned.

    Serving maps this onto a 409 with a typed reason so a concurrent
    editor gets a retryable failure instead of a silently dropped
    decision.
    """

    def __init__(self, report_id: int, expected_status: str) -> None:
        super().__init__(
            f"reader report {report_id} no longer has status "
            f"{expected_status!r} (changed concurrently)"
        )
        self.report_id = report_id
        self.expected_status = expected_status


def load_reader_report(session: Session, report_id: int) -> Optional[ReaderReport]:
    """Fresh-row SELECT with ``with_for_update`` when the backend supports it.

    SQLite drops the lock clause (single-writer serialization supersedes
    it); PostgreSQL uses it to serialize planning against concurrent
    decisions within the same transaction.
    """
    statement = (
        select(ReaderReport).where(ReaderReport.id == report_id).with_for_update()
    )
    return session.execute(statement).scalar_one_or_none()


def duplicate_target_exists(session: Session, target_report_id: int) -> bool:
    """True when another report row exists under ``target_report_id``.

    Existence only — the decision surface never edits the target and
    never cascades into it (no FK by design, see the plan 187 migration).
    """
    found = session.execute(
        select(ReaderReport.id).where(ReaderReport.id == target_report_id)
    ).scalar_one_or_none()
    return found is not None


def build_decision_context(
    session: Session,
    report: ReaderReport,
    request: ReportDecisionRequest,
) -> DecisionContext:
    """SELECT-only inputs the pure rules need (LAW-B4).

    - Exact-duplicate replay match: an earlier decision row for this
      report whose persisted payload equals the request's (the CHECK
      constraint keeps ``decision`` non-null, so a triage request —
      whose echo has no decision — can never match a row).
    - Duplicate-target existence: checked only when the request carries
      a ``duplicate_of_report_id``.
    """
    statement = (
        select(ReaderReportDecision.id)
        .where(
            ReaderReportDecision.report_id == report.id,
            ReaderReportDecision.actor == request.actor,
            ReaderReportDecision.notes == request.notes,
            ReaderReportDecision.corrected_at == request.corrected_at,
            ReaderReportDecision.correction_summary == request.correction_summary,
            ReaderReportDecision.duplicate_of_report_id
            == request.duplicate_of_report_id,
            ReaderReportDecision.decision == request.decision,
        )
        .order_by(
            ReaderReportDecision.created_at.desc(),
            ReaderReportDecision.id.desc(),
        )
        .limit(1)
    )
    replayed = session.execute(statement).scalar_one_or_none()

    duplicate_of_exists: Optional[bool] = None
    if request.duplicate_of_report_id is not None:
        duplicate_of_exists = duplicate_target_exists(
            session, request.duplicate_of_report_id
        )

    return DecisionContext(
        report_id=report.id,
        current_status=report.status,
        duplicate_of_exists=duplicate_of_exists,
        replayed_decision_id=replayed,
    )


def list_report_decisions(
    session: Session, report_id: int
) -> Sequence[ReaderReportDecision]:
    """Append-only decision history in audit order (oldest first).

    ``created_at`` cannot order same-second ties reliably, so ``id`` is
    the deterministic tie-break (row ids are monotonic locally); the
    ordering happens in SQL to keep aware/naive collation engine-side.
    """
    return (
        session.query(ReaderReportDecision)
        .filter(ReaderReportDecision.report_id == report_id)
        .order_by(
            ReaderReportDecision.created_at.asc(),
            ReaderReportDecision.id.asc(),
        )
        .all()
    )


def apply_report_decision(
    session: Session,
    planned: PlannedDecision,
) -> DecisionApplyResult:
    """CAS the status and append the audit row in ONE transaction.

    The caller owns the transaction boundary (``manager.get_session()``):
    on any raised error the session rolls back, so a CAS'd status update
    can never commit without its audit row, nor the other way around.

    - Exact-duplicate replays write nothing and return the refreshed
      current state.
    - Triage actions CAS only the status (no decision row — see the
      module docstring and plan 187's one-column migration scope).
    """
    report = session.get(ReaderReport, planned.report_id)
    if report is None:
        raise ValueError(
            f"reader report {planned.report_id} does not exist; plan the "
            "decision from a loaded report"
        )

    refreshed_id = planned.replayed_decision_id
    if not planned.insert_decision_row and planned.next_status is None:
        # Replay: audit conservation — no row, no CAS, new answer = the
        # CURRENT state (re-read: the snapshot may be stale).
        session.refresh(report)
        return DecisionApplyResult(
            report=report,
            inserted_decision=None,
            replayed_decision_id=refreshed_id,
        )

    if planned.next_status == _STATUS_CLOSED:
        raise ValueError(
            "plan 188 owns closure; the report-decision surface may never "
            "write 'closed'"
        )

    result = session.execute(
        update(ReaderReport)
        .where(
            ReaderReport.id == planned.report_id,
            ReaderReport.status == planned.current_status,
            ReaderReport.status != _STATUS_CLOSED,
        )
        .values(status=planned.next_status, updated_at=datetime.now(timezone.utc))
    )
    if result.rowcount != 1:
        raise StaleReportStateConflict(planned.report_id, planned.current_status)

    inserted: Optional[ReaderReportDecision] = None
    if planned.insert_decision_row:
        inserted = ReaderReportDecision(
            report_id=planned.report_id,
            decision=planned.decision,
            actor=planned.actor,
            notes=planned.notes,
            corrected_at=planned.corrected_at,
            correction_summary=planned.correction_summary,
            duplicate_of_report_id=planned.duplicate_of_report_id,
        )
        session.add(inserted)

    session.flush()  # assign ids so the response can reference the row

    # The Core UPDATE bypassed ORM listeners for the loaded instance:
    # re-read the row so the response reports the committed-intent state.
    session.refresh(report)
    return DecisionApplyResult(
        report=report,
        inserted_decision=inserted,
        replayed_decision_id=None,
    )
