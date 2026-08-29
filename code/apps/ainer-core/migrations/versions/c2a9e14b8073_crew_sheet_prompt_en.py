"""crew_sheets.prompt_en：制作单的英文提示词

制作单是本系统对下游（图像／视频生成）的主要交付物，
而图像模型不认中文 —— 喂中文出来的是一整版汉字纹样，不是画面。
只有中文那一份，等于交不出去。

中文留给人审核，英文交给模型。

Revision ID: c2a9e14b8073
Revises: b8e3f5a1d740
"""
from alembic import op
import sqlalchemy as sa

revision = 'c2a9e14b8073'
down_revision = 'b8e3f5a1d740'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('crew_sheets', sa.Column('prompt_en', sa.Text(), nullable=True),
                  schema='core')


def downgrade() -> None:
    op.drop_column('crew_sheets', 'prompt_en', schema='core')
