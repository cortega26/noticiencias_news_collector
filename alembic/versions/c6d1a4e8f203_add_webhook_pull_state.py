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


def upgrade() -> None:
    # DatabaseManager.create_all() runs before Alembic in the existing app
    # lifecycle. Guard each object so fresh databases and partially initialized
    # deployments can safely advance to this revision.
    inspector = inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    if "webhook_pull_cursors" not in tables:
        op.create_table(
            "webhook_pull_cursors",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("endpoint_key", sa.String(length=500), nullable=False),
            sa.Column("after_id", sa.Integer(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    cursor_indexes = (
        {index["name"] for index in inspector.get_indexes("webhook_pull_cursors")}
        if "webhook_pull_cursors" in tables
        else set()
    )
    if "uq_webhook_pull_cursors_endpoint" not in cursor_indexes:
        op.create_index(
            "uq_webhook_pull_cursors_endpoint",
            "webhook_pull_cursors",
            ["endpoint_key"],
            unique=True,
        )

    if "webhook_pull_receipts" not in tables:
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
    receipt_indexes = (
        {index["name"] for index in inspector.get_indexes("webhook_pull_receipts")}
        if "webhook_pull_receipts" in tables
        else set()
    )
    if "ix_webhook_pull_receipts_pending" not in receipt_indexes:
        op.create_index(
            "ix_webhook_pull_receipts_pending",
            "webhook_pull_receipts",
            ["endpoint_key", "status", "last_attempt_at"],
        )


def downgrade() -> None:
    op.drop_index(
        "ix_webhook_pull_receipts_pending", table_name="webhook_pull_receipts"
    )
    op.drop_table("webhook_pull_receipts")
    op.drop_index("uq_webhook_pull_cursors_endpoint", table_name="webhook_pull_cursors")
    op.drop_table("webhook_pull_cursors")
