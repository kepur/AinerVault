from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, text

from app.config import settings
from app.models import Base   # 导入即注册全部表

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
SCHEMA = settings.db_schema


def include_name(name, type_, parent_names) -> bool:
    """只反射 core schema。v1 的 public 表必须完全不可见，
    否则 autogenerate 会把同名的 v1 表（users / scenes / shots …）当成本 schema 的表来 diff。
    """
    if type_ == "schema":
        return name == SCHEMA
    return True


def include_object(obj, name, type_, reflected, compare_to) -> bool:
    if type_ == "table":
        return (obj.schema or SCHEMA) == SCHEMA
    return True


def _engine():
    """反射时保持默认 search_path。

    若把 search_path 钉死为 core，反射出的表 schema 变成 None，
    就与 metadata 里的 "core.xxx" 对不上，autogenerate 会误判成"全部新建"。
    v1 的 public 表由 include_name 的 schema 过滤挡住。
    """
    return create_engine(settings.database_url, pool_pre_ping=True)


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        include_schemas=True,
        include_name=include_name,
        include_object=include_object,
        version_table_schema=SCHEMA,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = _engine()
    with engine.connect() as connection:
        connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_name=include_name,
            include_object=include_object,
            version_table_schema=SCHEMA,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
