"""转译力度 · 导读篇 · 虚构圈层底座

三件事各自独立，但都服务同一个问题：**目标文化圈层的读者要读得懂**。

  world_primers            体系性认知一次讲完，正文里才能直接用原物
  world_profiles.is_fictional / base_profile_id
                           虚构圈层不是任何现实文化，但读者是现实里的人
  （力度三档写在 transform.policy_json，无需建表）

Revision ID: f1c8b4e2a903
Revises: e7a2c9d3f105
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'f1c8b4e2a903'
down_revision = 'e7a2c9d3f105'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('world_profiles',
                  sa.Column('is_fictional', sa.Boolean(), nullable=False,
                            server_default=sa.false()),
                  schema='core')
    op.add_column('world_profiles',
                  sa.Column('base_profile_id', sa.String(length=32), nullable=True),
                  schema='core')
    op.create_foreign_key(
        op.f('fk_world_profiles_base_profile_id'), 'world_profiles',
        'world_profiles', ['base_profile_id'], ['id'],
        source_schema='core', referent_schema='core', ondelete='SET NULL')

    reviewstatus = postgresql.ENUM(
        'candidate', 'approved', 'locked', name='reviewstatus',
        schema='core', create_type=False)
    op.create_table(
        'world_primers',
        sa.Column('transform_id', sa.String(length=32), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=256), nullable=True),
        sa.Column('sections_json', postgresql.JSONB(astext_type=sa.Text()),
                  nullable=True),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('covers_json', postgresql.JSONB(astext_type=sa.Text()),
                  nullable=True),
        sa.Column('word_count', sa.Integer(), nullable=False),
        sa.Column('model', sa.String(length=128), nullable=True),
        sa.Column('rationale', sa.Text(), nullable=True),
        sa.Column('status', reviewstatus, nullable=False),
        sa.Column('edited_by_human', sa.Boolean(), nullable=False),
        sa.Column('locked', sa.Boolean(), nullable=False),
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('workspace_id', sa.String(length=64), nullable=False),
        sa.Column('created_by', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['transform_id'], ['core.world_transforms.id'],
                                name=op.f('fk_world_primers_transform_id'),
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_world_primers')),
        schema='core',
    )
    op.create_index('ix_world_primers_transform', 'world_primers',
                    ['transform_id', 'status'], unique=False, schema='core')
    op.create_index(op.f('ix_world_primers_created_at'), 'world_primers',
                    ['created_at'], unique=False, schema='core')
    op.create_index(op.f('ix_world_primers_workspace_id'), 'world_primers',
                    ['workspace_id'], unique=False, schema='core')


def downgrade() -> None:
    op.drop_table('world_primers', schema='core')
    op.drop_constraint(op.f('fk_world_profiles_base_profile_id'),
                       'world_profiles', schema='core', type_='foreignkey')
    op.drop_column('world_profiles', 'base_profile_id', schema='core')
    op.drop_column('world_profiles', 'is_fictional', schema='core')
