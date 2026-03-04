"""add_skill_runs_and_persistence

Revision ID: f3a2b1c0d456
Revises: e2f1a9c30145
Create Date: 2026-03-01 12:00:00.000000

持久化改造：
- skill_runs 运行记录表（LLM 调用去重 + 成本统计 + 版本回溯）
- chapters 新增版本/Run 引用字段
- entity_mappings 新增命名策略/锁定字段
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f3a2b1c0d456"
down_revision: Union[str, Sequence[str], None] = "e2f1a9c30145"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. skill_runs 运行记录表 ─────────────────────────────────────────────
    op.execute(
        "CREATE TYPE skillrunstatus AS ENUM ('queued','running','succeeded','failed')"
    )

    op.create_table(
        "skill_runs",
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
        # Business fields
        sa.Column("skill_id", sa.String(64), nullable=False),
        sa.Column("novel_id", sa.String(64), nullable=True),
        sa.Column("chapter_id", sa.String(64), nullable=True),
        sa.Column("input_hash", sa.String(64), nullable=True),
        sa.Column("input_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM("queued", "running", "succeeded", "failed",
                            name="skillrunstatus", create_type=False),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("output_json", postgresql.JSONB(), nullable=True),
        sa.Column("raw_response", sa.Text, nullable=True),
        sa.Column("token_usage", postgresql.JSONB(), nullable=True),
        sa.Column("cost_estimate", sa.Float, nullable=True),
        sa.Column("model_provider_id", sa.String(64), nullable=True),
        sa.Column("model_name", sa.String(128), nullable=True),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chapter_id"], ["chapters.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_skill_runs_skill_id",    "skill_runs", ["skill_id"])
    op.create_index("ix_skill_runs_input_hash",  "skill_runs", ["input_hash"])
    op.create_index("ix_skill_runs_chapter",     "skill_runs", ["chapter_id"])
    op.create_index("ix_skill_runs_novel",       "skill_runs", ["novel_id"])
    op.create_index("ix_skill_runs_status",      "skill_runs", ["status"])
    op.create_index("ix_skill_runs_tenant_id",   "skill_runs", ["tenant_id"])
    op.create_index("ix_skill_runs_deleted_at",  "skill_runs", ["deleted_at"])

    # ── 2. chapters 新增版本/缓存字段 ─────────────────────────────────────────
    op.add_column("chapters", sa.Column("format_detect_json",      postgresql.JSONB(), nullable=True))
    op.add_column("chapters", sa.Column("script_version",          sa.Integer, nullable=False, server_default="0"))
    op.add_column("chapters", sa.Column("world_model_version",     sa.Integer, nullable=False, server_default="0"))
    op.add_column("chapters", sa.Column("script_run_id",           sa.String(64), nullable=True))
    op.add_column("chapters", sa.Column("world_model_run_id",      sa.String(64), nullable=True))
    op.add_column("chapters", sa.Column("script_updated_at",       sa.DateTime(timezone=True), nullable=True))
    op.add_column("chapters", sa.Column("world_model_updated_at",  sa.DateTime(timezone=True), nullable=True))

    # ── 3. entity_mappings 新增命名策略/锁定字段 ─────────────────────────────
    op.add_column("entity_mappings", sa.Column("naming_policy",      sa.String(64), nullable=True))
    op.add_column("entity_mappings", sa.Column("culture_profile_id", sa.String(64), nullable=True))
    op.add_column("entity_mappings", sa.Column("style_tags_json",    postgresql.JSONB(), nullable=True))
    op.add_column("entity_mappings", sa.Column("rationale",          sa.Text, nullable=True))
    op.add_column("entity_mappings", sa.Column("locked",             sa.Boolean, nullable=False, server_default="false"))
    op.add_column("entity_mappings", sa.Column("updated_by_ai",      sa.Boolean, nullable=False, server_default="false"))


def downgrade() -> None:
    # entity_mappings
    op.drop_column("entity_mappings", "updated_by_ai")
    op.drop_column("entity_mappings", "locked")
    op.drop_column("entity_mappings", "rationale")
    op.drop_column("entity_mappings", "style_tags_json")
    op.drop_column("entity_mappings", "culture_profile_id")
    op.drop_column("entity_mappings", "naming_policy")
    # chapters
    op.drop_column("chapters", "world_model_updated_at")
    op.drop_column("chapters", "script_updated_at")
    op.drop_column("chapters", "world_model_run_id")
    op.drop_column("chapters", "script_run_id")
    op.drop_column("chapters", "world_model_version")
    op.drop_column("chapters", "script_version")
    op.drop_column("chapters", "format_detect_json")
    # skill_runs
    op.drop_table("skill_runs")
    op.execute("DROP TYPE IF EXISTS skillrunstatus")
