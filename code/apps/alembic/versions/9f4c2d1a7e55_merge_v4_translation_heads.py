"""merge v4 translation heads

Revision ID: 9f4c2d1a7e55
Revises: 456d2c37a891, 2b7e4d9f1c33
Create Date: 2026-03-01 18:56:00.000000
"""
from typing import Sequence, Union


revision: str = "9f4c2d1a7e55"
down_revision: Union[str, Sequence[str], None] = ("456d2c37a891", "2b7e4d9f1c33")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
