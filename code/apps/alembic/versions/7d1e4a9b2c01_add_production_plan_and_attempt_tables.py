"""add_production_plan_and_attempt_tables

Revision ID: 7d1e4a9b2c01
Revises: 3c2a9f7b6d11
Create Date: 2026-03-03 22:10:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "7d1e4a9b2c01"
down_revision: Union[str, Sequence[str], None] = "3c2a9f7b6d11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _standard_columns() -> list[sa.Column]:
    return [
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
    ]


def _create_standard_indexes(table_name: str) -> None:
    op.create_index(f"ix_{table_name}_tenant_id", table_name, ["tenant_id"])
    op.create_index(f"ix_{table_name}_project_id", table_name, ["project_id"])
    op.create_index(f"ix_{table_name}_deleted_at", table_name, ["deleted_at"])
    op.create_index(f"ix_{table_name}_created_at", table_name, ["created_at"])


def upgrade() -> None:
    op.create_table(
        "production_plan_versions",
        *_standard_columns(),
        sa.Column("novel_id", sa.String(64), nullable=False),
        sa.Column("chapter_id", sa.String(64), nullable=False),
        sa.Column("script_source", sa.String(24), nullable=False, server_default="original"),
        sa.Column("script_version_ref", sa.String(64), nullable=True),
        sa.Column("translation_project_id", sa.String(64), nullable=True),
        sa.Column("plan_version_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("plan_schema_version", sa.String(16), nullable=False, server_default="1.0"),
        sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("total_duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("plan_json", postgresql.JSONB(), nullable=True),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chapter_id"], ["chapters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["translation_project_id"], ["translation_projects.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("tenant_id", "project_id", "chapter_id", "plan_version_no", name="uq_ppv_scope_chapter_version"),
    )
    _create_standard_indexes("production_plan_versions")
    op.create_index("ix_ppv_scope_chapter", "production_plan_versions", ["tenant_id", "project_id", "chapter_id"])
    op.create_index(
        "ix_ppv_scope_translation_project",
        "production_plan_versions",
        ["tenant_id", "project_id", "translation_project_id"],
    )
    op.create_index("ix_ppv_scope_status", "production_plan_versions", ["tenant_id", "project_id", "status"])

    op.create_table(
        "production_plan_units",
        *_standard_columns(),
        sa.Column("plan_version_id", sa.String(64), nullable=False),
        sa.Column("track_type", sa.String(32), nullable=False),
        sa.Column("unit_ref_id", sa.String(64), nullable=False),
        sa.Column("unit_kind", sa.String(32), nullable=False),
        sa.Column("order_no", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("planned_start_ms", sa.Integer(), nullable=True),
        sa.Column("planned_end_ms", sa.Integer(), nullable=True),
        sa.Column("payload_json", postgresql.JSONB(), nullable=True),
        sa.Column("dependency_json", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="ready"),
        sa.ForeignKeyConstraint(["plan_version_id"], ["production_plan_versions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "tenant_id",
            "project_id",
            "plan_version_id",
            "track_type",
            "unit_ref_id",
            name="uq_ppu_scope_plan_track_unit",
        ),
    )
    _create_standard_indexes("production_plan_units")
    op.create_index(
        "ix_ppu_scope_plan_track_order",
        "production_plan_units",
        ["tenant_id", "project_id", "plan_version_id", "track_type", "order_no"],
    )
    op.create_index("ix_ppu_scope_status", "production_plan_units", ["tenant_id", "project_id", "status"])

    op.create_table(
        "track_unit_attempts",
        *_standard_columns(),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("track_run_id", sa.String(64), nullable=False),
        sa.Column("track_unit_id", sa.String(64), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("trigger_type", sa.String(24), nullable=False, server_default="run_all"),
        sa.Column("patch_json", postgresql.JSONB(), nullable=True),
        sa.Column("job_id", sa.String(64), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="queued"),
        sa.Column("artifact_id", sa.String(64), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["render_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["track_run_id"], ["track_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["track_unit_id"], ["track_units.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("tenant_id", "project_id", "track_unit_id", "attempt_no", name="uq_tua_scope_unit_attempt"),
    )
    _create_standard_indexes("track_unit_attempts")
    op.create_index(
        "ix_tua_scope_run_track_status",
        "track_unit_attempts",
        ["tenant_id", "project_id", "run_id", "track_run_id", "status"],
    )
    op.create_index("ix_tua_scope_job", "track_unit_attempts", ["tenant_id", "project_id", "job_id"])

    op.create_table(
        "artifact_lineage_index",
        *_standard_columns(),
        sa.Column("artifact_id", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=True),
        sa.Column("track_run_id", sa.String(64), nullable=True),
        sa.Column("track_unit_id", sa.String(64), nullable=True),
        sa.Column("novel_id", sa.String(64), nullable=True),
        sa.Column("chapter_id", sa.String(64), nullable=True),
        sa.Column("source_language", sa.String(16), nullable=True),
        sa.Column("target_language", sa.String(16), nullable=True),
        sa.Column("culture_pack_id", sa.String(64), nullable=True),
        sa.Column("world_pack_version", sa.String(64), nullable=True),
        sa.Column("track_type", sa.String(32), nullable=True),
        sa.Column("unit_ref_id", sa.String(64), nullable=True),
        sa.Column("canonical_path", sa.String(1024), nullable=True),
        sa.Column("model_profile_id", sa.String(64), nullable=True),
        sa.Column("extra_meta_json", postgresql.JSONB(), nullable=True),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["render_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["track_run_id"], ["track_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["track_unit_id"], ["track_units.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["chapter_id"], ["chapters.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["model_profile_id"], ["model_profiles.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("tenant_id", "project_id", "artifact_id", name="uq_ali_scope_artifact"),
    )
    _create_standard_indexes("artifact_lineage_index")
    op.create_index(
        "ix_ali_scope_run_track_unit",
        "artifact_lineage_index",
        ["tenant_id", "project_id", "run_id", "track_type", "unit_ref_id"],
    )
    op.create_index(
        "ix_ali_scope_chapter_track",
        "artifact_lineage_index",
        ["tenant_id", "project_id", "chapter_id", "track_type"],
    )
    op.create_index(
        "ix_ali_scope_lang_culture",
        "artifact_lineage_index",
        ["tenant_id", "project_id", "target_language", "culture_pack_id"],
    )


def downgrade() -> None:
    op.drop_table("artifact_lineage_index")
    op.drop_table("track_unit_attempts")
    op.drop_table("production_plan_units")
    op.drop_table("production_plan_versions")
