"""add_kb_binding_fields

Revision ID: c5f3a2b7d890
Revises: b4e2f1a9c301
Create Date: 2026-02-28 15:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c5f3a2b7d890"
down_revision: Union[str, Sequence[str], None] = "b4e2f1a9c301"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── KBBindType enum ──
    op.execute(
        "CREATE TYPE kbbindtype AS ENUM ('role','persona','novel','global')"
    )

    # ── RagCollection: add bind_type + bind_id ──
    op.add_column(
        "rag_collections",
        sa.Column(
            "bind_type",
            sa.Enum("role", "persona", "novel", "global", name="kbbindtype", create_type=False),
            nullable=True,
        ),
    )
    op.add_column(
        "rag_collections",
        sa.Column("bind_id", sa.String(128), nullable=True),
    )
    op.create_index(
        "ix_rag_collections_bind",
        "rag_collections",
        ["tenant_id", "project_id", "bind_type", "bind_id"],
    )

    # ── PersonaPack: add role_id ──
    op.add_column(
        "persona_packs",
        sa.Column("role_id", sa.String(128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("persona_packs", "role_id")
    op.drop_index("ix_rag_collections_bind", table_name="rag_collections")
    op.drop_column("rag_collections", "bind_id")
    op.drop_column("rag_collections", "bind_type")
    op.execute("DROP TYPE IF EXISTS kbbindtype")
