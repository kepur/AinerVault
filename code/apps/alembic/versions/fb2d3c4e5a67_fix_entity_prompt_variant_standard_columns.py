"""fix_entity_prompt_variant_standard_columns

Revision ID: fb2d3c4e5a67
Revises: fa9c1d2e3b44
Create Date: 2026-04-04 11:25:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "fb2d3c4e5a67"
down_revision: Union[str, Sequence[str], None] = "fa9c1d2e3b44"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "entity_prompt_variants",
        sa.Column("version", sa.String(length=32), nullable=False, server_default="v1"),
    )
    op.add_column(
        "entity_prompt_variants",
        sa.Column("created_by", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "entity_prompt_variants",
        sa.Column("updated_by", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "entity_prompt_variants",
        sa.Column("error_code", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "entity_prompt_variants",
        sa.Column("error_message", sa.String(length=1024), nullable=True),
    )
    op.add_column(
        "entity_prompt_variants",
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("entity_prompt_variants", "retry_count")
    op.drop_column("entity_prompt_variants", "error_message")
    op.drop_column("entity_prompt_variants", "error_code")
    op.drop_column("entity_prompt_variants", "updated_by")
    op.drop_column("entity_prompt_variants", "created_by")
    op.drop_column("entity_prompt_variants", "version")
