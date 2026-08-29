"""voice casting: cast_key, engine, model

旁白也要有配音行 —— 它是全片出现最多的那把嗓子。但它没有实体，
而 entity_id 是 NOT NULL 的外键。改成：cast_key 承担唯一键，
entity_id 可空且只在真有实体时填。

不能只把 entity_id 改成可空就完事：Postgres 里 NULL 各不相等，
(NULL, profile, 'baseline') 能插进去两条，旁白就有了两个嗓子。

Revision ID: c3f7a10be241
Revises: de6fc0de7c7d
"""
from alembic import op
import sqlalchemy as sa

revision = 'c3f7a10be241'
down_revision = 'de6fc0de7c7d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('voice_castings',
                  sa.Column('cast_key', sa.String(length=64), nullable=True),
                  schema='core')
    op.add_column('voice_castings',
                  sa.Column('voice_engine', sa.String(length=64), nullable=True),
                  schema='core')
    op.add_column('voice_castings',
                  sa.Column('model', sa.String(length=128), nullable=True),
                  schema='core')
    op.add_column('voice_castings',
                  sa.Column('edited_by_human', sa.Boolean(), nullable=False,
                            server_default=sa.false()),
                  schema='core')
    # 已有行的 cast_key 就是它的 entity_id
    op.execute('UPDATE core.voice_castings SET cast_key = entity_id '
               'WHERE cast_key IS NULL')
    op.alter_column('voice_castings', 'cast_key', nullable=False, schema='core')
    op.alter_column('voice_castings', 'entity_id', nullable=True, schema='core')
    op.create_index(op.f('ix_voice_castings_cast_key'), 'voice_castings',
                    ['cast_key'], unique=False, schema='core')
    op.drop_constraint('uq_voice_casting_entity_profile_epoch', 'voice_castings',
                       schema='core', type_='unique')
    op.create_unique_constraint('uq_voice_casting_key_profile_epoch',
                                'voice_castings',
                                ['cast_key', 'world_profile_id', 'epoch_key'],
                                schema='core')


def downgrade() -> None:
    op.drop_constraint('uq_voice_casting_key_profile_epoch', 'voice_castings',
                       schema='core', type_='unique')
    op.execute('DELETE FROM core.voice_castings WHERE entity_id IS NULL')
    op.alter_column('voice_castings', 'entity_id', nullable=False, schema='core')
    op.create_unique_constraint('uq_voice_casting_entity_profile_epoch',
                                'voice_castings',
                                ['entity_id', 'world_profile_id', 'epoch_key'],
                                schema='core')
    op.drop_index(op.f('ix_voice_castings_cast_key'), table_name='voice_castings',
                  schema='core')
    for col in ('edited_by_human', 'model', 'voice_engine', 'cast_key'):
        op.drop_column('voice_castings', col, schema='core')
