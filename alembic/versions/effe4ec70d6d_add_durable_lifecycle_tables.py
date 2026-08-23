"""add_durable_lifecycle_tables

Revision ID: effe4ec70d6d
Revises: b61c2d3e4f50
Create Date: 2026-08-23 13:01:40.636555

Plan 060 / Phase 3a: five new, purely additive tables for durable
workflow/editorial/publication lineage — ``workflow_runs``,
``workflow_stage_attempts``, ``editorial_decisions``,
``publication_attempts``, ``publication_events``. Nothing reads or
writes these tables yet (that is Phase 3b); this revision only adds
schema.

Idempotent by design, same convention as 2447e261ecf4 and b61c2d3e4f50:
every ``create_table``/``create_index`` is guarded by an inspector
check, because ``DatabaseManager``'s ``create_all`` already builds
these tables from the current models before Alembic ever runs against
a fresh database (see ``tests/test_database_migrations.py``, several
tests bootstrap via ``DatabaseManager`` first). The same guard is
needed in ``downgrade()`` for the same reason — several tests
downgrade past this revision and back up to head within one run.

One helper function per table, same split-up-a-complex-upgrade()
convention as 2447e261ecf4_consolidate_refinery_schema.py's
``_upgrade_sources_table``/``_upgrade_articles_table``/``_create_indexes``.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "effe4ec70d6d"
down_revision: Union[str, Sequence[str], None] = "b61c2d3e4f50"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Mirrors news_collector/storage/models.py exactly — keep both in sync.
WORKFLOW_RUN_STATUS_VALUES = ("running", "completed", "failed", "cancelled")
WORKFLOW_RUN_ACTIVE_STATUS = "running"
WORKFLOW_STAGE_ATTEMPT_STATUS_VALUES = ("running", "completed", "failed", "skipped")
EDITORIAL_DECISION_TYPE_VALUES = ("auditor", "critic")
EDITORIAL_DECISION_OUTCOME_VALUES = ("pass", "fail", "accept", "reject")
PUBLICATION_ATTEMPT_STATE_VALUES = ("PR_CREATED", "REJECTED", "COMPLETED")
PUBLICATION_EVENT_TYPE_VALUES = ("pr_created", "check_passed", "deployed", "rejected")


def _check(column: str, values: tuple) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _table_indexes(inspector, table_name: str, existing_tables: set) -> set:
    """Names of the indexes already on ``table_name``, empty if the table
    was just created in this same upgrade() call (nothing to reflect yet)."""
    if table_name not in existing_tables:
        return set()
    return {idx["name"] for idx in inspector.get_indexes(table_name)}


def _create_workflow_runs(inspector, existing_tables: set) -> None:
    if "workflow_runs" not in existing_tables:
        op.create_table(
            "workflow_runs",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("run_type", sa.String(length=50), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("run_metadata", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                _check("status", WORKFLOW_RUN_STATUS_VALUES),
                name="ck_workflow_runs_status",
            ),
        )

    indexes = _table_indexes(inspector, "workflow_runs", existing_tables)
    if "ix_workflow_runs_run_type" not in indexes:
        op.create_index("ix_workflow_runs_run_type", "workflow_runs", ["run_type"])
    if "uq_workflow_runs_one_active_collection" not in indexes:
        # "One active collection": unique among rows satisfying the
        # predicate. run_type is constant ('collection') within that
        # filtered set, so uniqueness on it caps the set at one row.
        # Same sqlite_where pattern as uq_articles_content_hash in
        # 2447e261ecf4_consolidate_refinery_schema.py.
        op.create_index(
            "uq_workflow_runs_one_active_collection",
            "workflow_runs",
            ["run_type"],
            unique=True,
            sqlite_where=sa.text(
                f"run_type = 'collection' AND status = '{WORKFLOW_RUN_ACTIVE_STATUS}'"
            ),
        )


def _create_workflow_stage_attempts(inspector, existing_tables: set) -> None:
    if "workflow_stage_attempts" not in existing_tables:
        op.create_table(
            "workflow_stage_attempts",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("workflow_run_id", sa.Integer(), nullable=False),
            sa.Column("stage_name", sa.String(length=100), nullable=False),
            sa.Column("attempt_number", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("error_code", sa.String(length=100), nullable=True),
            sa.Column("details", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["workflow_run_id"], ["workflow_runs.id"], ondelete="RESTRICT"
            ),
            sa.CheckConstraint(
                _check("status", WORKFLOW_STAGE_ATTEMPT_STATUS_VALUES),
                name="ck_workflow_stage_attempts_status",
            ),
            sa.UniqueConstraint(
                "workflow_run_id",
                "stage_name",
                "attempt_number",
                name="uq_workflow_stage_attempts_run_stage_attempt",
            ),
        )

    indexes = _table_indexes(inspector, "workflow_stage_attempts", existing_tables)
    if "ix_workflow_stage_attempts_workflow_run_id" not in indexes:
        op.create_index(
            "ix_workflow_stage_attempts_workflow_run_id",
            "workflow_stage_attempts",
            ["workflow_run_id"],
        )
    if "ix_workflow_stage_attempts_stage_name" not in indexes:
        op.create_index(
            "ix_workflow_stage_attempts_stage_name",
            "workflow_stage_attempts",
            ["stage_name"],
        )


def _create_editorial_decisions(inspector, existing_tables: set) -> None:
    if "editorial_decisions" not in existing_tables:
        op.create_table(
            "editorial_decisions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            # Nullable: an editorial decision can occur before an Article
            # row exists (refinery_engine.py's _schedule_optional_audit /
            # _record_audit_status treats article_numeric_id as int | None
            # and no-ops on None rather than requiring it).
            sa.Column("article_id", sa.Integer(), nullable=True),
            sa.Column("decision_type", sa.String(length=50), nullable=False),
            sa.Column("outcome", sa.String(length=20), nullable=False),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("details", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["article_id"], ["articles.id"], ondelete="RESTRICT"
            ),
            sa.CheckConstraint(
                _check("decision_type", EDITORIAL_DECISION_TYPE_VALUES),
                name="ck_editorial_decisions_decision_type",
            ),
            sa.CheckConstraint(
                _check("outcome", EDITORIAL_DECISION_OUTCOME_VALUES),
                name="ck_editorial_decisions_outcome",
            ),
        )

    indexes = _table_indexes(inspector, "editorial_decisions", existing_tables)
    if "ix_editorial_decisions_article_id" not in indexes:
        op.create_index(
            "ix_editorial_decisions_article_id",
            "editorial_decisions",
            ["article_id"],
        )
    if "ix_editorial_decisions_decision_type" not in indexes:
        op.create_index(
            "ix_editorial_decisions_decision_type",
            "editorial_decisions",
            ["decision_type"],
        )


def _create_publication_attempts(inspector, existing_tables: set) -> None:
    if "publication_attempts" not in existing_tables:
        op.create_table(
            "publication_attempts",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("article_id", sa.Integer(), nullable=False),
            sa.Column("refinery_id", sa.String(length=100), nullable=False),
            sa.Column("attempt_number", sa.Integer(), nullable=False),
            sa.Column("state", sa.String(length=20), nullable=False),
            sa.Column("pr_url", sa.String(length=500), nullable=True),
            sa.Column("branch_name", sa.String(length=255), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("details", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["article_id"], ["articles.id"], ondelete="RESTRICT"
            ),
            sa.CheckConstraint(
                _check("state", PUBLICATION_ATTEMPT_STATE_VALUES),
                name="ck_publication_attempts_state",
            ),
        )

    indexes = _table_indexes(inspector, "publication_attempts", existing_tables)
    if "ix_publication_attempts_article_id" not in indexes:
        op.create_index(
            "ix_publication_attempts_article_id",
            "publication_attempts",
            ["article_id"],
        )
    if "ix_publication_attempts_refinery_id" not in indexes:
        op.create_index(
            "ix_publication_attempts_refinery_id",
            "publication_attempts",
            ["refinery_id"],
        )
    if "ix_publication_attempts_state" not in indexes:
        op.create_index(
            "ix_publication_attempts_state", "publication_attempts", ["state"]
        )


def _create_publication_events(inspector, existing_tables: set) -> None:
    if "publication_events" not in existing_tables:
        op.create_table(
            "publication_events",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("publication_attempt_id", sa.Integer(), nullable=False),
            sa.Column("event_type", sa.String(length=50), nullable=False),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("details", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["publication_attempt_id"],
                ["publication_attempts.id"],
                ondelete="RESTRICT",
            ),
            sa.CheckConstraint(
                _check("event_type", PUBLICATION_EVENT_TYPE_VALUES),
                name="ck_publication_events_event_type",
            ),
        )

    indexes = _table_indexes(inspector, "publication_events", existing_tables)
    if "ix_publication_events_publication_attempt_id" not in indexes:
        op.create_index(
            "ix_publication_events_publication_attempt_id",
            "publication_events",
            ["publication_attempt_id"],
        )
    if "ix_publication_events_event_type" not in indexes:
        op.create_index(
            "ix_publication_events_event_type",
            "publication_events",
            ["event_type"],
        )


def upgrade() -> None:
    """Upgrade schema: create the five new lineage tables (additive only)."""
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # Parents before children (workflow_runs before workflow_stage_attempts,
    # publication_attempts before publication_events) — matches FK direction.
    _create_workflow_runs(inspector, existing_tables)
    _create_workflow_stage_attempts(inspector, existing_tables)
    _create_editorial_decisions(inspector, existing_tables)
    _create_publication_attempts(inspector, existing_tables)
    _create_publication_events(inspector, existing_tables)


def downgrade() -> None:
    """Downgrade schema: drop the five new lineage tables, nothing else.

    Complete (not the abbreviated-on-purpose kind 2447e261ecf4 documents):
    this revision only ever added these five tables and their indexes, so
    dropping them fully reverses it. Dropped in FK-dependency order
    (children before parents). Table drops implicitly drop their indexes
    in SQLite, so no separate op.drop_index calls are needed.
    """
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "publication_events" in existing_tables:
        op.drop_table("publication_events")
    if "publication_attempts" in existing_tables:
        op.drop_table("publication_attempts")
    if "editorial_decisions" in existing_tables:
        op.drop_table("editorial_decisions")
    if "workflow_stage_attempts" in existing_tables:
        op.drop_table("workflow_stage_attempts")
    if "workflow_runs" in existing_tables:
        op.drop_table("workflow_runs")
