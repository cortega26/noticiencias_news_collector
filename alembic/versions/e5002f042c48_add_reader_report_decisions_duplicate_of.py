"""add_reader_report_decisions_duplicate_of

Revision ID: e5002f042c48
Revises: d2e3f4a5b6c7
Create Date: 2026-10-20 00:00:00.000000

Plan 187: a ``duplicate`` decision must name the report it duplicates.
Adds exactly ONE nullable INTEGER column —
``reader_report_decisions.duplicate_of_report_id`` — on top of the plan
186 head; nothing else in the schema changes. Deliberately NO FK
constraint (and no cascade): decision rows are append-only audit records
that must outlive any deleted report, and cascade semantics are a
branching decision for a later plan. Referential integrity is enforced
by the repository's existence check before the row is written. Guarded
by an inspector check so a database that already carries the column
(fresh ``create_all`` from the current models) is a no-op; ``downgrade``
drops it.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "e5002f042c48"
down_revision: Union[str, Sequence[str], None] = "d2e3f4a5b6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "reader_report_decisions"
COLUMN = "duplicate_of_report_id"


def _column_names(table_name: str) -> set[str]:
    return {column["name"] for column in inspect(op.get_bind()).get_columns(table_name)}


def upgrade() -> None:
    """Upgrade schema: one nullable duplicate-reference column."""
    if COLUMN in _column_names(TABLE):
        return
    op.add_column(TABLE, sa.Column(COLUMN, sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema: drop only the column this revision added."""
    if COLUMN not in _column_names(TABLE):
        return
    op.drop_column(TABLE, COLUMN)
