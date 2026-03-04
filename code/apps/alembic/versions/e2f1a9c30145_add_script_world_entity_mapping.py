"""add_script_world_entity_mapping

Revision ID: e2f1a9c30145
Revises: d6a4c3b1e720
Create Date: 2026-03-01 10:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e2f1a9c30145"
down_revision: Union[str, Sequence[str], None] = "d6a4c3b1e720"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. chapters 表新增两列 JSONB ──────────────────────────────────────────
    op.add_column("chapters", sa.Column("script_json", postgresql.JSONB(), nullable=True))
    op.add_column("chapters", sa.Column("world_model_json", postgresql.JSONB(), nullable=True))

    # ── 2. 新枚举 ─────────────────────────────────────────────────────────────
    op.execute(
        "CREATE TYPE entitymappingtype AS ENUM ('character','location','prop','style','event')"
    )
    op.execute(
        "CREATE TYPE entitycontinuitystatus AS ENUM ('unbound','candidate','locked','drifted')"
    )

    # ── 3. entity_mappings 表 ─────────────────────────────────────────────────
    op.create_table(
        "entity_mappings",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("trace_id", sa.String(128), nullable=True),
        sa.Column("correlation_id", sa.String(128), nullable=True),
        sa.Column("idempotency_key", sa.String(256), nullable=True),
        sa.Column("version", sa.String(32), nullable=False, server_default="v1"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("updated_by", sa.String(64), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.String(1024), nullable=True),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("novel_id", sa.String(64), nullable=True),
        sa.Column(
            "entity_type",
            postgresql.ENUM(
                "character", "location", "prop", "style", "event",
                name="entitymappingtype",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column("canonical_name", sa.String(256), nullable=False),
        sa.Column("source_language", sa.String(16), nullable=False, server_default="zh-CN"),
        sa.Column("translations_json", postgresql.JSONB(), nullable=True),
        sa.Column("aliases_json", postgresql.JSONB(), nullable=True),
        sa.Column("culture_tags_json", postgresql.JSONB(), nullable=True),
        sa.Column("world_model_source", sa.String(128), nullable=True),
        sa.Column("anchor_asset_id", sa.String(128), nullable=True),
        sa.Column(
            "continuity_status",
            postgresql.ENUM(
                "unbound", "candidate", "locked", "drifted",
                name="entitycontinuitystatus",
                create_type=False,
            ),
            nullable=False,
            server_default="unbound",
        ),
        sa.Column("notes", sa.Text, nullable=True),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_em_novel", "entity_mappings", ["novel_id"])
    op.create_index("ix_em_status", "entity_mappings", ["continuity_status"])
    op.create_index("ix_em_deleted", "entity_mappings", ["deleted_at"])
    op.create_index("ix_em_tenant_id", "entity_mappings", ["tenant_id"])
    op.create_index("ix_em_project_id", "entity_mappings", ["project_id"])


def downgrade() -> None:
    op.drop_table("entity_mappings")
    op.execute("DROP TYPE IF EXISTS entitycontinuitystatus")
    op.execute("DROP TYPE IF EXISTS entitymappingtype")
    op.drop_column("chapters", "world_model_json")
    op.drop_column("chapters", "script_json")
