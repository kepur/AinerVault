"""Director Core：场景协议快照、渲染任务、产物

Revision ID: c4d8e2f1a7b3
Revises: b7e3d91c4a20
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'c4d8e2f1a7b3'
down_revision = 'b7e3d91c4a20'
branch_labels = None
depends_on = None

_STD = lambda: [  # noqa: E731
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('workspace_id', sa.String(length=64), nullable=False),
    sa.Column('created_by', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
]
_J = lambda: postgresql.JSONB(astext_type=sa.Text())  # noqa: E731


def upgrade() -> None:
    op.create_table(
        'director_scenes', *_STD(),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('source', sa.String(length=16), nullable=False),
        sa.Column('box_project_id', sa.String(length=32), nullable=True),
        sa.Column('protocol_json', _J(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('prompt', sa.Text(), nullable=True),
        sa.Column('notes_json', _J(), nullable=True),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_director_scenes')),
        schema='core',
    )
    for col in ('workspace_id', 'created_at', 'box_project_id'):
        op.create_index(op.f(f'ix_director_scenes_{col}'), 'director_scenes', [col], unique=False, schema='core')

    op.create_table(
        'director_jobs', *_STD(),
        sa.Column('scene_id', sa.String(length=32), nullable=True),
        sa.Column('parent_id', sa.String(length=32), nullable=True),
        sa.Column('job_type', sa.String(length=24), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('backend', sa.String(length=16), nullable=False),
        sa.Column('input_json', _J(), nullable=True),
        sa.Column('progress_json', _J(), nullable=True),
        sa.Column('output_manifest_json', _J(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['scene_id'], ['core.director_scenes.id'], name=op.f('fk_director_jobs_scene_id'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_director_jobs')),
        schema='core',
    )
    for col in ('workspace_id', 'created_at', 'scene_id', 'parent_id', 'status'):
        op.create_index(op.f(f'ix_director_jobs_{col}'), 'director_jobs', [col], unique=False, schema='core')

    op.create_table(
        'director_outputs', *_STD(),
        sa.Column('job_id', sa.String(length=32), nullable=False),
        sa.Column('kind', sa.String(length=24), nullable=False),
        sa.Column('path', sa.String(length=512), nullable=False),
        sa.Column('asset_id', sa.String(length=32), nullable=True),
        sa.Column('url', sa.String(length=1024), nullable=True),
        sa.Column('bytes', sa.Integer(), nullable=True),
        sa.Column('meta_json', _J(), nullable=True),
        sa.ForeignKeyConstraint(['job_id'], ['core.director_jobs.id'], name=op.f('fk_director_outputs_job_id'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_director_outputs')),
        schema='core',
    )
    for col in ('workspace_id', 'created_at', 'job_id'):
        op.create_index(op.f(f'ix_director_outputs_{col}'), 'director_outputs', [col], unique=False, schema='core')


def downgrade() -> None:
    op.drop_table('director_outputs', schema='core')
    op.drop_table('director_jobs', schema='core')
    op.drop_table('director_scenes', schema='core')
