"""add_novel_team_json

Revision ID: a3c7d1e9f452
Revises: 0f2b6c9b0c7f
Create Date: 2026-02-28 10:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a3c7d1e9f452"
down_revision: Union[str, Sequence[str], None] = "0f2b6c9b0c7f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("novels", sa.Column("team_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column("novels", "team_json")
