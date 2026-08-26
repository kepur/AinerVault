"""add_entity_prompt_variants

Revision ID: f6b1d2e3a4c5
Revises: c7f2d4a1b390
Create Date: 2026-04-04 10:30:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f6b1d2e3a4c5"
down_revision: Union[str, Sequence[str], None] = "c7f2d4a1b390"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "entity_prompt_variants",
        sa.Column("novel_id", sa.String(), nullable=False),
        sa.Column("entity_id", sa.String(), nullable=False),
        sa.Column("culture_pack_id", sa.String(length=64), nullable=False),
        sa.Column("anchor_prompt", sa.Text(), nullable=True),
        sa.Column(
            "prompt_struct_json",
            postgresql.JSONB(),
            nullable=True,
            comment="文化包变体提示词 {positive_zh, negative_zh, positive_en, negative_en}",
        ),
        sa.Column("source", sa.String(length=32), nullable=True),
        sa.Column("meta_json", postgresql.JSONB(), nullable=True),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=False),
        sa.Column("trace_id", sa.String(length=64), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "entity_id",
            "culture_pack_id",
            name="uq_entity_prompt_variants_scope_entity_pack",
        ),
    )
    op.create_index(
        "ix_entity_prompt_variants_scope_novel",
        "entity_prompt_variants",
        ["tenant_id", "project_id", "novel_id"],
        unique=False,
    )
    op.create_index(
        "ix_entity_prompt_variants_scope_entity",
        "entity_prompt_variants",
        ["tenant_id", "project_id", "entity_id"],
        unique=False,
    )
    op.create_index(
        "ix_entity_prompt_variants_scope_pack",
        "entity_prompt_variants",
        ["tenant_id", "project_id", "culture_pack_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_entity_prompt_variants_scope_pack", table_name="entity_prompt_variants")
    op.drop_index("ix_entity_prompt_variants_scope_entity", table_name="entity_prompt_variants")
    op.drop_index("ix_entity_prompt_variants_scope_novel", table_name="entity_prompt_variants")
    op.drop_table("entity_prompt_variants")
