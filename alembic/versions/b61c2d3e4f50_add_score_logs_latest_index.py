"""add score_logs latest index

Revision ID: b61c2d3e4f50
Revises: a54ba7f7dabb
Create Date: 2026-06-12 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect

revision: str = "b61c2d3e4f50"
down_revision: Union[str, Sequence[str], None] = "a54ba7f7dabb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = "idx_score_logs_article_latest"


def upgrade() -> None:
    inspector = inspect(op.get_bind())
    existing = {index["name"] for index in inspector.get_indexes("score_logs")}
    if INDEX_NAME not in existing:
        op.create_index(
            INDEX_NAME,
            "score_logs",
            ["article_id", "calculated_at"],
        )


def downgrade() -> None:
    inspector = inspect(op.get_bind())
    existing = {index["name"] for index in inspector.get_indexes("score_logs")}
    if INDEX_NAME in existing:
        op.drop_index(INDEX_NAME, table_name="score_logs")
