"""创作画布：一章多张画布（整章总览 / 场次 / 自建，只存布局与引用）＋ 画布上的一键出片工作流

Revision ID: e2b6d4a9c3f1
Revises: c4d8e2f1a7b3
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'e2b6d4a9c3f1'
down_revision = 'c4d8e2f1a7b3'
branch_labels = None
depends_on = None

_STD = lambda: [  # noqa: E731
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('workspace_id', sa.String(length=64), nullable=False),
    sa.Column('created_by', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
]


def upgrade() -> None:
    op.create_table(
        'studio_boards', *_STD(),
        sa.Column('kind', sa.String(length=16), server_default=sa.text("'plan'"), nullable=False),
        sa.Column('title', sa.String(length=200), server_default=sa.text("''"), nullable=False),
        sa.Column('shot_plan_id', sa.String(length=32), nullable=True),
        sa.Column('chapter_id', sa.String(length=32), nullable=True),
        sa.Column('novel_id', sa.String(length=32), nullable=True),
        sa.Column('scope_json', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('sort', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('source', sa.String(length=16), server_default=sa.text("'auto'"), nullable=False),
        sa.Column('version', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('doc_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(['shot_plan_id'], ['core.shot_plans.id'],
                                name=op.f('fk_studio_boards_shot_plan_id'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_studio_boards')),
        schema='core',
    )
    for col in ('workspace_id', 'created_at', 'shot_plan_id', 'chapter_id', 'novel_id'):
        op.create_index(op.f(f'ix_studio_boards_{col}'), 'studio_boards', [col], unique=False, schema='core')
    # 整章总览一份计划只许一张：两个标签页同时首存时，后到的撞唯一索引 → 409
    op.create_index('uq_studio_boards_plan_overview', 'studio_boards', ['shot_plan_id'], unique=True, schema='core',
                    postgresql_where=sa.text("kind = 'plan'"))

    op.create_table(
        'studio_runs', *_STD(),
        sa.Column('board_id', sa.String(length=32), nullable=True),
        sa.Column('shot_plan_id', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('profile', sa.String(length=16), nullable=False),
        sa.Column('options_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('items_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('error', sa.String(length=500), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['board_id'], ['core.studio_boards.id'],
                                name=op.f('fk_studio_runs_board_id'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['shot_plan_id'], ['core.shot_plans.id'],
                                name=op.f('fk_studio_runs_shot_plan_id'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_studio_runs')),
        schema='core',
    )
    for col in ('workspace_id', 'created_at', 'board_id', 'shot_plan_id', 'status'):
        op.create_index(op.f(f'ix_studio_runs_{col}'), 'studio_runs', [col], unique=False, schema='core')


def downgrade() -> None:
    op.drop_table('studio_runs', schema='core')
    op.drop_table('studio_boards', schema='core')
