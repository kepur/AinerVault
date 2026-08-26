"""add_translation_glossary_tables

Revision ID: c9d4e6f7a8b1
Revises: fb2d3c4e5a67
Create Date: 2026-04-27 12:30:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "c9d4e6f7a8b1"
down_revision: Union[str, Sequence[str], None] = "fb2d3c4e5a67"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE glossarytermstatus AS ENUM "
        "('draft','approved','archived')"
    )
    op.execute(
        "CREATE TYPE glossarytermtype AS ENUM "
        "('proper_noun','artifact','creature','place','faction','technique','cultural','other')"
    )
    op.execute(
        "CREATE TYPE glossarycandidatestatus AS ENUM "
        "('pending_review','approved','rejected','merged')"
    )

    op.create_table(
        "glossary_terms",
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
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("novel_id", sa.String(64), nullable=True),
        sa.Column("translation_project_id", sa.String(64), nullable=True),
        sa.Column("source_language_code", sa.String(16), nullable=False),
        sa.Column("target_language_code", sa.String(16), nullable=False),
        sa.Column("source_term", sa.String(256), nullable=False),
        sa.Column("target_term", sa.String(256), nullable=False),
        sa.Column(
            "term_type",
            postgresql.ENUM(
                "proper_noun", "artifact", "creature", "place", "faction", "technique", "cultural", "other",
                name="glossarytermtype",
                create_type=False,
            ),
            nullable=False,
            server_default="proper_noun",
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                "draft", "approved", "archived",
                name="glossarytermstatus",
                create_type=False,
            ),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("aliases_json", postgresql.JSONB(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("context_json", postgresql.JSONB(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=True),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["translation_project_id"], ["translation_projects.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_gt_lang_status", "glossary_terms", ["source_language_code", "target_language_code", "status"])
    op.create_index("ix_gt_source_term", "glossary_terms", ["source_term"])
    op.create_index("ix_gt_project_scope", "glossary_terms", ["translation_project_id"])
    op.create_index("ix_glossary_terms_tenant_id", "glossary_terms", ["tenant_id"])
    op.create_index("ix_glossary_terms_project_id", "glossary_terms", ["project_id"])
    op.create_index("ix_glossary_terms_deleted_at", "glossary_terms", ["deleted_at"])
    op.create_index("ix_glossary_terms_created_at", "glossary_terms", ["created_at"])

    op.create_table(
        "glossary_candidates",
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
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("novel_id", sa.String(64), nullable=False),
        sa.Column("translation_project_id", sa.String(64), nullable=False),
        sa.Column("source_language_code", sa.String(16), nullable=False),
        sa.Column("target_language_code", sa.String(16), nullable=False),
        sa.Column("source_term", sa.String(256), nullable=False),
        sa.Column("suggested_target_term", sa.String(256), nullable=True),
        sa.Column(
            "term_type",
            postgresql.ENUM(
                "proper_noun", "artifact", "creature", "place", "faction", "technique", "cultural", "other",
                name="glossarytermtype",
                create_type=False,
            ),
            nullable=False,
            server_default="proper_noun",
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending_review", "approved", "rejected", "merged",
                name="glossarycandidatestatus",
                create_type=False,
            ),
            nullable=False,
            server_default="pending_review",
        ),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("source_excerpt", sa.Text(), nullable=True),
        sa.Column("source_block_id", sa.String(64), nullable=True),
        sa.Column("normalized_term", sa.String(256), nullable=True),
        sa.Column("candidate_reason", sa.Text(), nullable=True),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=True),
        sa.Column("approved_term_id", sa.String(64), nullable=True),
        sa.ForeignKeyConstraint(["novel_id"], ["novels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["translation_project_id"], ["translation_projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_block_id"], ["script_blocks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approved_term_id"], ["glossary_terms.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_gc_project_status", "glossary_candidates", ["translation_project_id", "status"])
    op.create_index("ix_gc_source_term", "glossary_candidates", ["source_term"])
    op.create_index("ix_gc_term_type", "glossary_candidates", ["term_type"])
    op.create_index("ix_glossary_candidates_tenant_id", "glossary_candidates", ["tenant_id"])
    op.create_index("ix_glossary_candidates_project_id", "glossary_candidates", ["project_id"])
    op.create_index("ix_glossary_candidates_deleted_at", "glossary_candidates", ["deleted_at"])
    op.create_index("ix_glossary_candidates_created_at", "glossary_candidates", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_glossary_candidates_created_at", table_name="glossary_candidates")
    op.drop_index("ix_glossary_candidates_deleted_at", table_name="glossary_candidates")
    op.drop_index("ix_glossary_candidates_project_id", table_name="glossary_candidates")
    op.drop_index("ix_glossary_candidates_tenant_id", table_name="glossary_candidates")
    op.drop_index("ix_gc_term_type", table_name="glossary_candidates")
    op.drop_index("ix_gc_source_term", table_name="glossary_candidates")
    op.drop_index("ix_gc_project_status", table_name="glossary_candidates")
    op.drop_table("glossary_candidates")

    op.drop_index("ix_glossary_terms_created_at", table_name="glossary_terms")
    op.drop_index("ix_glossary_terms_deleted_at", table_name="glossary_terms")
    op.drop_index("ix_glossary_terms_project_id", table_name="glossary_terms")
    op.drop_index("ix_glossary_terms_tenant_id", table_name="glossary_terms")
    op.drop_index("ix_gt_project_scope", table_name="glossary_terms")
    op.drop_index("ix_gt_source_term", table_name="glossary_terms")
    op.drop_index("ix_gt_lang_status", table_name="glossary_terms")
    op.drop_table("glossary_terms")

    op.execute("DROP TYPE glossarycandidatestatus")
    op.execute("DROP TYPE glossarytermtype")
    op.execute("DROP TYPE glossarytermstatus")