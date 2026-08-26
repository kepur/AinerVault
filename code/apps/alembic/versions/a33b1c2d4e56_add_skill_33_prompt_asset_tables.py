"""add_skill_33_prompt_asset_tables

Revision ID: a33b1c2d4e56
Revises: bdcf270022c1
Create Date: 2026-04-02 16:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a33b1c2d4e56"
down_revision: Union[str, Sequence[str], None] = "bdcf270022c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── semantic_assets ────────────────────────────────────────────
    op.create_table(
        "semantic_assets",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("project_id", sa.String(64), nullable=False, index=True),
        sa.Column("novel_id", sa.String(64), sa.ForeignKey("novels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_id", sa.String(64), sa.ForeignKey("entities.id", ondelete="SET NULL"), nullable=True),
        sa.Column("asset_type", sa.String(32), nullable=False),
        sa.Column("canonical_name", sa.String(256), nullable=False),
        sa.Column("aliases_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("tags_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("structured_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("prompt_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("negative_prompt_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("version", sa.String(32), nullable=False, server_default="v1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("meta_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # StandardColumnsMixin fields
        sa.Column("trace_id", sa.String(128), nullable=True, index=True),
        sa.Column("correlation_id", sa.String(128), nullable=True, index=True),
        sa.Column("idempotency_key", sa.String(256), nullable=True, index=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("updated_by", sa.String(64), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True, index=True),
        sa.Column("error_message", sa.String(1024), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.UniqueConstraint(
            "tenant_id", "project_id", "novel_id", "asset_type", "canonical_name",
            name="uq_semantic_assets_scope_type_name",
        ),
    )
    op.create_index("ix_semantic_assets_scope_novel", "semantic_assets", ["tenant_id", "project_id", "novel_id"])
    op.create_index("ix_semantic_assets_scope_entity", "semantic_assets", ["tenant_id", "project_id", "entity_id"])
    op.create_index("ix_semantic_assets_scope_type", "semantic_assets", ["tenant_id", "project_id", "asset_type"])

    # ── character_stage_profiles ───────────────────────────────────
    op.create_table(
        "character_stage_profiles",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("project_id", sa.String(64), nullable=False, index=True),
        sa.Column("novel_id", sa.String(64), sa.ForeignKey("novels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_id", sa.String(64), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stage_name", sa.String(128), nullable=False),
        sa.Column("chapter_start", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("chapter_end", sa.Integer(), nullable=True),
        sa.Column("appearance_override_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("temperament_override_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("default_costume_asset_id", sa.String(64), sa.ForeignKey("semantic_assets.id", ondelete="SET NULL"), nullable=True),
        sa.Column("default_prop_asset_ids_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("emotional_baseline_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status_tags_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("meta_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # StandardColumnsMixin fields
        sa.Column("version", sa.String(32), nullable=False, server_default="v1"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("trace_id", sa.String(128), nullable=True, index=True),
        sa.Column("correlation_id", sa.String(128), nullable=True, index=True),
        sa.Column("idempotency_key", sa.String(256), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("updated_by", sa.String(64), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True, index=True),
        sa.Column("error_message", sa.String(1024), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.UniqueConstraint(
            "tenant_id", "project_id", "entity_id", "stage_name",
            name="uq_character_stage_profiles_scope_stage",
        ),
    )
    op.create_index("ix_character_stage_profiles_scope_entity", "character_stage_profiles", ["tenant_id", "project_id", "entity_id"])
    op.create_index("ix_character_stage_profiles_scope_novel", "character_stage_profiles", ["tenant_id", "project_id", "novel_id"])

    # ── prompt_snapshots (before shot_asset_bindings since it FK references) ──
    op.create_table(
        "prompt_snapshots",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("project_id", sa.String(64), nullable=False, index=True),
        sa.Column("run_id", sa.String(64), sa.ForeignKey("render_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("chapter_id", sa.String(64), sa.ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scene_id", sa.String(64), sa.ForeignKey("scenes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("shot_id", sa.String(64), sa.ForeignKey("shots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_id", sa.String(64), sa.ForeignKey("entities.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_type", sa.String(32), nullable=False, server_default="auto"),
        sa.Column("source_id", sa.String(64), nullable=True),
        sa.Column("merged_prompt_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("merged_negative_prompt_text", sa.Text(), nullable=True),
        sa.Column("merged_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("generation_params_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("consistency_hash", sa.String(128), nullable=True),
        sa.Column("regenerate_parent_snapshot_id", sa.String(64), sa.ForeignKey("prompt_snapshots.id", ondelete="SET NULL"), nullable=True),
        sa.Column("meta_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # StandardColumnsMixin fields
        sa.Column("version", sa.String(32), nullable=False, server_default="v1"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("trace_id", sa.String(128), nullable=True, index=True),
        sa.Column("correlation_id", sa.String(128), nullable=True, index=True),
        sa.Column("idempotency_key", sa.String(256), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("updated_by", sa.String(64), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True, index=True),
        sa.Column("error_message", sa.String(1024), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.create_index("ix_prompt_snapshots_scope_shot", "prompt_snapshots", ["tenant_id", "project_id", "shot_id"])
    op.create_index("ix_prompt_snapshots_scope_entity", "prompt_snapshots", ["tenant_id", "project_id", "entity_id"])
    op.create_index("ix_prompt_snapshots_scope_run", "prompt_snapshots", ["tenant_id", "project_id", "run_id"])
    op.create_index("ix_prompt_snapshots_scope_hash", "prompt_snapshots", ["consistency_hash"])

    # ── shot_asset_bindings ────────────────────────────────────────
    op.create_table(
        "shot_asset_bindings",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("project_id", sa.String(64), nullable=False, index=True),
        sa.Column("run_id", sa.String(64), sa.ForeignKey("render_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("chapter_id", sa.String(64), sa.ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scene_id", sa.String(64), sa.ForeignKey("scenes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("shot_id", sa.String(64), sa.ForeignKey("shots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_id", sa.String(64), sa.ForeignKey("entities.id", ondelete="SET NULL"), nullable=True),
        sa.Column("binding_role", sa.String(32), nullable=False, server_default="subject"),
        sa.Column("stage_profile_id", sa.String(64), sa.ForeignKey("character_stage_profiles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("selected_asset_ids_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("state_override_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("prompt_snapshot_id", sa.String(64), sa.ForeignKey("prompt_snapshots.id", ondelete="SET NULL"), nullable=True),
        sa.Column("meta_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # StandardColumnsMixin fields
        sa.Column("version", sa.String(32), nullable=False, server_default="v1"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("trace_id", sa.String(128), nullable=True, index=True),
        sa.Column("correlation_id", sa.String(128), nullable=True, index=True),
        sa.Column("idempotency_key", sa.String(256), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("updated_by", sa.String(64), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True, index=True),
        sa.Column("error_message", sa.String(1024), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.create_index("ix_shot_asset_bindings_scope_shot", "shot_asset_bindings", ["tenant_id", "project_id", "shot_id"])
    op.create_index("ix_shot_asset_bindings_scope_chapter", "shot_asset_bindings", ["tenant_id", "project_id", "chapter_id"])
    op.create_index("ix_shot_asset_bindings_scope_entity", "shot_asset_bindings", ["tenant_id", "project_id", "entity_id"])


def downgrade() -> None:
    op.drop_table("shot_asset_bindings")
    op.drop_table("prompt_snapshots")
    op.drop_table("character_stage_profiles")
    op.drop_table("semantic_assets")
