"""shot_performances.en_json：表情与动作的英文渲染

图像模型不认中文 —— 实跑时把中文表情动作拼进提示词，
出来的是一整版汉字纹样，不是画面。
中文字段留给人审核，英文这一份给出图。

Revision ID: e7a2c9d3f105
Revises: d5b9e2c14a70
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'e7a2c9d3f105'
down_revision = 'd5b9e2c14a70'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('shot_performances',
                  sa.Column('en_json', postgresql.JSONB(astext_type=sa.Text()),
                            nullable=True),
                  schema='core')


def downgrade() -> None:
    op.drop_column('shot_performances', 'en_json', schema='core')
