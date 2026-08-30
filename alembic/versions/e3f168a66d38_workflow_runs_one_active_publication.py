"""workflow_runs_one_active_publication

Revision ID: e3f168a66d38
Revises: 84cf98a379c1
Create Date: 2026-08-29 00:00:00.000000

Plan 060 / Phase 4c: `PublicationRunWorkflow`
(`news_collector/logic/workflows/publication_run_workflow.py`) becomes a real
writer of `workflow_runs` for `run_type='publication'` — the Astro admin's
"Refine & Publish" action. It needs its own single-flight guard: exactly one
publication run may be queued/running at a time (the Refinery clones the
target repo into a shared dir and opens a PR — concurrent runs would corrupt
each other), independent of any collection run.

Adds one partial unique index, mirroring
`uq_workflow_runs_one_active_collection` exactly but scoped to
`run_type='publication'`:

    uq_workflow_runs_one_active_publication
      UNIQUE (run_type) WHERE run_type = 'publication'
                          AND status IN ('queued', 'running')

Purely additive — no columns, no constraint changes. `run_type` is already
free-form `String(50)` and `ck_workflow_runs_status` already allows all six
values (widened in `84cf98a379c1`), so nothing else moves.

Idempotent by design, same as every Phase 3/4 migration: `DatabaseManager`'s
`create_all` builds this index from the current `models.py` before Alembic
runs against a fresh DB, so `upgrade()` inspects current state first.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "e3f168a66d38"
down_revision: Union[str, Sequence[str], None] = "84cf98a379c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEX_NAME = "uq_workflow_runs_one_active_publication"
# Mirrors news_collector/storage/models.py's _WORKFLOW_RUN_QUEUEABLE_STATUS_CHECK.
_QUEUEABLE_PREDICATE = "run_type = 'publication' AND status IN ('queued', 'running')"


def _table_indexes(inspector) -> set:
    if "workflow_runs" not in inspector.get_table_names():
        return set()
    return {idx["name"] for idx in inspector.get_indexes("workflow_runs")}


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    if _INDEX_NAME not in _table_indexes(inspector):
        op.create_index(
            _INDEX_NAME,
            "workflow_runs",
            ["run_type"],
            unique=True,
            sqlite_where=sa.text(_QUEUEABLE_PREDICATE),
        )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    if _INDEX_NAME in _table_indexes(inspector):
        op.drop_index(_INDEX_NAME, table_name="workflow_runs")
