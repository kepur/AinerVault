"""add glossary warning types

Revision ID: e1f2a3b4c5d6
Revises: c9d4e6f7a8b1
Create Date: 2026-04-27 00:00:00.000000
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "e1f2a3b4c5d6"
down_revision = "c9d4e6f7a8b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE warningtype ADD VALUE IF NOT EXISTS 'glossary_missing'")
    op.execute("ALTER TYPE warningtype ADD VALUE IF NOT EXISTS 'glossary_drift'")


def downgrade() -> None:
    # PostgreSQL enum values cannot be removed safely in-place.
    pass