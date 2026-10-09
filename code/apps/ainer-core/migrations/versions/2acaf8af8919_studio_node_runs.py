"""创作画布：配方节点的服务端运行记录（studio_node_runs，执行器 pipelines/canvas_exec.py 写）

一个节点每跑一次一行；「当前结果」= 这个节点最近一次 succeeded 的那行。
只建新表，不动 studio_boards / studio_runs。

Revision ID: 2acaf8af8919
Revises: e2b6d4a9c3f1
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '2acaf8af8919'
down_revision = 'e2b6d4a9c3f1'
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
        'studio_node_runs', *_STD(),
        sa.Column('board_id', sa.String(length=32), nullable=False),
        sa.Column('node_id', sa.String(length=120), nullable=False),
        sa.Column('op', sa.String(length=16), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('recipe_hash', sa.String(length=64), nullable=True),
        sa.Column('recipe_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('task_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('progress', sa.Integer(), nullable=True),
        sa.Column('step', sa.String(length=200), nullable=True),
        sa.Column('error', sa.String(length=500), nullable=True),
        sa.Column('media_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('extra_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['board_id'], ['core.studio_boards.id'],
                                name=op.f('fk_studio_node_runs_board_id'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_studio_node_runs')),
        schema='core',
    )
    for col in ('workspace_id', 'created_at', 'board_id', 'status'):
        op.create_index(op.f(f'ix_studio_node_runs_{col}'), 'studio_node_runs', [col], unique=False, schema='core')
    # node-runs 接口按画布取每个节点最近一次（DISTINCT ON node_id ORDER BY created_at DESC）
    op.create_index('ix_studio_node_runs_board_node_created', 'studio_node_runs',
                    ['board_id', 'node_id', 'created_at'], unique=False, schema='core')


def downgrade() -> None:
    op.drop_table('studio_node_runs', schema='core')
