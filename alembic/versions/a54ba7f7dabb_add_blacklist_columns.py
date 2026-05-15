"""add blacklist columns to sources

Revision ID: a54ba7f7dabb
Revises: a3f1b2c4d5e6
Create Date: 2026-05-15 13:23:54.426663

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "a54ba7f7dabb"
down_revision: Union[str, Sequence[str], None] = "a3f1b2c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("sources")}

    if "blacklisted" not in columns:
        op.add_column(
            "sources",
            sa.Column("blacklisted", sa.Boolean(), nullable=True, server_default="0"),
        )
    if "blacklisted_at" not in columns:
        op.add_column(
            "sources",
            sa.Column("blacklisted_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "blacklist_reason" not in columns:
        op.add_column(
            "sources",
            sa.Column("blacklist_reason", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("sources", "blacklist_reason")
    op.drop_column("sources", "blacklisted_at")
    op.drop_column("sources", "blacklisted")
