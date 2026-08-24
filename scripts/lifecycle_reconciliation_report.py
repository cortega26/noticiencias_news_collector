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
from datetime import datetime, timezone
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
    # "clean" | "drift" | "not_applicable" | "missing" (no --dual-write-since)
    # | "missing_pre_dualwrite" | "missing_post_dualwrite" (with the flag)
    status: str
    detail: str | None = None


@dataclass
class ReconciliationSummary:
    checks: list[ReconciliationCheck] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        # Base keys always present (backward-compatible shape when
        # --dual-write-since is omitted); any additional status
        # (missing_pre_dualwrite/missing_post_dualwrite) is added
        # dynamically only if it actually occurs, per Plan 060 / Phase 3c.
        counts = {"clean": 0, "drift": 0, "missing": 0, "not_applicable": 0}
        for check in self.checks:
            counts[check.status] = counts.get(check.status, 0) + 1
        return counts

    def ok(self) -> bool:
        counts = self.counts()
        return (
            counts["drift"] == 0
            and counts["missing"] == 0
            and counts.get("missing_post_dualwrite", 0) == 0
        )


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

    # Plan 060 / Phase 3c: dual-write's update_article_audit_status has no
    # idempotency guard (unlike the backfill's editorial_decision_exists
    # check) — a second terminal audit call for the same article correctly
    # appends a second row (genuinely append-only history), so more than
    # one "auditor" row can now exist. Legacy article_metadata["audit"]
    # only ever reflects the *current* (i.e. most recent) decision, so
    # comparison must target the newest row, not rows[0] (which, ordered
    # ascending by decided_at, would be the oldest and could report
    # spurious "drift" once history accumulates). Tie-broken by id for the
    # same determinism reason as the (attempt_number, id) publication tie-break.
    match = max(rows, key=lambda d: (d.decided_at, d.id))
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


def _split_missing_status(
    check: ReconciliationCheck,
    article: Article,
    dual_write_since: datetime | None,
) -> ReconciliationCheck:
    """Plan 060 / Phase 3c: once dual-write ships, a "missing" result means
    something different depending on when the article was collected —
    before the cutover, the backfill simply hasn't (or can't retroactively)
    run; on/after it, dual-write should have created the row live, so
    "missing" is now an actionable dual-write failure. No-ops (returns
    ``check`` unchanged) when ``dual_write_since`` is ``None`` or the
    check isn't "missing" — this is what keeps the flag-omitted case
    byte-identical to pre-Phase-3c output.
    """
    if dual_write_since is None or check.status != "missing":
        return check

    collected = article.collected_date
    # DateTime(timezone=True) columns can still come back naive from
    # SQLite (it has no native tz storage) — normalize to UTC before
    # comparing rather than letting a naive/aware comparison raise.
    if collected.tzinfo is None:
        collected = collected.replace(tzinfo=timezone.utc)

    is_post = collected >= dual_write_since
    new_status = "missing_post_dualwrite" if is_post else "missing_pre_dualwrite"
    return ReconciliationCheck(check.article_id, check.kind, new_status, check.detail)


def reconcile(
    db: DatabaseManager, dual_write_since: datetime | None = None
) -> ReconciliationSummary:
    """Compare every article's legacy publication/audit metadata against the
    backfilled lifecycle tables. Read-only: never modifies any row.

    ``dual_write_since``: optional cutover marker (Plan 060 / Phase 3c). When
    given, every "missing" check is reclassified as "missing_pre_dualwrite"
    or "missing_post_dualwrite" based on the article's ``collected_date``.
    Omitting it (the default) reproduces this function's exact pre-Phase-3c
    output shape.
    """
    summary = ReconciliationSummary()
    with db.get_session() as session:
        articles = session.query(Article).all()
        for article in articles:
            metadata = article.article_metadata or {}
            publication = metadata.get("publication")
            audit = metadata.get("audit")
            if publication:
                check = _check_publication(db.lifecycle, article, publication)
                summary.checks.append(
                    _split_missing_status(check, article, dual_write_since)
                )
            if audit:
                check = _check_audit(db.lifecycle, article, audit)
                summary.checks.append(
                    _split_missing_status(check, article, dual_write_since)
                )
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
    parser.add_argument(
        "--dual-write-since",
        default=None,
        metavar="ISO_DATE",
        help=(
            "Plan 060 / Phase 3c cutover marker (e.g. this phase's merge "
            "date, ISO 8601). When given, 'missing' splits into "
            "'missing_pre_dualwrite' (article collected before this date — "
            "the known, routine pre-dual-write backfill gap) and "
            "'missing_post_dualwrite' (collected on/after — dual-write "
            "should have created the row live; a real failure). Omit to "
            "keep today's single 'missing' bucket."
        ),
    )
    args = parser.parse_args()

    dual_write_since: datetime | None = None
    if args.dual_write_since:
        dual_write_since = datetime.fromisoformat(args.dual_write_since)
        if dual_write_since.tzinfo is None:
            dual_write_since = dual_write_since.replace(tzinfo=timezone.utc)

    db = DatabaseManager()
    try:
        summary = reconcile(db, dual_write_since=dual_write_since)
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
