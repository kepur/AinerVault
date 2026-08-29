"""shot_motions 的英文那一份

运动描述与制作单一样，是直接交给视频模型的 ——
而视频模型和图像模型一样不认中文。

Revision ID: d7e3b52a91f4
Revises: c2a9e14b8073
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'd7e3b52a91f4'
down_revision = 'c2a9e14b8073'
branch_labels = None
depends_on = None


def upgrade() -> None:
    for col in ('motion_prompt_en', 'start_frame_en', 'end_frame_en'):
        op.add_column('shot_motions', sa.Column(col, sa.Text(), nullable=True),
                      schema='core')
    op.add_column('shot_motions',
                  sa.Column('deltas_en_json',
                            postgresql.JSONB(astext_type=sa.Text()), nullable=True),
                  schema='core')


def downgrade() -> None:
    for col in ('deltas_en_json', 'end_frame_en', 'start_frame_en',
                'motion_prompt_en'):
        op.drop_column('shot_motions', col, schema='core')
