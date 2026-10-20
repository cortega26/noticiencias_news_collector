"""Idempotent persistence for reconciled reader reports (plan 186).

The reconciliation promise: the same R2 report object processed any number
of times yields exactly one ``reader_reports`` row — the Worker's record
``id`` (UUID) is the ``idempotency_key``, and first-seen content wins.
A replay is a *counted duplicate outcome*, never a rewrite: resolution
fields stamped at insert time are left untouched.

Privacy (plan 185 law): the reporter email lives ONLY in
``reader_report_contacts`` — never on the report row. The email reaches
this module exclusively through the explicit ``reporter_email`` argument;
the payload's transport field is never read implicitly, so a caller that
 hands no email produces a report with no contact row.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Tuple

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from news_collector.contracts.reader_reports import ReaderReportPayload, ReportIdentity
from news_collector.storage.models import ReaderReport, ReaderReportContact


def report_exists(session: Session, *, idempotency_key: str) -> bool:
    """True when a report row carries this idempotency key (SELECT only).

    Used by the dry-run wiring to classify would-be outcomes without
    writing anything.
    """
    statement = select(ReaderReport.id).where(
        ReaderReport.idempotency_key == idempotency_key
    )
    found = session.execute(statement).scalar_one_or_none()
    return found is not None


def _row_from_payload(payload: ReaderReportPayload, report: ReaderReport) -> None:
    """Copy report-body columns from the validated payload onto ``report``.

    Enumerates persisted columns explicitly: ``reporter_email`` is
    deliberately absent (contact-separated by law) and the Worker meta
    fields belong to the record metadata, not the report body.
    """
    report.problem_type = payload.problem_type
    report.article_url = payload.article_url
    report.description = payload.description
    report.content_snippet = payload.content_snippet
    report.evidence_url = payload.evidence_url
    report.tech_browser = payload.tech_browser
    report.tech_os = payload.tech_os


def _row_from_identity(identity: ReportIdentity, report: ReaderReport) -> None:
    """Server-resolved identity (never reader-supplied) onto ``report``."""
    report.resolution_status = identity.status
    report.resolved_refinery_id = identity.refinery_id
    report.resolved_content_sha256 = identity.content_sha256
    report.resolution_reason = identity.reason


def upsert_reader_report(
    session: Session,
    *,
    idempotency_key: str,
    payload: ReaderReportPayload,
    submitted_at: datetime,
    identity: ReportIdentity,
    reporter_email: Optional[str] = None,
) -> Tuple[ReaderReport, bool]:
    """Insert the report once per idempotency key; replays are no-ops.

    Returns ``(report, created)`` — ``created=False`` means an existing row
    was found (or won by a concurrent reconciler between our SELECT and
    INSERT) and was left untouched: the caller accounts it as a duplicate
    and first-seen resolution data survives. The session is flushed but
    not committed; the caller owns the transaction boundary so a failure
    cannot half-commit a report plus its contact row.

    ``reporter_email`` is an explicit argument (plan 186 signature): it is
    persisted only on the contact row, at most once per report.
    """
    existing = session.execute(
        select(ReaderReport).where(ReaderReport.idempotency_key == idempotency_key)
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    report = ReaderReport(
        idempotency_key=idempotency_key,
        status="new",
        submitted_at=submitted_at,
    )
    _row_from_payload(payload, report)
    _row_from_identity(identity, report)
    session.add(report)

    try:
        session.flush()  # assign report.id before the FK'd contact row
    except IntegrityError:
        # A concurrent reconciler inserted the same key between our SELECT
        # and this INSERT; the unique index won. The replayed read is the
        # duplicate outcome — the winner is never rewritten (LAW-B5).
        session.rollback()
        winner = session.execute(
            select(ReaderReport).where(ReaderReport.idempotency_key == idempotency_key)
        ).scalar_one_or_none()
        if winner is None:
            raise
        return winner, False

    email = (reporter_email or "").strip()
    if email:
        session.add(ReaderReportContact(report_id=report.id, email=email))

    return report, True
