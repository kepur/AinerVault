"""ORM 基类。

与 v1 的差异：
- 去掉 tenant_id / project_id 双层作用域，代之以单一 workspace_id（默认 "default"）。
  这是"砍多租户但留扩展位"的落法：将来要多团队时加索引 + 中间件注入即可，不改表结构。
- 去掉 trace/correlation/idempotency/error/retry 等编排框架遗留列，需要的表自己声明。
"""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import DateTime, MetaData, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(schema=settings.db_schema, naming_convention=NAMING_CONVENTION)

    #: 让所有 python Enum 生成的 PG 原生枚举跟随表所在 schema。
    #: 不设的话 DDL 会把类型建在 core（随 search_path），而 metadata 里记为无 schema，
    #: alembic autogenerate 每次都会误报「类型变更」。
    type_annotation_map = {
        enum.Enum: SAEnum(enum.Enum, inherit_schema=True),
    }


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class StdMixin(TimestampMixin):
    """标准列：id + workspace + 时间戳 + 创建人。"""

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String(64), default="default", nullable=False, index=True
    )
    created_by: Mapped[str | None] = mapped_column(String(64))
