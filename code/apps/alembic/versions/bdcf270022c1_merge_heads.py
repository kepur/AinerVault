"""merge_heads

Revision ID: bdcf270022c1
Revises: 7d1e4a9b2c01, b8f1c3d6e902
Create Date: 2026-04-02 13:51:09.182507

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bdcf270022c1'
down_revision: Union[str, Sequence[str], None] = ('7d1e4a9b2c01', 'b8f1c3d6e902')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
