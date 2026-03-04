"""add_entity_localization_drift_columns

Revision ID: 1a9d4c7e8b10
Revises: f3a2b1c0d456
Create Date: 2026-03-01 17:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "1a9d4c7e8b10"
down_revision: Union[str, Sequence[str], None] = "f3a2b1c0d456"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "entity_mappings",
        sa.Column("localization_candidates_json", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "entity_mappings",
        sa.Column("drift_score", sa.Float(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("entity_mappings", "drift_score")
    op.drop_column("entity_mappings", "localization_candidates_json")
