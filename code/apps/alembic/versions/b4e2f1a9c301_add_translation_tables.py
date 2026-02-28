"""add_translation_tables

Revision ID: b4e2f1a9c301
Revises: a3c7d1e9f452
Create Date: 2026-02-28 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b4e2f1a9c301"
down_revision: Union[str, Sequence[str], None] = "a3c7d1e9f452"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Enum types ────────────────────────────────────────────────────────────
    op.execute(
        "CREATE TYPE translationprojectstatus AS ENUM "
        "('draft','in_progress','completed','archived')"
    )
    op.execute(
        "CREATE TYPE consistencymode AS ENUM ('strict','balanced','free')"
    )
    op.execute(
        "CREATE TYPE blocktype AS ENUM "
        "('narration','dialogue','action','heading','scene_break')"
    )
    op.execute(
        "CREATE TYPE translationblockstatus AS ENUM ('draft','reviewed','locked')"
    )
    op.execute(
        "CREATE TYPE warningtype AS ENUM ('name_drift','new_variant','cross_chapter')"
    )
    op.execute(
        "CREATE TYPE warningstatus AS ENUM ('open','resolved','ignored')"
    )

    # ── translation_projects ──────────────────────────────────────────────────
    op.create_table(
        "translation_projects",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("trace_id", sa.String(128), nullable=True),
        sa.Column("correlation_id", sa.String(128), nullable=True),
        sa.Column("idempotency_key", sa.String(256), nullable=True),
        sa.Column("version", sa.String(32), nullable=False, server_default="v1"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("updated_by", sa.String(64), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.String(1024), nullable=True),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("novel_id", sa.String(64), nullable=False),
        sa.Column("source_language_code", sa.String(16), nullable=False),
        sa.Column("target_language_code", sa.String(16), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "draft", "in_progress", "completed", "archived",
                name="translationprojectstatus",
                create_type=False,
            ),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("model_provider_id", sa.String(128), nullable=True),
        sa.Column(
            "consistency_mode",
            postgresql.ENUM(
                "strict", "balanced", "free",
                name="consistencymode",
                create_type=False,
            ),
            nullable=False,
            server_default="balanced",
        ),
        sa.Column("term_dictionary_json", postgresql.JSONB(), nullable=True),
        sa.Column("stats_json", postgresql.JSONB(), nullable=True),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_tp_novel", "translation_projects", ["novel_id"])
    op.create_index("ix_tp_scope", "translation_projects", ["tenant_id", "project_id"])
    op.create_index(
        "ix_translation_projects_tenant_id", "translation_projects", ["tenant_id"]
    )
    op.create_index(
        "ix_translation_projects_project_id", "translation_projects", ["project_id"]
    )
    op.create_index(
        "ix_translation_projects_deleted_at", "translation_projects", ["deleted_at"]
    )
    op.create_index(
        "ix_translation_projects_created_at", "translation_projects", ["created_at"]
    )

    # ── script_blocks ─────────────────────────────────────────────────────────
    op.create_table(
        "script_blocks",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("trace_id", sa.String(128), nullable=True),
        sa.Column("correlation_id", sa.String(128), nullable=True),
        sa.Column("idempotency_key", sa.String(256), nullable=True),
        sa.Column("version", sa.String(32), nullable=False, server_default="v1"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("updated_by", sa.String(64), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.String(1024), nullable=True),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("translation_project_id", sa.String(64), nullable=False),
        sa.Column("chapter_id", sa.String(64), nullable=False),
        sa.Column("seq_no", sa.Integer, nullable=False),
        sa.Column(
            "block_type",
            postgresql.ENUM(
                "narration", "dialogue", "action", "heading", "scene_break",
                name="blocktype",
                create_type=False,
            ),
            nullable=False,
            server_default="narration",
        ),
        sa.Column("source_text", sa.Text, nullable=False),
        sa.Column("speaker_tag", sa.String(128), nullable=True),
        sa.ForeignKeyConstraint(
            ["translation_project_id"], ["translation_projects.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["chapter_id"], ["chapters.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_sb_project_chapter",
        "script_blocks",
        ["translation_project_id", "chapter_id"],
    )
    op.create_index(
        "ix_sb_project_seq",
        "script_blocks",
        ["translation_project_id", "seq_no"],
    )
    op.create_index(
        "ix_script_blocks_tenant_id", "script_blocks", ["tenant_id"]
    )
    op.create_index(
        "ix_script_blocks_project_id", "script_blocks", ["project_id"]
    )
    op.create_index(
        "ix_script_blocks_deleted_at", "script_blocks", ["deleted_at"]
    )
    op.create_index(
        "ix_script_blocks_created_at", "script_blocks", ["created_at"]
    )

    # ── entity_name_variants ──────────────────────────────────────────────────
    op.create_table(
        "entity_name_variants",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("trace_id", sa.String(128), nullable=True),
        sa.Column("correlation_id", sa.String(128), nullable=True),
        sa.Column("idempotency_key", sa.String(256), nullable=True),
        sa.Column("version", sa.String(32), nullable=False, server_default="v1"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("updated_by", sa.String(64), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.String(1024), nullable=True),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("translation_project_id", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.String(128), nullable=True),
        sa.Column("source_name", sa.String(256), nullable=False),
        sa.Column("canonical_target_name", sa.String(256), nullable=False),
        sa.Column("is_locked", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("aliases_json", postgresql.JSONB(), nullable=True),
        sa.ForeignKeyConstraint(
            ["translation_project_id"], ["translation_projects.id"], ondelete="CASCADE"
        ),
    )
    op.create_index("ix_env_project", "entity_name_variants", ["translation_project_id"])
    op.create_index(
        "ix_entity_name_variants_tenant_id", "entity_name_variants", ["tenant_id"]
    )
    op.create_index(
        "ix_entity_name_variants_project_id", "entity_name_variants", ["project_id"]
    )
    op.create_index(
        "ix_entity_name_variants_deleted_at", "entity_name_variants", ["deleted_at"]
    )
    op.create_index(
        "ix_entity_name_variants_created_at", "entity_name_variants", ["created_at"]
    )

    # ── translation_blocks ────────────────────────────────────────────────────
    op.create_table(
        "translation_blocks",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("trace_id", sa.String(128), nullable=True),
        sa.Column("correlation_id", sa.String(128), nullable=True),
        sa.Column("idempotency_key", sa.String(256), nullable=True),
        sa.Column("version", sa.String(32), nullable=False, server_default="v1"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("updated_by", sa.String(64), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.String(1024), nullable=True),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("script_block_id", sa.String(64), nullable=False),
        sa.Column("translation_project_id", sa.String(64), nullable=False),
        sa.Column("translated_text", sa.Text, nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "draft", "reviewed", "locked",
                name="translationblockstatus",
                create_type=False,
            ),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("translation_notes", sa.Text, nullable=True),
        sa.Column("model_provider_id", sa.String(128), nullable=True),
        sa.ForeignKeyConstraint(
            ["script_block_id"], ["script_blocks.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["translation_project_id"], ["translation_projects.id"], ondelete="CASCADE"
        ),
    )
    op.create_index("ix_tb_script_block", "translation_blocks", ["script_block_id"])
    op.create_index("ix_tb_project", "translation_blocks", ["translation_project_id"])
    op.create_index(
        "ix_translation_blocks_tenant_id", "translation_blocks", ["tenant_id"]
    )
    op.create_index(
        "ix_translation_blocks_project_id", "translation_blocks", ["project_id"]
    )
    op.create_index(
        "ix_translation_blocks_deleted_at", "translation_blocks", ["deleted_at"]
    )
    op.create_index(
        "ix_translation_blocks_created_at", "translation_blocks", ["created_at"]
    )

    # ── consistency_warnings ──────────────────────────────────────────────────
    op.create_table(
        "consistency_warnings",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("project_id", sa.String(64), nullable=False),
        sa.Column("trace_id", sa.String(128), nullable=True),
        sa.Column("correlation_id", sa.String(128), nullable=True),
        sa.Column("idempotency_key", sa.String(256), nullable=True),
        sa.Column("version", sa.String(32), nullable=False, server_default="v1"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("updated_by", sa.String(64), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.String(1024), nullable=True),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("translation_project_id", sa.String(64), nullable=False),
        sa.Column("translation_block_id", sa.String(64), nullable=True),
        sa.Column(
            "warning_type",
            postgresql.ENUM(
                "name_drift", "new_variant", "cross_chapter",
                name="warningtype",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("source_name", sa.String(256), nullable=False),
        sa.Column("detected_variant", sa.String(256), nullable=False),
        sa.Column("expected_canonical", sa.String(256), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "open", "resolved", "ignored",
                name="warningstatus",
                create_type=False,
            ),
            nullable=False,
            server_default="open",
        ),
        sa.ForeignKeyConstraint(
            ["translation_project_id"], ["translation_projects.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["translation_block_id"], ["translation_blocks.id"], ondelete="SET NULL"
        ),
    )
    op.create_index("ix_cw_project", "consistency_warnings", ["translation_project_id"])
    op.create_index("ix_cw_status", "consistency_warnings", ["status"])
    op.create_index(
        "ix_consistency_warnings_tenant_id", "consistency_warnings", ["tenant_id"]
    )
    op.create_index(
        "ix_consistency_warnings_project_id", "consistency_warnings", ["project_id"]
    )
    op.create_index(
        "ix_consistency_warnings_deleted_at", "consistency_warnings", ["deleted_at"]
    )
    op.create_index(
        "ix_consistency_warnings_created_at", "consistency_warnings", ["created_at"]
    )


def downgrade() -> None:
    op.drop_table("consistency_warnings")
    op.drop_table("translation_blocks")
    op.drop_table("entity_name_variants")
    op.drop_table("script_blocks")
    op.drop_table("translation_projects")

    op.execute("DROP TYPE IF EXISTS warningstatus")
    op.execute("DROP TYPE IF EXISTS warningtype")
    op.execute("DROP TYPE IF EXISTS translationblockstatus")
    op.execute("DROP TYPE IF EXISTS blocktype")
    op.execute("DROP TYPE IF EXISTS consistencymode")
    op.execute("DROP TYPE IF EXISTS translationprojectstatus")
