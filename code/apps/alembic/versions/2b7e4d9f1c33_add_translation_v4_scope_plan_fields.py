"""add_translation_v4_scope_plan_fields

Revision ID: 2b7e4d9f1c33
Revises: 1a9d4c7e8b10
Create Date: 2026-03-01 18:20:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "2b7e4d9f1c33"
down_revision: Union[str, Sequence[str], None] = "1a9d4c7e8b10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # translation_projects: V4 scope/culture/temporal/naming config
    op.add_column("translation_projects", sa.Column("scope_mode", sa.String(32), nullable=False, server_default="chapters_selected"))
    op.add_column("translation_projects", sa.Column("scope_payload_json", postgresql.JSONB(), nullable=True))
    op.add_column("translation_projects", sa.Column("granularity", sa.String(16), nullable=False, server_default="chapter"))
    op.add_column("translation_projects", sa.Column("batch_size", sa.Integer(), nullable=False, server_default="10"))
    op.add_column("translation_projects", sa.Column("max_cost", sa.Float(), nullable=True))
    op.add_column("translation_projects", sa.Column("max_tokens", sa.Integer(), nullable=True))
    op.add_column("translation_projects", sa.Column("run_policy", sa.String(16), nullable=False, server_default="manual"))
    op.add_column("translation_projects", sa.Column("culture_mode", sa.String(16), nullable=False, server_default="auto"))
    op.add_column("translation_projects", sa.Column("culture_packs_json", postgresql.JSONB(), nullable=True))
    op.add_column("translation_projects", sa.Column("temporal_enabled", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("translation_projects", sa.Column("temporal_layers_json", postgresql.JSONB(), nullable=True))
    op.add_column("translation_projects", sa.Column("temporal_detect_policy", sa.String(24), nullable=False, server_default="off"))
    op.add_column("translation_projects", sa.Column("naming_policy_by_lang_json", postgresql.JSONB(), nullable=True))
    op.add_column("translation_projects", sa.Column("auto_fill_missing_names", sa.Boolean(), nullable=False, server_default="false"))

    # entity_mappings: per-language lock semantics
    op.add_column("entity_mappings", sa.Column("locked_langs_json", postgresql.JSONB(), nullable=True))
    op.add_column("entity_mappings", sa.Column("naming_policy_by_lang_json", postgresql.JSONB(), nullable=True))

    # translation plan items table
    op.create_table(
        "translation_plan_items",
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
        sa.Column("translation_project_id", sa.String(64), nullable=False),
        sa.Column("scope_type", sa.String(16), nullable=False, server_default="chapter"),
        sa.Column("chapter_id", sa.String(64), nullable=True),
        sa.Column("scene_id", sa.String(64), nullable=True),
        sa.Column("segment_id", sa.String(64), nullable=True),
        sa.Column("order_no", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("item_status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_run_id", sa.String(64), nullable=True),
        sa.ForeignKeyConstraint(["translation_project_id"], ["translation_projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chapter_id"], ["chapters.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_tpi_project_status", "translation_plan_items", ["translation_project_id", "item_status"])
    op.create_index("ix_tpi_project_order", "translation_plan_items", ["translation_project_id", "order_no"])
    op.create_index("ix_translation_plan_items_tenant_id", "translation_plan_items", ["tenant_id"])
    op.create_index("ix_translation_plan_items_project_id", "translation_plan_items", ["project_id"])
    op.create_index("ix_translation_plan_items_deleted_at", "translation_plan_items", ["deleted_at"])
    op.create_index("ix_translation_plan_items_created_at", "translation_plan_items", ["created_at"])


def downgrade() -> None:
    op.drop_table("translation_plan_items")
    op.drop_column("entity_mappings", "naming_policy_by_lang_json")
    op.drop_column("entity_mappings", "locked_langs_json")

    op.drop_column("translation_projects", "auto_fill_missing_names")
    op.drop_column("translation_projects", "naming_policy_by_lang_json")
    op.drop_column("translation_projects", "temporal_detect_policy")
    op.drop_column("translation_projects", "temporal_layers_json")
    op.drop_column("translation_projects", "temporal_enabled")
    op.drop_column("translation_projects", "culture_packs_json")
    op.drop_column("translation_projects", "culture_mode")
    op.drop_column("translation_projects", "run_policy")
    op.drop_column("translation_projects", "max_tokens")
    op.drop_column("translation_projects", "max_cost")
    op.drop_column("translation_projects", "batch_size")
    op.drop_column("translation_projects", "granularity")
    op.drop_column("translation_projects", "scope_payload_json")
    op.drop_column("translation_projects", "scope_mode")
