#!/usr/bin/env python3
"""Read-only reconciliation report: legacy ``article_metadata`` publication/
audit state vs. the backfilled ``publication_attempts``/``editorial_decisions``
rows (Plan 060 / Phase 3b).

Never writes to the database — every operation here is a read via
``LifecycleRepository``'s query methods and a plain ``Article`` query.
Compares, for every ``Article`` row with legacy ``publication``/``audit``
metadata, the mapped fields (per plans/060/phase-3b-typed-repos/spec.md
recon finding 4) against the corresponding new-table row(s), and classifies
each comparison as one of:

  - "clean": legacy data and the new-table row agree.
  - "drift": legacy data and the new-table row disagree — a real mismatch.
  - "missing": legacy data exists but no new-table row does (the backfill
    has not run yet, or failed, for this article).
  - "not_applicable": the legacy audit state is not a completed decision
    (pending/skipped/unrecognized) — nothing should have been backfilled
    for it, so its absence must not be reported as "missing".

Exit code: 0 if every check is "clean" or "not_applicable"; 1 if any check
is "drift" or "missing".

Usage:
    python scripts/lifecycle_reconciliation_report.py [--verbose]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from news_collector.storage.database import DatabaseManager  # noqa: E402
from news_collector.storage.lifecycle_repository import (  # noqa: E402
    LifecycleRepository,
    map_legacy_audit_outcome,
)
from news_collector.storage.models import Article  # noqa: E402


@dataclass(frozen=True)
class ReconciliationCheck:
    article_id: int
    kind: str  # "publication" | "audit"
    status: str  # "clean" | "drift" | "missing" | "not_applicable"
    detail: str | None = None


@dataclass
class ReconciliationSummary:
    checks: list[ReconciliationCheck] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        counts = {"clean": 0, "drift": 0, "missing": 0, "not_applicable": 0}
        for check in self.checks:
            counts[check.status] += 1
        return counts

    def ok(self) -> bool:
        counts = self.counts()
        return counts["drift"] == 0 and counts["missing"] == 0


def _check_publication(
    lifecycle: LifecycleRepository, article: Article, publication: dict[str, Any]
) -> ReconciliationCheck:
    refinery_id = publication.get("refinery_id") or str(article.id)
    rows = lifecycle.get_publication_attempts_for_article(article.id)
    match = next((r for r in rows if r.refinery_id == refinery_id), None)
    if match is None:
        return ReconciliationCheck(
            article.id,
            "publication",
            "missing",
            f"no publication_attempts row for refinery_id={refinery_id!r}",
        )

    mismatches = []
    if match.state != publication.get("state"):
        mismatches.append(
            f"state legacy={publication.get('state')!r} new={match.state!r}"
        )
    if match.pr_url != publication.get("pr_url"):
        mismatches.append(
            f"pr_url legacy={publication.get('pr_url')!r} new={match.pr_url!r}"
        )
    if mismatches:
        return ReconciliationCheck(
            article.id, "publication", "drift", "; ".join(mismatches)
        )
    return ReconciliationCheck(article.id, "publication", "clean")


def _check_audit(
    lifecycle: LifecycleRepository, article: Article, audit: dict[str, Any]
) -> ReconciliationCheck:
    state = audit.get("state")
    expected_outcome = map_legacy_audit_outcome(state)
    if expected_outcome is None:
        return ReconciliationCheck(
            article.id,
            "audit",
            "not_applicable",
            f"legacy audit state {state!r} is not a completed decision",
        )

    rows = [
        d
        for d in lifecycle.get_editorial_decisions_for_article(article.id)
        if d.decision_type == "auditor"
    ]
    if not rows:
        return ReconciliationCheck(
            article.id,
            "audit",
            "missing",
            "no editorial_decisions row for decision_type='auditor'",
        )

    match = rows[0]
    mismatches = []
    if match.outcome != expected_outcome:
        mismatches.append(
            f"outcome expected={expected_outcome!r} new={match.outcome!r}"
        )
    legacy_reason = audit.get("reason") or None
    if (match.reason or None) != legacy_reason:
        mismatches.append(f"reason legacy={legacy_reason!r} new={match.reason!r}")
    if mismatches:
        return ReconciliationCheck(article.id, "audit", "drift", "; ".join(mismatches))
    return ReconciliationCheck(article.id, "audit", "clean")


def reconcile(db: DatabaseManager) -> ReconciliationSummary:
    """Compare every article's legacy publication/audit metadata against the
    backfilled lifecycle tables. Read-only: never modifies any row."""
    summary = ReconciliationSummary()
    with db.get_session() as session:
        articles = session.query(Article).all()
        for article in articles:
            metadata = article.article_metadata or {}
            publication = metadata.get("publication")
            audit = metadata.get("audit")
            if publication:
                summary.checks.append(
                    _check_publication(db.lifecycle, article, publication)
                )
            if audit:
                summary.checks.append(_check_audit(db.lifecycle, article, audit))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only reconciliation report comparing legacy "
            "article_metadata against the backfilled lifecycle tables."
        )
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Include every check in the JSON output, not just non-clean ones.",
    )
    args = parser.parse_args()

    db = DatabaseManager()
    try:
        summary = reconcile(db)
    finally:
        db.close()

    counts = summary.counts()
    checks_to_report = (
        summary.checks
        if args.verbose
        else [c for c in summary.checks if c.status != "clean"]
    )
    report = {
        "status": "PASS" if summary.ok() else "FAIL",
        "counts": counts,
        "checks": [
            {
                "article_id": c.article_id,
                "kind": c.kind,
                "status": c.status,
                "detail": c.detail,
            }
            for c in checks_to_report
        ],
    }
    print(json.dumps(report, indent=2))
    return 0 if summary.ok() else 1


if __name__ == "__main__":
    sys.exit(main())
