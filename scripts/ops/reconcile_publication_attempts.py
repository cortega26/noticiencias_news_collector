#!/usr/bin/env python3
"""On-demand reconciler for stale publication attempts
(Plan 060 / Phase 5b, master spec Phase 5 item 4).

A `PR_CREATED` publication attempt whose callback was lost (or whose
processing failed) sits forever: the frontend's deploy already happened but
the backend never applied the transition. This script runs one reconciliation
pass, which:

1. replays unprocessed webhook receipts (`received`/`failed`) whose
   `publication_ids` name a stale attempt, through the *real* callback
   effects (same code path as the serving webhook);
2. repairs an attempt whose legacy article is already `completed` *and* has
   a real deploy URL, or already `rejected`;
3. leaves a genuinely open PR alone and reports it as actionable.

It never creates a pull request and never marks an attempt `COMPLETED`
without deploy evidence. Convention: a manual on-demand ops script, like
`scripts/ops/prune_workflow_runs.py` — this repo has no scheduler
infrastructure, so wiring an external timer is out of scope.

Usage:
    python scripts/ops/reconcile_publication_attempts.py \
        [--stale-minutes 60] [--limit 100] [--receipt-limit 500] [--dry-run]

Exit codes: 0 on a completed pass (stale findings are a successful report),
1 on an unexpected failure.
"""

from __future__ import annotations

import argparse
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from news_collector.logic.workflows.publication_reconciliation import (  # noqa: E402
    DEFAULT_LIMIT,
    DEFAULT_RECEIPT_LIMIT,
    DEFAULT_STALE_MINUTES,
    PublicationReconciliationWorkflow,
)
from news_collector.storage.database import DatabaseManager  # noqa: E402
from news_collector.utils.logger import get_logger  # noqa: E402

logger = get_logger().create_module_logger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Reconcile stale PR_CREATED publication attempts by replaying "
            "stored webhook receipts and applying evidence-backed "
            "transitions (Plan 060 / Phase 5b). Never creates PRs and never "
            "publishes without deploy evidence."
        )
    )
    parser.add_argument(
        "--stale-minutes",
        type=int,
        default=DEFAULT_STALE_MINUTES,
        help=(
            "Attempts in PR_CREATED at least this old are candidates "
            f"(default: {DEFAULT_STALE_MINUTES})."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Maximum candidate attempts per pass (default: {DEFAULT_LIMIT}).",
    )
    parser.add_argument(
        "--receipt-limit",
        type=int,
        default=DEFAULT_RECEIPT_LIMIT,
        help=(
            "Maximum unprocessed receipts to scan per pass "
            f"(default: {DEFAULT_RECEIPT_LIMIT})."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would happen without writing anything.",
    )
    args = parser.parse_args()

    db = DatabaseManager()
    try:
        workflow = PublicationReconciliationWorkflow(db)
        summary = workflow.run(
            stale_minutes=args.stale_minutes,
            limit=args.limit,
            receipt_limit=args.receipt_limit,
            dry_run=args.dry_run,
        )
    finally:
        db.close()

    prefix = "[reconcile-publications]"
    print(f"{prefix} scanned={summary.scanned}")
    print(f"{prefix} replayable_receipts={summary.replayable_receipts}")
    print(f"{prefix} replayed={summary.replayed}")
    print(f"{prefix} completed={summary.completed}")
    print(f"{prefix} rejected={summary.rejected}")
    print(f"{prefix} stale_pr_open={summary.stale_pr_open}")
    print(f"{prefix} missing_deploy_evidence={summary.missing_deploy_evidence}")
    print(f"{prefix} malformed_payloads={summary.malformed_payloads}")
    print(f"{prefix} unmatched_receipts={summary.unmatched_receipts}")
    if args.dry_run:
        print(f"{prefix} dry-run: no rows were written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
