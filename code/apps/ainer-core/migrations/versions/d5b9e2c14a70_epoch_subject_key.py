"""asset_epochs / epoch_bindings: subject_key + entity_id

时期最要紧的对象恰恰是人物 —— 少年林凡与中年林凡的脸要一样、
衣着兵器要不一样，这是整套设计的初衷。但 asset_specs 里没有「人物」这一类
（人物是叙事实体，不是可复用的视觉素材），于是人物时期一直无处可挂：
INVARIANT_FIELDS["character"] 定义了却永远取不到。

改成主体二选一：素材填 asset_spec_id，人物填 entity_id，
subject_key 记实际那一个并承担唯一键。
两个可空外键做不成唯一键 —— Postgres 里 NULL 各不相等，
(NULL, profile, 'baseline') 能插两条，同一个人就有了两份基准形态。

Revision ID: d5b9e2c14a70
Revises: c3f7a10be241
"""
from alembic import op
import sqlalchemy as sa

revision = 'd5b9e2c14a70'
down_revision = 'c3f7a10be241'
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ('asset_epochs', 'epoch_bindings'):
        op.add_column(table, sa.Column('subject_key', sa.String(length=32),
                                       nullable=True), schema='core')
        op.add_column(table, sa.Column('entity_id', sa.String(length=32),
                                       nullable=True), schema='core')
        op.create_foreign_key(
            op.f(f'fk_{table}_entity_id'), table, 'world_entities',
            ['entity_id'], ['id'], source_schema='core',
            referent_schema='core', ondelete='CASCADE')
        # 存量行的主体都是素材
        op.execute(f'UPDATE core.{table} SET subject_key = asset_spec_id '
                   f'WHERE subject_key IS NULL')
        op.alter_column(table, 'subject_key', nullable=False, schema='core')
        op.alter_column(table, 'asset_spec_id', nullable=True, schema='core')
        op.create_index(op.f(f'ix_{table}_subject_key'), table,
                        ['subject_key'], unique=False, schema='core')

    op.drop_constraint('uq_asset_epoch_spec_profile_key', 'asset_epochs',
                       schema='core', type_='unique')
    op.create_unique_constraint(
        'uq_asset_epoch_subject_profile_key', 'asset_epochs',
        ['subject_key', 'world_profile_id', 'epoch_key'], schema='core')
    op.drop_index('ix_asset_epoch_lookup', table_name='asset_epochs',
                  schema='core')
    op.create_index('ix_asset_epoch_lookup', 'asset_epochs',
                    ['subject_key', 'world_profile_id', 'from_chapter_order'],
                    unique=False, schema='core')

    op.drop_constraint('uq_epoch_binding_shot_spec', 'epoch_bindings',
                       schema='core', type_='unique')
    op.create_unique_constraint(
        'uq_epoch_binding_shot_subject', 'epoch_bindings',
        ['shot_id', 'subject_key'], schema='core')


def downgrade() -> None:
    op.drop_constraint('uq_epoch_binding_shot_subject', 'epoch_bindings',
                       schema='core', type_='unique')
    op.drop_constraint('uq_asset_epoch_subject_profile_key', 'asset_epochs',
                       schema='core', type_='unique')
    op.drop_index('ix_asset_epoch_lookup', table_name='asset_epochs',
                  schema='core')
    for table in ('asset_epochs', 'epoch_bindings'):
        op.execute(f'DELETE FROM core.{table} WHERE asset_spec_id IS NULL')
        op.alter_column(table, 'asset_spec_id', nullable=False, schema='core')
        op.drop_index(op.f(f'ix_{table}_subject_key'), table_name=table,
                      schema='core')
        op.drop_constraint(op.f(f'fk_{table}_entity_id'), table,
                           schema='core', type_='foreignkey')
        op.drop_column(table, 'entity_id', schema='core')
        op.drop_column(table, 'subject_key', schema='core')
    op.create_index('ix_asset_epoch_lookup', 'asset_epochs',
                    ['asset_spec_id', 'world_profile_id', 'from_chapter_order'],
                    unique=False, schema='core')
    op.create_unique_constraint(
        'uq_asset_epoch_spec_profile_key', 'asset_epochs',
        ['asset_spec_id', 'world_profile_id', 'epoch_key'], schema='core')
    op.create_unique_constraint('uq_epoch_binding_shot_spec', 'epoch_bindings',
                                ['shot_id', 'asset_spec_id'], schema='core')
