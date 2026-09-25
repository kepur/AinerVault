"""3D-BOX 场景项目、对话，与预设库（风格／运镜／特效／题材／模板／发型／服装／官方角色）

Revision ID: b7e3d91c4a20
Revises: a1b2c3d4e5f6
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'b7e3d91c4a20'
down_revision = 'a1b2c3d4e5f6'
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
        'scene_projects', *_STD(),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('novel_id', sa.String(length=32), nullable=True),
        sa.Column('shot_plan_id', sa.String(length=32), nullable=True),
        sa.Column('scene_id', sa.String(length=32), nullable=True),
        sa.Column('template', sa.String(length=64), nullable=True),
        sa.Column('files_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('overrides_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('compiled_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('diagnostics_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('versions_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('settings_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('seed', sa.Integer(), nullable=False),
        sa.Column('thumb_url', sa.String(length=1024), nullable=True),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_scene_projects')),
        schema='core',
    )
    for col in ('workspace_id', 'created_at', 'novel_id', 'shot_plan_id'):
        op.create_index(op.f(f'ix_scene_projects_{col}'), 'scene_projects', [col], unique=False, schema='core')

    op.create_table(
        'scene_messages', *_STD(),
        sa.Column('project_id', sa.String(length=32), nullable=False),
        sa.Column('run_id', sa.String(length=32), nullable=True),
        sa.Column('role', sa.String(length=16), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('meta_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['core.scene_projects.id'], name=op.f('fk_scene_messages_project_id'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_scene_messages')),
        schema='core',
    )
    for col in ('workspace_id', 'created_at', 'project_id', 'run_id'):
        op.create_index(op.f(f'ix_scene_messages_{col}'), 'scene_messages', [col], unique=False, schema='core')

    op.create_table(
        'presets', *_STD(),
        sa.Column('kind', sa.String(length=32), nullable=False),
        sa.Column('key', sa.String(length=64), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('category', sa.String(length=64), nullable=True),
        sa.Column('cover_url', sa.String(length=1024), nullable=True),
        sa.Column('payload_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('tags_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('author', sa.String(length=64), nullable=True),
        sa.Column('official', sa.Boolean(), nullable=False),
        sa.Column('commercial', sa.Boolean(), nullable=False),
        sa.Column('uses', sa.Integer(), nullable=False),
        sa.Column('sort', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_presets')),
        sa.UniqueConstraint('kind', 'key', name='uq_presets_kind_key'),
        schema='core',
    )
    for col in ('workspace_id', 'created_at', 'kind', 'category'):
        op.create_index(op.f(f'ix_presets_{col}'), 'presets', [col], unique=False, schema='core')

    op.create_table(
        'preset_marks', *_STD(),
        sa.Column('preset_id', sa.String(length=32), nullable=False),
        sa.Column('mark', sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(['preset_id'], ['core.presets.id'], name=op.f('fk_preset_marks_preset_id'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_preset_marks')),
        sa.UniqueConstraint('preset_id', 'mark', 'workspace_id', name='uq_preset_marks'),
        schema='core',
    )
    for col in ('workspace_id', 'created_at', 'preset_id'):
        op.create_index(op.f(f'ix_preset_marks_{col}'), 'preset_marks', [col], unique=False, schema='core')


def downgrade() -> None:
    op.drop_table('preset_marks', schema='core')
    op.drop_table('presets', schema='core')
    op.drop_table('scene_messages', schema='core')
    op.drop_table('scene_projects', schema='core')
