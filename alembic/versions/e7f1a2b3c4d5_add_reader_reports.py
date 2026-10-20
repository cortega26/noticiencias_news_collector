"""add_reader_reports

Revision ID: e7f1a2b3c4d5
Revises: c6d1a4e8f203
Create Date: 2026-10-20 00:00:00.000000

Plan 185: durable reader-report intake with privacy-separated contact data.
Adds three additive tables:

    reader_reports          -- report body + server-resolved identity
    reader_report_contacts  -- one private email row per report
    reader_report_decisions -- editorial decision/closure history

Idempotent by design, same convention as ``f2a9c1d4e6b7``/``c6d1a4e8f203``:
every ``create_table``/``create_index`` is guarded by an inspector check
because ``DatabaseManager``'s ``create_all`` already builds the tables from
the current models before Alembic runs against a fresh database. ``downgrade``
is complete — this revision only added these three tables.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "e7f1a2b3c4d5"
down_revision: Union[str, Sequence[str], None] = "c6d1a4e8f203"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Mirrors news_collector/storage/models.py exactly — keep both in sync.
READER_REPORT_STATUS_VALUES = (
    "new",
    "triaged",
    "accepted",
    "rejected",
    "duplicate",
    "no_action",
)
READER_RESOLUTION_STATUS_VALUES = ("unresolved", "resolved", "ambiguous")
READER_DECISION_VALUES = ("accepted", "rejected", "duplicate", "no_action")

_STATUS_CHECK = "status IN ({})".format(
    ", ".join(repr(value) for value in READER_REPORT_STATUS_VALUES)
)
_RESOLUTION_STATUS_CHECK = "resolution_status IN ({})".format(
    ", ".join(repr(value) for value in READER_RESOLUTION_STATUS_VALUES)
)
_DECISION_CHECK = "decision IN ({})".format(
    ", ".join(repr(value) for value in READER_DECISION_VALUES)
)


def _table_names() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _index_names(table_name: str) -> set[str]:
    return {index["name"] for index in inspect(op.get_bind()).get_indexes(table_name)}


def _create_reader_reports() -> None:
    if "reader_reports" in _table_names():
        return
    op.create_table(
        "reader_reports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("problem_type", sa.String(length=40), nullable=False),
        sa.Column("article_url", sa.String(length=2000), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("content_snippet", sa.Text(), nullable=True),
        sa.Column("evidence_url", sa.String(length=2000), nullable=True),
        sa.Column("tech_browser", sa.String(length=200), nullable=True),
        sa.Column("tech_os", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("resolution_status", sa.String(length=20), nullable=False),
        sa.Column("resolved_refinery_id", sa.String(length=100), nullable=True),
        sa.Column("resolved_content_sha256", sa.String(length=64), nullable=True),
        sa.Column("resolution_reason", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("contact_purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(_STATUS_CHECK, name="ck_reader_reports_status"),
        sa.CheckConstraint(
            _RESOLUTION_STATUS_CHECK,
            name="ck_reader_reports_resolution_status",
        ),
    )


def _create_reader_report_contacts() -> None:
    if "reader_report_contacts" in _table_names():
        return
    op.create_table(
        "reader_report_contacts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("report_id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["reader_reports.id"],
            ondelete="CASCADE",
        ),
    )


def _create_reader_report_decisions() -> None:
    if "reader_report_decisions" in _table_names():
        return
    op.create_table(
        "reader_report_decisions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("report_id", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("actor", sa.String(length=200), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("corrected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("correction_summary", sa.Text(), nullable=True),
        sa.Column("publication_ref", sa.String(length=200), nullable=True),
        sa.Column("deploy_evidence", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["reader_reports.id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            _DECISION_CHECK,
            name="ck_reader_report_decisions_decision",
        ),
    )


def _ensure_index(
    table_name: str,
    index_name: str,
    columns: list[str],
    *,
    unique: bool = False,
) -> None:
    if index_name in _index_names(table_name):
        return
    op.create_index(index_name, table_name, columns, unique=unique)


def upgrade() -> None:
    """Upgrade schema: create the three reader-report tables (additive only)."""
    _create_reader_reports()
    _ensure_index(
        "reader_reports",
        "uq_reader_reports_idempotency_key",
        ["idempotency_key"],
        unique=True,
    )
    _ensure_index("reader_reports", "ix_reader_reports_status", ["status"])
    _ensure_index(
        "reader_reports",
        "ix_reader_reports_resolution_status",
        ["resolution_status"],
    )
    _ensure_index(
        "reader_reports",
        "ix_reader_reports_resolved_refinery_id",
        ["resolved_refinery_id"],
    )

    _create_reader_report_contacts()
    _ensure_index(
        "reader_report_contacts",
        "uq_reader_report_contacts_report_id",
        ["report_id"],
        unique=True,
    )

    _create_reader_report_decisions()
    _ensure_index(
        "reader_report_decisions",
        "ix_reader_report_decisions_report_id",
        ["report_id"],
    )


def downgrade() -> None:
    """Downgrade schema: drop only the three tables this revision added."""
    tables = _table_names()
    if "reader_report_decisions" in tables:
        op.drop_table("reader_report_decisions")
    if "reader_report_contacts" in tables:
        op.drop_table("reader_report_contacts")
    if "reader_reports" in tables:
        op.drop_table("reader_reports")
