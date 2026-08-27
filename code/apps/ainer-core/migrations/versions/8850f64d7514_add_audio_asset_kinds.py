"""add audio asset kinds

Revision ID: 8850f64d7514
Revises: 1e948975c724
Create Date: 2026-08-27 16:36:36.678737
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '8850f64d7514'
down_revision = '1e948975c724'
branch_labels = None
depends_on = None


#: 音频素材类别。alembic autogenerate 不处理 enum 值变更，须手写。
NEW_KINDS = ("voice", "sfx", "bgm", "room_tone")


def upgrade() -> None:
    # PG 12+ 支持在事务内 ADD VALUE；IF NOT EXISTS 让迁移可重复执行
    for kind in NEW_KINDS:
        op.execute(f"ALTER TYPE core.assetkindspec ADD VALUE IF NOT EXISTS '{kind}'")


def downgrade() -> None:
    # PG 不支持从 enum 移除值。要回滚需重建类型并迁移依赖列，
    # 代价远高于收益 —— 多出来的枚举值不影响旧代码。
    pass
