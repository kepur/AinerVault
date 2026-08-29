"""world_lexicon.no_equivalent

「目标文化里没有对应物」是词条的固有属性，不是某次导读的推断。
导读要讲的正是这些 —— 有对应物的词写进导读是浪费读者的耐心，
而耐心是导读最稀缺的资源。

Revision ID: a4d6f0b7c218
Revises: f1c8b4e2a903
"""
from alembic import op
import sqlalchemy as sa

revision = 'a4d6f0b7c218'
down_revision = 'f1c8b4e2a903'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('world_lexicon',
                  sa.Column('no_equivalent', sa.Boolean(), nullable=False,
                            server_default=sa.false()),
                  schema='core')


def downgrade() -> None:
    op.drop_column('world_lexicon', 'no_equivalent', schema='core')
