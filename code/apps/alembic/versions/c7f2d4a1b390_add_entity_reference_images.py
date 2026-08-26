"""add_entity_reference_images

Revision ID: c7f2d4a1b390
Revises: a33b1c2d4e56
Create Date: 2026-04-03 10:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c7f2d4a1b390"
down_revision: Union[str, Sequence[str], None] = "a33b1c2d4e56"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "entities",
        sa.Column(
            "reference_images_json",
            postgresql.JSONB(),
            nullable=True,
            comment="参考图片列表 [{url, filename, uploaded_at}]",
        ),
    )


def downgrade() -> None:
    op.drop_column("entities", "reference_images_json")
