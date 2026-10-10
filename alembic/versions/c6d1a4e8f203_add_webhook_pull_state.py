"""add_webhook_pull_state

Revision ID: c6d1a4e8f203
Revises: f2a9c1d4e6b7
Create Date: 2026-10-09 00:00:00.000000

ADR-0011: persist the remote receipt cursor and locally staged retry queue.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "c6d1a4e8f203"
down_revision: Union[str, Sequence[str], None] = "f2a9c1d4e6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STATUS_CHECK = "status IN ('received', 'processing', 'processed', 'failed')"


def _table_exists(table_name: str) -> bool:
    return table_name in set(inspect(op.get_bind()).get_table_names())


def _ensure_cursor_table() -> None:
    if _table_exists("webhook_pull_cursors"):
        return
    op.create_table(
        "webhook_pull_cursors",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("endpoint_key", sa.String(length=500), nullable=False),
        sa.Column("after_id", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def _ensure_receipt_table() -> None:
    if _table_exists("webhook_pull_receipts"):
        return
    op.create_table(
        "webhook_pull_receipts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("endpoint_key", sa.String(length=500), nullable=False),
        sa.Column("remote_id", sa.Integer(), nullable=False),
        sa.Column("delivery_key", sa.String(length=200), nullable=True),
        sa.Column("event_type", sa.String(length=50), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_until", sa.Float(), nullable=True),
        sa.Column("lease_token", sa.String(length=32), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(_STATUS_CHECK, name="ck_webhook_pull_receipts_status"),
        sa.UniqueConstraint(
            "endpoint_key", "remote_id", name="uq_webhook_pull_receipts_source_id"
        ),
    )


def _ensure_index(
    table_name: str,
    index_name: str,
    columns: list[str],
    *,
    unique: bool = False,
) -> None:
    inspector = inspect(op.get_bind())
    indexes = {index["name"] for index in inspector.get_indexes(table_name)}
    if index_name not in indexes:
        op.create_index(index_name, table_name, columns, unique=unique)


def upgrade() -> None:
    # create_all() precedes Alembic in the existing app lifecycle; each object
    # remains safe to create when a database is fresh or partially initialized.
    _ensure_cursor_table()
    _ensure_index(
        "webhook_pull_cursors",
        "uq_webhook_pull_cursors_endpoint",
        ["endpoint_key"],
        unique=True,
    )
    _ensure_receipt_table()
    _ensure_index(
        "webhook_pull_receipts",
        "ix_webhook_pull_receipts_pending",
        ["endpoint_key", "status", "last_attempt_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_webhook_pull_receipts_pending", table_name="webhook_pull_receipts"
    )
    op.drop_table("webhook_pull_receipts")
    op.drop_index("uq_webhook_pull_cursors_endpoint", table_name="webhook_pull_cursors")
    op.drop_table("webhook_pull_cursors")
