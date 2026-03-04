"""add_track_run_and_track_unit

Revision ID: 3c2a9f7b6d11
Revises: 9f4c2d1a7e55
Create Date: 2026-03-03 14:40:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3c2a9f7b6d11"
down_revision: Union[str, Sequence[str], None] = "9f4c2d1a7e55"
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


def upgrade() -> None:
    op.create_table(
        "track_runs",
        *_standard_columns(),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("chapter_id", sa.String(64), nullable=True),
        sa.Column("track_type", sa.String(32), nullable=False),
        sa.Column("worker_type", sa.String(64), nullable=True),
        sa.Column("model_profile_id", sa.String(64), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="queued"),
        sa.Column("blocked_reason", sa.String(128), nullable=True),
        sa.Column("dependency_json", postgresql.JSONB(), nullable=True),
        sa.Column("counters_json", postgresql.JSONB(), nullable=True),
        sa.Column("config_json", postgresql.JSONB(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["render_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chapter_id"], ["chapters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["model_profile_id"], ["model_profiles.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("tenant_id", "project_id", "run_id", "track_type", name="uq_track_runs_scope_run_track"),
    )
    op.create_index("ix_track_runs_scope_run", "track_runs", ["tenant_id", "project_id", "run_id"])
    op.create_index("ix_track_runs_scope_status", "track_runs", ["tenant_id", "project_id", "status"])
    op.create_index("ix_track_runs_tenant_id", "track_runs", ["tenant_id"])
    op.create_index("ix_track_runs_project_id", "track_runs", ["project_id"])
    op.create_index("ix_track_runs_deleted_at", "track_runs", ["deleted_at"])
    op.create_index("ix_track_runs_created_at", "track_runs", ["created_at"])

    op.create_table(
        "track_units",
        *_standard_columns(),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("track_run_id", sa.String(64), nullable=False),
        sa.Column("chapter_id", sa.String(64), nullable=True),
        sa.Column("shot_id", sa.String(64), nullable=True),
        sa.Column("dialogue_id", sa.String(64), nullable=True),
        sa.Column("unit_ref_id", sa.String(64), nullable=False),
        sa.Column("unit_kind", sa.String(32), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="queued"),
        sa.Column("blocked_reason", sa.String(128), nullable=True),
        sa.Column("planned_start_ms", sa.Integer(), nullable=True),
        sa.Column("planned_end_ms", sa.Integer(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("last_error_code", sa.String(64), nullable=True),
        sa.Column("last_error_message", sa.Text(), nullable=True),
        sa.Column("input_payload_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("output_candidates_json", postgresql.JSONB(), nullable=True),
        sa.Column("selected_asset_id", sa.String(64), nullable=True),
        sa.Column("selected_job_id", sa.String(64), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["render_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["track_run_id"], ["track_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chapter_id"], ["chapters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["shot_id"], ["shots.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["dialogue_id"], ["dialogues.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["selected_asset_id"], ["artifacts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["selected_job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("tenant_id", "project_id", "track_run_id", "unit_ref_id", name="uq_track_units_scope_track_ref"),
    )
    op.create_index("ix_track_units_scope_run", "track_units", ["tenant_id", "project_id", "run_id"])
    op.create_index("ix_track_units_scope_track", "track_units", ["tenant_id", "project_id", "track_run_id"])
    op.create_index("ix_track_units_scope_status", "track_units", ["tenant_id", "project_id", "status"])
    op.create_index("ix_track_units_tenant_id", "track_units", ["tenant_id"])
    op.create_index("ix_track_units_project_id", "track_units", ["project_id"])
    op.create_index("ix_track_units_deleted_at", "track_units", ["deleted_at"])
    op.create_index("ix_track_units_created_at", "track_units", ["created_at"])

    op.add_column("jobs", sa.Column("track_unit_id", sa.String(64), nullable=True))
    op.create_foreign_key(
        "fk_jobs_track_unit_id_track_units",
        source_table="jobs",
        referent_table="track_units",
        local_cols=["track_unit_id"],
        remote_cols=["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_jobs_scope_track_unit", "jobs", ["tenant_id", "project_id", "track_unit_id"])


def downgrade() -> None:
    op.drop_index("ix_jobs_scope_track_unit", table_name="jobs")
    op.drop_constraint("fk_jobs_track_unit_id_track_units", "jobs", type_="foreignkey")
    op.drop_column("jobs", "track_unit_id")

    op.drop_table("track_units")
    op.drop_table("track_runs")
