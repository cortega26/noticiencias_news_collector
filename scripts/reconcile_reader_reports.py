#!/usr/bin/env python3
"""Reconcile Worker report intake from R2 into the backend (plan 186).

The frontend Worker stores every accepted reader report as
``reports/YYYY-MM-DD/<uuid>.json`` in the R2 bucket ``noticiencias-reports``
(pretty-printed JSON with the record's ``id``/``submitted_at``/payload
fields). This operator entrypoint pulls those objects through the
Cloudflare REST API and persists them idempotently: the same object
reconciled any number of times yields exactly one ``reader_reports`` row
(the Worker UUID is the ``idempotency_key``) with at most one contact row,
and every per-object failure is a typed, counted outcome — nothing is
silently dropped and existing rows are never rewritten.

    python scripts/reconcile_reader_reports.py [--limit 100] [--prefix R]
        [--since ISO] [--dry-run]

Prerequisites (see .env.example): ``CLOUDFLARE_ACCOUNT_ID`` and
``CLOUDFLARE_R2_API_TOKEN`` (Workers R2 Storage Edit); optional
``CLOUDFLARE_R2_REPORT_BUCKET`` override.

Exit codes: 0 on a completed pass (duplicates, invalid records and skipped
reports are a report, matching ``pull_webhook_receipts.py``), 1 when the
R2 listing fails or the input is invalid — a run-level failure, and 2 when
the Cloudflare credentials are missing (checked before any I/O).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from news_collector.contracts.reader_reports import (  # noqa: E402
    PersistOutcome,
    ReconciliationSummary,
    ValidReportIntake,
)
from news_collector.infrastructure.r2_client import (  # noqa: E402
    DEFAULT_PREFIX,
    R2ConfigurationError,
    R2Credentials,
    R2ReportClient,
    load_r2_credentials,
)
from news_collector.logic.workflows.reader_reports import resolve_report_identity
from news_collector.logic.workflows.report_reconciliation import (
    reconcile_report_objects,
)
from news_collector.storage.database import DatabaseManager
from news_collector.storage.reader_report_repository import (
    report_exists,
    upsert_reader_report,
)

DEFAULT_LIMIT = 100
SCRIPT_TAG = "[reconcile-reports]"


def parse_since(value: Optional[str]) -> Optional[datetime]:
    """Parse ``--since`` (``YYYY-MM-DD`` or full ISO datetime) as UTC-aware.

    ``YYYY-MM-DD`` means "from the start of that UTC day" — the R2 key date
    and ``record.submitted_at`` share that reading (Worker's
    ``toISOString().slice(0, 10)``).
    """
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        if len(text) == 10 and text[4] == "-" and text[7] == "-":
            return datetime.fromisoformat(f"{text}T00:00:00+00:00")
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(
            f"invalid --since: {value!r} (YYYY-MM-DD or ISO datetime)"
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _dry_run_persister(db: DatabaseManager) -> Callable[..., PersistOutcome]:
    """Read-only classifier: duplicates vs would-be inserts — no writes."""

    def persist(intake: ValidReportIntake, identity: Any) -> PersistOutcome:
        with db.SessionLocal() as session:
            exists = report_exists(session, idempotency_key=intake.idempotency_key)
        return PersistOutcome(status="duplicate" if exists else "created")

    return persist


def _committing_persister(db: DatabaseManager) -> Callable[..., PersistOutcome]:
    """Real persistence: idempotent upsert, one transaction per object."""

    def persist(intake: ValidReportIntake, identity: Any) -> PersistOutcome:
        with db.SessionLocal() as session:
            report, created = upsert_reader_report(
                session,
                idempotency_key=intake.idempotency_key,
                payload=intake.payload,
                submitted_at=intake.submitted_at,
                identity=identity,
                reporter_email=intake.payload.reporter_email,
            )
            session.commit()
        return PersistOutcome(status="created" if created else "duplicate")

    return persist


def run_reconciliation(
    db: DatabaseManager,
    *,
    credentials: R2Credentials,
    limit: int = DEFAULT_LIMIT,
    prefix: str = DEFAULT_PREFIX,
    since: Optional[datetime] = None,
    dry_run: bool = False,
    feed: Optional[R2ReportClient] = None,
) -> ReconciliationSummary:
    """One idempotent reconciliation pass (injectable feed for tests)."""
    parsed_feed: R2ReportClient = feed or R2ReportClient(credentials)
    try:
        return reconcile_report_objects(
            feed=parsed_feed,
            resolve_identity=lambda url: resolve_report_identity(url, db),
            persist_report=(
                _dry_run_persister(db) if dry_run else _committing_persister(db)
            ),
            prefix=prefix,
            limit=limit,
            since=since,
        )
    finally:
        if feed is None:
            parsed_feed.close()


def _summary_payload(summary: ReconciliationSummary) -> Dict[str, Any]:
    """JSON-safe summary counters plus per-key outcomes and reason counts."""
    outcomes = [
        {
            "key": outcome.key,
            "status": outcome.status,
            "idempotency_key": outcome.idempotency_key,
            "reason": outcome.reason,
        }
        for outcome in summary.outcomes
    ]
    by_reason: Dict[str, int] = {}
    for outcome in summary.outcomes:
        if outcome.status in ("invalid", "fetch_failed", "persist_failed", "skipped"):
            reason = outcome.reason or "unspecified"
            by_reason[reason] = by_reason.get(reason, 0) + 1
    return {
        "listed": summary.listed,
        "fetched": summary.fetched,
        "created": summary.created,
        "duplicates": summary.duplicates,
        "invalid": summary.invalid,
        "skipped": summary.skipped,
        "fetch_failed": summary.fetch_failed,
        "persist_failed": summary.persist_failed,
        "truncated": summary.truncated,
        "fatal": summary.fatal,
        "by_reason": by_reason,
        "outcomes": outcomes,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Pull reader-report R2 objects via the Cloudflare REST API and "
            "reconcile them into reader_reports (plan 186). Idempotent by "
            "Worker record id; per-object failures are counted outcomes."
        )
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Maximum objects to process this pass (default: {DEFAULT_LIMIT}).",
    )
    parser.add_argument(
        "--prefix",
        default=DEFAULT_PREFIX,
        help=f"R2 key prefix to scan (default: {DEFAULT_PREFIX!r}).",
    )
    parser.add_argument(
        "--since",
        default=None,
        help=(
            "Skip reports submitted before this date/time (YYYY-MM-DD or "
            "ISO datetime); UTC is assumed."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Classify without writing anything (created = would-store).",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()

    # Credentials BEFORE any I/O (no R2 request, no database connection).
    try:
        credentials = load_r2_credentials()
    except R2ConfigurationError as exc:
        print(f"{SCRIPT_TAG} EXITING: {exc}", file=sys.stderr)
        return 2

    if args.limit < 1:
        print(f"{SCRIPT_TAG} EXITING: --limit must be at least 1", file=sys.stderr)
        return 1
    try:
        since = parse_since(args.since)
    except ValueError as exc:
        print(f"{SCRIPT_TAG} EXITING: {exc}", file=sys.stderr)
        return 1

    db = DatabaseManager()
    try:
        summary = run_reconciliation(
            db,
            credentials=credentials,
            limit=args.limit,
            prefix=args.prefix,
            since=since,
            dry_run=args.dry_run,
        )
    finally:
        db.close()

    print(json.dumps(_summary_payload(summary), indent=2))

    if summary.fatal:
        print(
            f"{SCRIPT_TAG} run failed listing reports: {summary.fatal}", file=sys.stderr
        )
        return 1
    if args.dry_run:
        print(f"{SCRIPT_TAG} dry-run: no rows were written", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
