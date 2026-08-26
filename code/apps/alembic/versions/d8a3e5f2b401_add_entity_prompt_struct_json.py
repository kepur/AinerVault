"""add_entity_prompt_struct_json

Revision ID: d8a3e5f2b401
Revises: c7f2d4a1b390
Create Date: 2026-04-02 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d8a3e5f2b401"
down_revision: Union[str, Sequence[str], None] = "c7f2d4a1b390"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "entities",
        sa.Column(
            "prompt_struct_json",
            postgresql.JSONB(),
            nullable=True,
            comment="结构化提示词 {positive_zh, negative_zh, positive_en, negative_en}",
        ),
    )


def downgrade() -> None:
    op.drop_column("entities", "prompt_struct_json")
