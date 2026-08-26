"""extend_workflow_runs_durable_dispatch

Revision ID: 84cf98a379c1
Revises: a4d9a4ba00aa
Create Date: 2026-08-26 12:46:51.816084

Plan 060 / Phase 4a: extends ``workflow_runs`` so it can become the actual
source of truth for admin collection runs (``serving/api.py``'s
``CollectionRunWorkflow``, this same phase). Adds five new nullable-or-safe
columns (``idempotency_key``, ``heartbeat_at``, ``updated_at``,
``error_code``, ``error_detail``), widens ``ck_workflow_runs_status`` to
six values, and widens ``uq_workflow_runs_one_active_collection``'s partial
predicate from ``status = 'running'`` to ``status IN ('queued', 'running')``.
Also adds a second partial unique index,
``uq_workflow_runs_idempotency_key_active``, for the idempotency-key
single-flight check. See ``plans/060/phase-4a-collection-run-workflow/spec.md``
Design §1.

Status vocabulary decision (spec.md's own STOP condition, resolved with the
operator 2026-08-26): rename ``'completed'`` -> ``'succeeded'`` rather than
add ``'succeeded'`` as a second synonym value. Repo-wide grep found no
reader of ``workflow_runs.status`` outside ``models.py``, the effe4ec70d6d
migration, and schema-only tests in ``tests/test_database_migrations.py``
(none of which ever write the literal ``'completed'``) — and a scratch copy
of the real dev DB (``data/news_v3.db``) showed zero ``workflow_runs`` rows
of any status, confirming nothing writes here yet (Phase 3a only added the
schema; this phase is the first real writer). The rename is therefore free
in practice; ``upgrade()`` still runs a defensive
``UPDATE ... SET status='succeeded' WHERE status='completed'`` before
touching the constraint, in case some other environment's copy differs from
what was inspected here — a no-op today, cheap insurance going forward.
``downgrade()`` mirrors this back and additive-only/no-data-loss-guards on
any row in a status the narrower five-value constraint cannot represent
(``'queued'`` or ``'interrupted'``), same irreversibility pattern
``a4d9a4ba00aa`` established for a widened CHECK constraint (the model to
follow per this repo's own convention — checked that file directly rather
than inventing a new guard shape).

Column adds use plain ``op.add_column``/``op.drop_column`` (SQLite supports
this directly, same as ``a54ba7f7dabb_add_blacklist_columns.py``) — only the
CHECK-constraint swap needs ``batch_alter_table`` (SQLite has no
``ALTER TABLE ... DROP/ADD CONSTRAINT`` for CHECK constraints; batch mode
recreates the table under the hood, same as ``a4d9a4ba00aa``). Indexes are
dropped/created directly (SQLite supports ``CREATE/DROP INDEX`` natively,
no batch needed), same as ``effe4ec70d6d``.

Idempotent by design, same reason as every prior Phase 3 migration:
``DatabaseManager``'s ``create_all`` already builds this schema from the
current (already-updated) ``models.py`` before Alembic ever runs against a
fresh database, so every step here inspects current state before acting
rather than assuming a particular starting point.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "84cf98a379c1"
down_revision: Union[str, Sequence[str], None] = "a4d9a4ba00aa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Mirrors news_collector/storage/models.py exactly — keep both in sync.
# This revision is the current owner of workflow_runs' status vocabulary
# (models.py's own comment says so), same role a4d9a4ba00aa plays for
# PUBLICATION_ATTEMPT_STATE_VALUES.
WORKFLOW_RUN_STATUS_VALUES = (
    "queued",
    "running",
    "succeeded",
    "failed",
    "cancelled",
    "interrupted",
)
_OLD_STATUS_VALUES = ("running", "completed", "failed", "cancelled")
WORKFLOW_RUN_ACTIVE_STATUS = "running"
WORKFLOW_RUN_QUEUEABLE_STATUSES = ("queued", WORKFLOW_RUN_ACTIVE_STATUS)
_STATUS_CONSTRAINT_NAME = "ck_workflow_runs_status"
_ACTIVE_INDEX_NAME = "uq_workflow_runs_one_active_collection"
_IDEMPOTENCY_INDEX_NAME = "uq_workflow_runs_idempotency_key_active"
# Statuses the narrower (pre-Phase-4a) five-value... four-value constraint
# cannot represent — downgrade() refuses to run if any row holds one of
# these, per this program's additive-only / no-data-loss rule.
_STATUSES_UNREPRESENTABLE_BY_OLD_CONSTRAINT = ("queued", "interrupted")
# Superset of old + new values, used as a *temporary* constraint while the
# 'completed'<->'succeeded' backfill UPDATE runs in either direction. Fixes
# a real bug an automated review caught: writing 'succeeded' while only the
# narrow old constraint is active (or 'completed' while only the narrow new
# one is active) violates that constraint and aborts the migration — this
# was invisible against the real dev DB's 0-row workflow_runs table, which
# is exactly why it needed a second pair of eyes, not just an empty-table
# round-trip test. Widen to this union first, backfill, then narrow to the
# real target — standard sequencing for a CHECK-constrained rename.
_UNION_STATUS_VALUES = tuple(
    dict.fromkeys(_OLD_STATUS_VALUES + WORKFLOW_RUN_STATUS_VALUES)
)


def _check(column: str, values: tuple) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _current_constraint_sql(inspector):
    """SQL text of ck_workflow_runs_status as it exists right now, or None
    if the constraint (or the table) isn't there at all."""
    for constraint in inspector.get_check_constraints("workflow_runs"):
        if constraint["name"] == _STATUS_CONSTRAINT_NAME:
            return constraint["sqltext"]
    return None


def _table_columns(inspector) -> set:
    return {col["name"] for col in inspector.get_columns("workflow_runs")}


def _table_indexes(inspector) -> set:
    return {idx["name"] for idx in inspector.get_indexes("workflow_runs")}


def upgrade() -> None:
    """Add durable-dispatch columns, widen the status vocabulary, widen the
    active-collection index, add the idempotency-key index."""
    bind = op.get_bind()
    inspector = inspect(bind)

    # --- 1. New columns ---
    # idempotency_key/heartbeat_at/error_code/error_detail are all nullable
    # with no default — plain ADD COLUMN is safe for those in SQLite
    # regardless of existing rows. updated_at is NOT NULL with a
    # non-constant default (CURRENT_TIMESTAMP): SQLite's plain
    # ALTER TABLE ... ADD COLUMN rejects that combination outright
    # ("Cannot add a column with non-constant default") the moment the
    # table has any existing row to backfill — invisible against the real
    # dev DB's 0-row workflow_runs table (same blind spot the backfill-
    # ordering fix above ran into), caught only by testing against a
    # seeded row. batch_alter_table recreates the table instead, which
    # SQLite evaluates CURRENT_TIMESTAMP against per existing row
    # correctly.
    columns = _table_columns(inspector)
    if "idempotency_key" not in columns:
        op.add_column(
            "workflow_runs",
            sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        )
    if "heartbeat_at" not in columns:
        op.add_column(
            "workflow_runs",
            sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "updated_at" not in columns:
        with op.batch_alter_table("workflow_runs", schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "updated_at",
                    sa.DateTime(timezone=True),
                    nullable=False,
                    server_default=sa.text("CURRENT_TIMESTAMP"),
                )
            )
    if "error_code" not in columns:
        op.add_column(
            "workflow_runs",
            sa.Column("error_code", sa.String(length=100), nullable=True),
        )
    if "error_detail" not in columns:
        op.add_column(
            "workflow_runs", sa.Column("error_detail", sa.Text(), nullable=True)
        )

    # --- 2. Backfill + widen the status CHECK constraint ---
    # Order matters: widen to the old+new UNION *before* backfilling, so the
    # backfill UPDATE's target value ('succeeded') is never rejected by a
    # still-narrow constraint. A prior version of this migration ran the
    # backfill first — safe only because the real dev DB it was tested
    # against had zero workflow_runs rows, so the UPDATE was a no-op that
    # never actually touched the constraint. Any environment with a real
    # legacy 'completed' row would have failed the upgrade outright.
    current_sql = _current_constraint_sql(inspector)
    if current_sql is None or "succeeded" not in current_sql:
        with op.batch_alter_table("workflow_runs", schema=None) as batch_op:
            batch_op.drop_constraint(_STATUS_CONSTRAINT_NAME, type_="check")
            batch_op.create_check_constraint(
                _STATUS_CONSTRAINT_NAME, _check("status", _UNION_STATUS_VALUES)
            )
        bind.execute(
            sa.text(
                "UPDATE workflow_runs SET status = 'succeeded' "
                "WHERE status = 'completed'"
            )
        )
        with op.batch_alter_table("workflow_runs", schema=None) as batch_op:
            batch_op.drop_constraint(_STATUS_CONSTRAINT_NAME, type_="check")
            batch_op.create_check_constraint(
                _STATUS_CONSTRAINT_NAME, _check("status", WORKFLOW_RUN_STATUS_VALUES)
            )

    # --- 3. Widen the active-collection partial unique index ---
    indexes = _table_indexes(inspector)
    queueable_check = _check("status", WORKFLOW_RUN_QUEUEABLE_STATUSES)
    if _ACTIVE_INDEX_NAME in indexes:
        op.drop_index(_ACTIVE_INDEX_NAME, table_name="workflow_runs")
    op.create_index(
        _ACTIVE_INDEX_NAME,
        "workflow_runs",
        ["run_type"],
        unique=True,
        sqlite_where=sa.text(f"run_type = 'collection' AND {queueable_check}"),
    )

    # --- 4. New idempotency-key partial unique index ---
    if _IDEMPOTENCY_INDEX_NAME not in indexes:
        op.create_index(
            _IDEMPOTENCY_INDEX_NAME,
            "workflow_runs",
            ["run_type", "idempotency_key"],
            unique=True,
            sqlite_where=sa.text(f"idempotency_key IS NOT NULL AND {queueable_check}"),
        )


def downgrade() -> None:
    """Reverse upgrade(): drop the new columns/index, narrow the status
    constraint and the active-collection index back to their pre-Phase-4a
    shape.

    Additive-only / no-data-loss: refuses to run if any row holds a status
    the narrower four-value constraint cannot represent (``'queued'`` or
    ``'interrupted'``), same guard shape ``a4d9a4ba00aa`` established.
    """
    bind = op.get_bind()
    inspector = inspect(bind)

    unrepresentable = _STATUSES_UNREPRESENTABLE_BY_OLD_CONSTRAINT
    blocking_count = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM workflow_runs WHERE status IN :statuses"
        ).bindparams(sa.bindparam("statuses", expanding=True)),
        {"statuses": list(unrepresentable)},
    ).scalar_one()
    if blocking_count:
        raise NotImplementedError(
            f"Cannot downgrade past 84cf98a379c1: {blocking_count} workflow_runs "
            f"row(s) are in a status ({', '.join(unrepresentable)}) the pre-Phase-4a "
            "four-value ck_workflow_runs_status constraint cannot represent. "
            "This program is additive-only / no-data-loss (see "
            "plans/060/phase-4a-collection-run-workflow/spec.md); resolve "
            "those rows to a representable status before downgrading."
        )

    indexes = _table_indexes(inspector)

    # --- Reverse step 4: drop the idempotency-key index ---
    if _IDEMPOTENCY_INDEX_NAME in indexes:
        op.drop_index(_IDEMPOTENCY_INDEX_NAME, table_name="workflow_runs")

    # --- Reverse step 3: narrow the active-collection index back to
    #     status = 'running' only ---
    if _ACTIVE_INDEX_NAME in indexes:
        op.drop_index(_ACTIVE_INDEX_NAME, table_name="workflow_runs")
    op.create_index(
        _ACTIVE_INDEX_NAME,
        "workflow_runs",
        ["run_type"],
        unique=True,
        sqlite_where=sa.text(
            f"run_type = 'collection' AND status = '{WORKFLOW_RUN_ACTIVE_STATUS}'"
        ),
    )

    # --- Reverse step 2: narrow the status constraint, un-rename 'succeeded' ---
    # Same widen-first ordering as upgrade()'s equivalent step, for the same
    # reason: the still-active new constraint doesn't include 'completed',
    # so writing it before widening to the union would violate the
    # constraint and abort the downgrade.
    current_sql = _current_constraint_sql(inspector)
    if current_sql is None or "succeeded" in current_sql:
        with op.batch_alter_table("workflow_runs", schema=None) as batch_op:
            batch_op.drop_constraint(_STATUS_CONSTRAINT_NAME, type_="check")
            batch_op.create_check_constraint(
                _STATUS_CONSTRAINT_NAME, _check("status", _UNION_STATUS_VALUES)
            )
        bind.execute(
            sa.text(
                "UPDATE workflow_runs SET status = 'completed' "
                "WHERE status = 'succeeded'"
            )
        )
        with op.batch_alter_table("workflow_runs", schema=None) as batch_op:
            batch_op.drop_constraint(_STATUS_CONSTRAINT_NAME, type_="check")
            batch_op.create_check_constraint(
                _STATUS_CONSTRAINT_NAME, _check("status", _OLD_STATUS_VALUES)
            )

    # --- Reverse step 1: drop the new columns ---
    columns = _table_columns(inspector)
    if "error_detail" in columns:
        op.drop_column("workflow_runs", "error_detail")
    if "error_code" in columns:
        op.drop_column("workflow_runs", "error_code")
    if "updated_at" in columns:
        op.drop_column("workflow_runs", "updated_at")
    if "heartbeat_at" in columns:
        op.drop_column("workflow_runs", "heartbeat_at")
    if "idempotency_key" in columns:
        op.drop_column("workflow_runs", "idempotency_key")
