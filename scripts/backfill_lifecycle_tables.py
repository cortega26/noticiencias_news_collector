#!/usr/bin/env python3
"""One-shot backfill: legacy ``article_metadata`` publication/audit blobs ->
the durable lifecycle tables (Plan 060 / Phase 3b).

Reads every ``Article`` row's ``article_metadata["publication"]`` and
``["audit"]`` (when present) and inserts the corresponding
``publication_attempts``/``editorial_decisions`` row. Idempotent: safe to
re-run — a second run inserts nothing new (see idempotency note on
``LifecycleRepository.publication_attempt_exists``/``editorial_decision_exists``).

Does NOT touch ``workflow_runs``, ``workflow_stage_attempts``, or
``publication_events`` — no legacy data maps to those tables (see
plans/060/phase-3b-typed-repos/spec.md recon finding 5: this JSON state only
ever recorded an article's *current* status, never a run identity or an
event history to reconstruct).

Convention: a plain one-shot script, not an Alembic data migration — see
plans/060/phase-3b-typed-repos/spec.md Step 2. Alembic revisions in this
repo run automatically via ``alembic upgrade head`` / ``make migrate``;
wiring this backfill as a revision would make it fire on every routine
schema migration against whatever database that touches, which directly
contradicts this phase's own scope note that actually running the backfill
for real is a deliberate operator decision, made only after confirming
which database a real deployment actually writes to (recon finding 6: the
local dev database has never held real publication history and is not a
safe default target). A script the operator explicitly invokes keeps that
decision explicit; ``alembic upgrade head`` never touches it.

Usage:
    python scripts/backfill_lifecycle_tables.py
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Any

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from news_collector.storage.database import DatabaseManager  # noqa: E402
from news_collector.storage.lifecycle_repository import (  # noqa: E402
    LifecycleRepository,
    map_legacy_audit_outcome,
)
from news_collector.storage.models import (  # noqa: E402
    PUBLICATION_ATTEMPT_STATE_VALUES,
    Article,
)
from news_collector.utils.logger import get_logger  # noqa: E402

logger = get_logger().create_module_logger(__name__)

# Legacy `article_metadata["publication"]` keys that map to a dedicated
# `publication_attempts` column (or are consumed to derive one, like
# `refinery_id`/`updated_at`). Everything else is preserved verbatim in
# `details` — "preserve unknown legacy values rather than guessing."
_PUBLICATION_KNOWN_KEYS = {"state", "pr_url", "refinery_id", "updated_at"}

# Legacy `article_metadata["audit"]` keys that map to a dedicated
# `editorial_decisions` column. `attempts`/`timeout_seconds`/`model`/
# `endpoint` (and anything unrecognized) fall through to `details`.
_AUDIT_KNOWN_KEYS = {"state", "reason", "updated_at"}

_TERMINAL_PUBLICATION_STATES = {"REJECTED", "COMPLETED"}


@dataclass
class BackfillSummary:
    articles_processed: int = 0
    publication_rows_created: int = 0
    audit_rows_created: int = 0
    skipped_no_legacy_data: int = 0
    already_migrated_publication: int = 0
    already_migrated_audit: int = 0
    # Legacy audit state exists but isn't a completed decision (pending,
    # skipped, or an unrecognized value) — correctly not backfilled.
    audit_state_not_decision: int = 0
    # Legacy publication state exists but isn't one of the three known
    # values — logged and skipped rather than guessed at.
    publication_state_invalid: int = 0


def _parse_legacy_timestamp(value: Any, fallback: datetime) -> datetime:
    """Parse a legacy ``updated_at`` ISO string; fall back to ``fallback``.

    ``fallback`` must be the article's own ``collected_date`` (always
    present, never null) — never ``datetime.now()``. The backfill must be
    deterministic across re-runs so the reconciliation report's drift check
    stays stable; a "now" fallback would make every re-run produce a
    different value for rows backfilled from degraded legacy data.
    """
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            logger.warning("Unparseable legacy timestamp {!r}; using fallback.", value)
    return fallback


def _backfill_publication(
    lifecycle: LifecycleRepository,
    article: Article,
    publication: dict[str, Any],
    summary: BackfillSummary,
) -> None:
    # Same fallback `mark_article_published` itself already uses
    # (article_repository.py) when refinery_id predates that method's
    # current behavior — reconstructing a value the write path treats as
    # derivable from article_id, not a case of missing data to preserve.
    refinery_id = publication.get("refinery_id") or str(article.id)

    if lifecycle.publication_attempt_exists(article.id, refinery_id):
        summary.already_migrated_publication += 1
        return

    state = publication.get("state")
    if state not in PUBLICATION_ATTEMPT_STATE_VALUES:
        logger.warning(
            "Article {}: unrecognized legacy publication state {!r}; skipped.",
            article.id,
            state,
        )
        summary.publication_state_invalid += 1
        return

    started_at = _parse_legacy_timestamp(
        publication.get("updated_at"), article.collected_date
    )
    # We only ever have one legacy timestamp; a terminal state (rejected or
    # completed) means that timestamp is also when it finished. PR_CREATED
    # is still open, so finished_at stays null.
    finished_at = started_at if state in _TERMINAL_PUBLICATION_STATES else None

    details = {
        k: v for k, v in publication.items() if k not in _PUBLICATION_KNOWN_KEYS
    } or None

    lifecycle.record_publication_attempt(
        article.id,
        refinery_id=refinery_id,
        state=state,
        pr_url=publication.get("pr_url"),
        started_at=started_at,
        finished_at=finished_at,
        details=details,
        # Always attempt 1 for backfilled rows: legacy
        # article_metadata["publication"] only ever records the article's
        # *current* state, never a history of prior attempts — there is
        # exactly one legacy publication state per article, by
        # construction. Not COUNT(*) + 1 (see recon finding 5).
        attempt_number=1,
    )
    summary.publication_rows_created += 1


def _backfill_audit(
    lifecycle: LifecycleRepository,
    article: Article,
    audit: dict[str, Any],
    summary: BackfillSummary,
) -> None:
    if lifecycle.editorial_decision_exists(article.id, "auditor"):
        summary.already_migrated_audit += 1
        return

    state = audit.get("state")
    outcome = map_legacy_audit_outcome(state)
    if outcome is None:
        # Non-terminal (pending/skipped) or unrecognized — not a decision,
        # nothing to record. See lifecycle_repository.AUDIT_LEGACY_STATE_TO_OUTCOME.
        summary.audit_state_not_decision += 1
        return

    decided_at = _parse_legacy_timestamp(
        audit.get("updated_at"), article.collected_date
    )

    details: dict[str, Any] = {
        k: v for k, v in audit.items() if k not in _AUDIT_KNOWN_KEYS
    }
    # The raw legacy state is preserved even though it collapsed to a
    # coarser outcome value above ("audit_passed" -> "pass") — the outcome
    # column can't hold the finer-grained legacy vocabulary, but nothing is
    # dropped.
    details["legacy_state"] = state

    lifecycle.record_editorial_decision(
        article_id=article.id,
        decision_type="auditor",
        outcome=outcome,
        reason=audit.get("reason"),
        decided_at=decided_at,
        details=details,
    )
    summary.audit_rows_created += 1


def backfill(db: DatabaseManager) -> BackfillSummary:
    """Migrate every ``Article``'s legacy publication/audit metadata into
    the durable lifecycle tables. Idempotent — safe to re-run."""
    summary = BackfillSummary()
    with db.get_session() as session:
        articles = session.query(Article).all()
        for article in articles:
            summary.articles_processed += 1
            metadata = article.article_metadata or {}
            publication = metadata.get("publication")
            audit = metadata.get("audit")

            if not publication and not audit:
                summary.skipped_no_legacy_data += 1
                continue

            if publication:
                _backfill_publication(db.lifecycle, article, publication, summary)
            if audit:
                _backfill_audit(db.lifecycle, article, audit, summary)

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "One-shot backfill of legacy article_metadata publication/audit "
            "state into the durable lifecycle tables (Plan 060 / Phase 3b)."
        )
    )
    parser.parse_args()

    db = DatabaseManager()
    try:
        summary = backfill(db)
    finally:
        db.close()

    print(f"[backfill-lifecycle] articles_processed={summary.articles_processed}")
    print(
        f"[backfill-lifecycle] publication_rows_created={summary.publication_rows_created}"
    )
    print(f"[backfill-lifecycle] audit_rows_created={summary.audit_rows_created}")
    print(
        f"[backfill-lifecycle] skipped_no_legacy_data={summary.skipped_no_legacy_data}"
    )
    print(
        "[backfill-lifecycle] already_migrated_publication="
        f"{summary.already_migrated_publication}"
    )
    print(
        f"[backfill-lifecycle] already_migrated_audit={summary.already_migrated_audit}"
    )
    print(
        f"[backfill-lifecycle] audit_state_not_decision={summary.audit_state_not_decision}"
    )
    print(
        "[backfill-lifecycle] publication_state_invalid="
        f"{summary.publication_state_invalid}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
