"""数据库会话与 schema 管理。"""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

engine = create_engine(
    settings.database_url,
    echo=settings.db_echo,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)


@event.listens_for(engine, "connect", insert=True)
def _set_search_path(dbapi_conn, _record) -> None:
    """每条连接固定 search_path，ORM 里就不必到处写 schema 名。"""
    cur = dbapi_conn.cursor()
    cur.execute(f"SET search_path TO {settings.db_schema}, public")
    cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def ensure_schema() -> None:
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS {settings.db_schema}'))
