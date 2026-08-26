#!/usr/bin/env python3
"""On-demand retention: delete terminal ``workflow_runs`` rows older than a
retention window (Plan 060 / Phase 4a, spec.md Design §4).

Only rows in a terminal status (``succeeded``, ``failed``, ``cancelled``,
``interrupted``) whose ``finished_at`` is older than the retention window
are eligible. A row in ``queued``/``running`` is never eligible regardless
of age — this is the direct fix for the bug the old in-memory
``_prune_collect_runs`` had (keep-2-by-count, no status check, so a
still-running row could be evicted mid-flight; see
``plans/060/phase-4a-collection-run-workflow/spec.md`` recon). A row whose
``finished_at`` is somehow NULL despite a terminal status is treated as
ineligible (age cannot be determined) rather than guessed at.

Convention: a plain on-demand ops script, not a scheduled job — this repo
has no scheduled-job infrastructure to hook into. Checked ``scripts/`` and
``scripts/ops/`` for a periodic-maintenance precedent before writing this;
the closest is ``scripts/ops/purge_short_articles.py``, itself a plain
manually-invoked script (raw ``sqlite3``, no cron wiring). This script
follows that same "on-demand, operator-invoked" shape but goes through
``DatabaseManager``/the ORM model (not raw SQL) since it needs to reason
about ``workflow_runs``' typed status vocabulary, matching how
``scripts/backfill_lifecycle_tables.py`` (the other script touching a
Phase 3a/4a lineage table) is built. Wiring this into cron/systemd-timer/
some other external scheduler, if periodic execution is wanted later, is
explicitly out of this phase's scope (spec.md Design §4 only asks for the
cleanup logic and its test, not a scheduler).

Usage:
    python scripts/ops/prune_workflow_runs.py [--retention-days 90] [--dry-run]
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from news_collector.storage.database import DatabaseManager  # noqa: E402
from news_collector.storage.models import (  # noqa: E402
    WorkflowRun,
    WorkflowStageAttempt,
)
from news_collector.utils.logger import get_logger  # noqa: E402

logger = get_logger().create_module_logger(__name__)

DEFAULT_RETENTION_DAYS = 90

# Terminal statuses only — 'queued'/'running' are never eligible for
# pruning, regardless of age.
_TERMINAL_STATUSES = ("succeeded", "failed", "cancelled", "interrupted")


@dataclass
class PruneSummary:
    candidates_found: int = 0
    rows_deleted: int = 0


def prune_workflow_runs(
    db: DatabaseManager,
    *,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    dry_run: bool = False,
) -> PruneSummary:
    """Delete terminal ``workflow_runs`` rows whose ``finished_at`` is older
    than ``retention_days``. Returns a summary; deletes nothing when
    ``dry_run`` is True.

    ``workflow_stage_attempts.workflow_run_id`` is ``ON DELETE RESTRICT``
    (Phase 3a) — a run with any recorded stage attempt cannot be deleted
    until its attempts are deleted first, or the whole batch's commit fails
    and rolls back (an automated review caught this: it's currently inert
    since nothing writes stage attempts yet, but would silently defeat the
    advertised retention window the moment something does). Each
    candidate's stage attempts are deleted first, in the same per-row unit
    of work, so one row cannot take the rest of the batch down with it.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    summary = PruneSummary()
    with db.get_session() as session:
        candidate_ids = (
            session.query(WorkflowRun.id)
            .filter(
                WorkflowRun.status.in_(_TERMINAL_STATUSES),
                WorkflowRun.finished_at.isnot(None),
                WorkflowRun.finished_at < cutoff,
            )
            .all()
        )
        summary.candidates_found = len(candidate_ids)

    if dry_run or not candidate_ids:
        return summary

    for (run_id,) in candidate_ids:
        with db.get_session() as session:
            row = session.get(WorkflowRun, run_id)
            if row is None:  # deleted by something else since the scan above
                continue
            session.query(WorkflowStageAttempt).filter(
                WorkflowStageAttempt.workflow_run_id == run_id
            ).delete(synchronize_session=False)
            logger.info(
                "Pruning workflow_run {} (run_type={}, status={}, finished_at={})",
                row.id,
                row.run_type,
                row.status,
                row.finished_at,
            )
            session.delete(row)
        summary.rows_deleted += 1
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Delete terminal workflow_runs rows older than the retention "
            "window (Plan 060 / Phase 4a). queued/running rows are never "
            "eligible, regardless of age."
        )
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=DEFAULT_RETENTION_DAYS,
        help=f"Retention window in days (default: {DEFAULT_RETENTION_DAYS}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report candidates without deleting anything.",
    )
    args = parser.parse_args()

    db = DatabaseManager()
    try:
        summary = prune_workflow_runs(
            db, retention_days=args.retention_days, dry_run=args.dry_run
        )
    finally:
        db.close()

    print(f"[prune-workflow-runs] candidates_found={summary.candidates_found}")
    print(f"[prune-workflow-runs] rows_deleted={summary.rows_deleted}")
    if args.dry_run and summary.candidates_found:
        print("[prune-workflow-runs] dry-run: no rows deleted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
