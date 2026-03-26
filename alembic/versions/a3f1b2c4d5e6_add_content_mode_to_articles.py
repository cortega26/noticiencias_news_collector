"""add content_mode to articles

Revision ID: a3f1b2c4d5e6
Revises: 2447e261ecf4
Create Date: 2026-03-26 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "a3f1b2c4d5e6"
down_revision: Union[str, Sequence[str], None] = "2447e261ecf4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("articles")}

    if "content_mode" not in columns:
        op.add_column("articles", sa.Column("content_mode", sa.String(20)))


def downgrade() -> None:
    op.drop_column("articles", "content_mode")
