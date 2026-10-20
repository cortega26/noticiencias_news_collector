"""add_reader_reports_submitted_at

Revision ID: d2e3f4a5b6c7
Revises: e7f1a2b3c4d5
Create Date: 2026-10-20 00:00:00.000000

Plan 186: reconciliation needs the reader's own submission timestamp on
the report row, distinct from ``created_at`` (reconciliation time). Adds
exactly ONE nullable column — ``reader_reports.submitted_at`` — on top of
the plan 185 head; nothing else in the schema changes. Guarded by an
inspector check so a database that already carries the column (fresh
``create_all`` from the current models) is a no-op; ``downgrade`` drops it.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "d2e3f4a5b6c7"
down_revision: Union[str, Sequence[str], None] = "e7f1a2b3c4d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "reader_reports"
COLUMN = "submitted_at"


def _column_names(table_name: str) -> set[str]:
    return {column["name"] for column in inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    """Upgrade schema: one nullable intake timestamp on reader_reports."""
    if COLUMN in _column_names(TABLE):
        return
    op.add_column(
        TABLE,
        sa.Column(COLUMN, sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema: drop only the column this revision added."""
    if COLUMN not in _column_names(TABLE):
        return
    op.drop_column(TABLE, COLUMN)
