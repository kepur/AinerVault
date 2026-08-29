"""混合源圈层：穿越小说一本书横跨两个圈层

「先生」在古代场是老师，在现代场是 Mr.。
同一个源词在两个圈层里译法不同，靠 (transform, source_term) 唯一是分不开的 ——
后写的会覆盖先写的，而覆盖掉哪一个取决于挖掘顺序，两次跑可能不一样。

Revision ID: b8e3f5a1d740
Revises: a4d6f0b7c218
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'b8e3f5a1d740'
down_revision = 'a4d6f0b7c218'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('world_transforms',
                  sa.Column('extra_source_profiles_json',
                            postgresql.JSONB(astext_type=sa.Text()), nullable=True),
                  schema='core')
    op.add_column('scenes',
                  sa.Column('source_profile_id', sa.String(length=32),
                            nullable=True),
                  schema='core')
    op.create_index(op.f('ix_scenes_source_profile_id'), 'scenes',
                    ['source_profile_id'], unique=False, schema='core')
    op.add_column('world_lexicon',
                  sa.Column('source_profile_id', sa.String(length=32),
                            nullable=True),
                  schema='core')
    op.create_foreign_key(
        op.f('fk_world_lexicon_source_profile_id'), 'world_lexicon',
        'world_profiles', ['source_profile_id'], ['id'],
        source_schema='core', referent_schema='core', ondelete='SET NULL')
    op.drop_constraint('uq_lexicon_transform_source', 'world_lexicon',
                       schema='core', type_='unique')
    op.create_unique_constraint(
        'uq_lexicon_transform_source', 'world_lexicon',
        ['transform_id', 'source_term', 'source_profile_id'], schema='core')


def downgrade() -> None:
    op.drop_constraint('uq_lexicon_transform_source', 'world_lexicon',
                       schema='core', type_='unique')
    op.create_unique_constraint('uq_lexicon_transform_source', 'world_lexicon',
                                ['transform_id', 'source_term'], schema='core')
    op.drop_constraint(op.f('fk_world_lexicon_source_profile_id'),
                       'world_lexicon', schema='core', type_='foreignkey')
    op.drop_column('world_lexicon', 'source_profile_id', schema='core')
    op.drop_index(op.f('ix_scenes_source_profile_id'), table_name='scenes',
                  schema='core')
    op.drop_column('scenes', 'source_profile_id', schema='core')
    op.drop_column('world_transforms', 'extra_source_profiles_json',
                   schema='core')
