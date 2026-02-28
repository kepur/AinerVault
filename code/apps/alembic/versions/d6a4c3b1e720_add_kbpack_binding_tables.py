"""add_kbpack_binding_tables

Revision ID: d6a4c3b1e720
Revises: c5f3a2b7d890
Create Date: 2026-02-28 15:36:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d6a4c3b1e720"
down_revision: Union[str, Sequence[str], None] = "c5f3a2b7d890"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Enum types ────────────────────────────────────────────────────────────
    op.execute(
        "CREATE TYPE kbpackstatus AS ENUM ('draft','embedded','published','deprecated')"
    )
    op.execute(
        "CREATE TYPE kbsourcetype AS ENUM ('pdf','docx','xlsx','txt','url','manual')"
    )

    # ── kb_packs ──────────────────────────────────────────────────────────────
    op.create_table(
        "kb_packs",
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
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("language_code", sa.String(16), nullable=True),
        sa.Column("culture_pack", sa.String(64), nullable=True),
        sa.Column("version_name", sa.String(32), nullable=False, server_default="v1"),
        sa.Column(
            "status",
            postgresql.ENUM(
                "draft", "embedded", "published", "deprecated",
                name="kbpackstatus",
                create_type=False,
            ),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("tags_json", postgresql.JSONB(), nullable=True),
        sa.Column("bind_suggestions_json", postgresql.JSONB(), nullable=True),
        sa.Column("collection_id", sa.String(64), nullable=True),
        sa.ForeignKeyConstraint(["collection_id"], ["rag_collections.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("tenant_id", "project_id", "name", name="uq_kb_packs_scope_name"),
    )
    op.create_index("ix_kb_packs_scope_name", "kb_packs", ["tenant_id", "project_id", "name"])
    op.create_index("ix_kb_packs_scope_status", "kb_packs", ["tenant_id", "project_id", "status"])
    op.create_index("ix_kb_packs_tenant_id", "kb_packs", ["tenant_id"])
    op.create_index("ix_kb_packs_project_id", "kb_packs", ["project_id"])
    op.create_index("ix_kb_packs_deleted_at", "kb_packs", ["deleted_at"])
    op.create_index("ix_kb_packs_created_at", "kb_packs", ["created_at"])

    # ── kb_sources ────────────────────────────────────────────────────────────
    op.create_table(
        "kb_sources",
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
        sa.Column("kb_pack_id", sa.String(64), nullable=False),
        sa.Column(
            "source_type",
            postgresql.ENUM(
                "pdf", "docx", "xlsx", "txt", "url", "manual",
                name="kbsourcetype",
                create_type=False,
            ),
            nullable=False,
            server_default="txt",
        ),
        sa.Column("source_name", sa.String(256), nullable=True),
        sa.Column("source_uri", sa.String(512), nullable=True),
        sa.Column("parse_status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("parse_log", sa.Text, nullable=True),
        sa.Column("chunk_count", sa.Integer, nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["kb_pack_id"], ["kb_packs.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_kb_sources_pack", "kb_sources", ["kb_pack_id"])
    op.create_index("ix_kb_sources_status", "kb_sources", ["parse_status"])
    op.create_index("ix_kb_sources_tenant_id", "kb_sources", ["tenant_id"])
    op.create_index("ix_kb_sources_project_id", "kb_sources", ["project_id"])
    op.create_index("ix_kb_sources_deleted_at", "kb_sources", ["deleted_at"])

    # ── role_kb_maps ──────────────────────────────────────────────────────────
    op.create_table(
        "role_kb_maps",
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
        sa.Column("role_id", sa.String(128), nullable=False),
        sa.Column("kb_pack_id", sa.String(64), nullable=False),
        sa.Column("priority", sa.Integer, nullable=False, server_default="100"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("note", sa.String(256), nullable=True),
        sa.ForeignKeyConstraint(["kb_pack_id"], ["kb_packs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "project_id", "role_id", "kb_pack_id", name="uq_role_kb_maps_role_pack"),
    )
    op.create_index("ix_role_kb_maps_role", "role_kb_maps", ["tenant_id", "project_id", "role_id"])
    op.create_index("ix_role_kb_maps_pack", "role_kb_maps", ["kb_pack_id"])
    op.create_index("ix_role_kb_maps_tenant_id", "role_kb_maps", ["tenant_id"])
    op.create_index("ix_role_kb_maps_deleted_at", "role_kb_maps", ["deleted_at"])

    # ── persona_kb_maps ───────────────────────────────────────────────────────
    op.create_table(
        "persona_kb_maps",
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
        sa.Column("persona_pack_id", sa.String(64), nullable=False),
        sa.Column("kb_pack_id", sa.String(64), nullable=False),
        sa.Column("priority", sa.Integer, nullable=False, server_default="100"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("note", sa.String(256), nullable=True),
        sa.ForeignKeyConstraint(["persona_pack_id"], ["persona_packs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["kb_pack_id"], ["kb_packs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "project_id", "persona_pack_id", "kb_pack_id", name="uq_persona_kb_maps_persona_pack"),
    )
    op.create_index("ix_persona_kb_maps_persona", "persona_kb_maps", ["tenant_id", "project_id", "persona_pack_id"])
    op.create_index("ix_persona_kb_maps_pack", "persona_kb_maps", ["kb_pack_id"])
    op.create_index("ix_persona_kb_maps_tenant_id", "persona_kb_maps", ["tenant_id"])
    op.create_index("ix_persona_kb_maps_deleted_at", "persona_kb_maps", ["deleted_at"])

    # ── novel_kb_maps ─────────────────────────────────────────────────────────
    op.create_table(
        "novel_kb_maps",
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
        sa.Column("novel_id", sa.String(64), nullable=False),
        sa.Column("kb_pack_id", sa.String(64), nullable=False),
        sa.Column("priority", sa.Integer, nullable=False, server_default="100"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("note", sa.String(256), nullable=True),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["kb_pack_id"], ["kb_packs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "project_id", "novel_id", "kb_pack_id", name="uq_novel_kb_maps_novel_pack"),
    )
    op.create_index("ix_novel_kb_maps_novel", "novel_kb_maps", ["tenant_id", "project_id", "novel_id"])
    op.create_index("ix_novel_kb_maps_pack", "novel_kb_maps", ["kb_pack_id"])
    op.create_index("ix_novel_kb_maps_tenant_id", "novel_kb_maps", ["tenant_id"])
    op.create_index("ix_novel_kb_maps_deleted_at", "novel_kb_maps", ["deleted_at"])


def downgrade() -> None:
    op.drop_table("novel_kb_maps")
    op.drop_table("persona_kb_maps")
    op.drop_table("role_kb_maps")
    op.drop_table("kb_sources")
    op.drop_table("kb_packs")
    op.execute("DROP TYPE IF EXISTS kbsourcetype")
    op.execute("DROP TYPE IF EXISTS kbpackstatus")
