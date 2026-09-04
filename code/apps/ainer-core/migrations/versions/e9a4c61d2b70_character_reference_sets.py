"""人物三要素与三视角参考集。

Revision ID: e9a4c61d2b70
Revises: d7e3b52a91f4
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "e9a4c61d2b70"
down_revision = "d7e3b52a91f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "asset_epochs",
        sa.Column(
            "reference_set_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        schema="core",
    )


def downgrade() -> None:
    op.drop_column("asset_epochs", "reference_set_json", schema="core")
