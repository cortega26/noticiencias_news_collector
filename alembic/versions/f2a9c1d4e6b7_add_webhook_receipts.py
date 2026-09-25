"""add_webhook_receipts

Revision ID: f2a9c1d4e6b7
Revises: e3f168a66d38
Create Date: 2026-09-25 00:00:00.000000

Plan 060 / Phase 5a: durable receipts for frontend webhook deliveries.

The serving webhook (`POST /api/v1/webhook/frontend`) currently processes the
callback inline and always answers 202; a crash loses the delivery and a
processing exception leaves no trace. This revision adds one additive table:

    webhook_receipts
      delivery_key  TEXT UNIQUE  -- id: or derived sha256 identity key
      status        received | processed | failed
      attempts, result, error, received_at, processed_at

Idempotent by design, same convention as ``effe4ec70d6d``: every
``create_table``/``create_index`` is guarded by an inspector check because
``DatabaseManager``'s ``create_all`` already builds the table from the current
models before Alembic ever runs against a fresh database. ``downgrade()`` is
complete (this revision only added one table).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "f2a9c1d4e6b7"
down_revision: Union[str, Sequence[str], None] = "e3f168a66d38"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Mirrors news_collector/storage/models.py exactly — keep both in sync.
WEBHOOK_RECEIPT_STATUS_VALUES = ("received", "processed", "failed")
_STATUS_CHECK = "status IN ({})".format(
    ", ".join(repr(v) for v in WEBHOOK_RECEIPT_STATUS_VALUES)
)


def _table_indexes(inspector, table_name: str, existing_tables: set) -> set:
    """Names of the indexes already on ``table_name``, empty if the table
    was just created in this same upgrade() call (nothing to reflect yet)."""
    if table_name not in existing_tables:
        return set()
    return {idx["name"] for idx in inspector.get_indexes(table_name)}


def _create_webhook_receipts(inspector, existing_tables: set) -> None:
    if "webhook_receipts" not in existing_tables:
        op.create_table(
            "webhook_receipts",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("delivery_key", sa.String(length=200), nullable=False),
            sa.Column("event_type", sa.String(length=50), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False),
            sa.Column("result", sa.JSON(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint(_STATUS_CHECK, name="ck_webhook_receipts_status"),
        )

    indexes = _table_indexes(inspector, "webhook_receipts", existing_tables)
    if "uq_webhook_receipts_delivery_key" not in indexes:
        op.create_index(
            "uq_webhook_receipts_delivery_key",
            "webhook_receipts",
            ["delivery_key"],
            unique=True,
        )
    if "ix_webhook_receipts_status_received_at" not in indexes:
        op.create_index(
            "ix_webhook_receipts_status_received_at",
            "webhook_receipts",
            ["status", "received_at"],
        )


def upgrade() -> None:
    """Upgrade schema: create ``webhook_receipts`` (additive only)."""
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())
    _create_webhook_receipts(inspector, existing_tables)


def downgrade() -> None:
    """Downgrade schema: drop ``webhook_receipts`` and nothing else."""
    bind = op.get_bind()
    inspector = inspect(bind)
    if "webhook_receipts" in set(inspector.get_table_names()):
        op.drop_table("webhook_receipts")
