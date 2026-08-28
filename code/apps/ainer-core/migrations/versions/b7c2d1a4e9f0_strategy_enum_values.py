"""策略枚举补 4 个新值

autogenerate 不会生成 ALTER TYPE ... ADD VALUE —— 它只比对列和表，
不比对枚举的取值集合。加了新枚举成员却只跑自动迁移，
表结构看着一切正常，直到运行时写入才炸在 InvalidTextRepresentation。

Revision ID: b7c2d1a4e9f0
Revises: ac9c41c3ce68
"""
from alembic import op

revision = "b7c2d1a4e9f0"
down_revision = "ac9c41c3ce68"
branch_labels = None
depends_on = None

#: 策略阶梯从 5 档扩到 9 档时新增的
_NEW = ("transplant", "naturalize", "gloss_inline", "footnote", "omit")


def upgrade() -> None:
    for v in _NEW:
        # IF NOT EXISTS 让这条迁移可重复执行，
        # 也兼容枚举在别处已被补齐过的库
        op.execute(f"ALTER TYPE core.devicestrategy ADD VALUE IF NOT EXISTS '{v}'")


def downgrade() -> None:
    # PostgreSQL 不支持从枚举里删值。要回退只能重建整个类型并改写所有引用列，
    # 代价远大于收益 —— 多几个用不到的枚举值不会造成任何问题。
    pass
