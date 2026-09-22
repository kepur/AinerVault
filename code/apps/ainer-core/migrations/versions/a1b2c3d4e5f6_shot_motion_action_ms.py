"""shot_motions.action_ms：这个动作在现实里要多久

视频模型拿到多长的时长，就把动作铺满多长。一记耳光本来 0.8 秒，
按镜头时长给它 5 秒，出来就是慢动作 —— 而观众一眼看得出那不对。

从前时长是 min(镜头时长, 动作镜 2s / 对话镜 8s)，而「是不是动作镜」
靠关键词猜。猜不中就按 8 秒上限走，于是一批镜头全是慢动作。
改成由动作导演在写运动时一并判断，它本来就在描述这个动作怎么发生。

Revision ID: a1b2c3d4e5f6
Revises: e9a4c61d2b70
"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f6'
down_revision = 'e9a4c61d2b70'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('shot_motions',
                  sa.Column('action_ms', sa.Integer(), nullable=True),
                  schema='core')


def downgrade() -> None:
    op.drop_column('shot_motions', 'action_ms', schema='core')
