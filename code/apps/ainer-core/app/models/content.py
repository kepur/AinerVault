"""内容层：小说与章节。"""
from __future__ import annotations

from enum import Enum

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, StdMixin


class SourceFormat(str, Enum):
    plain = "plain"
    markdown = "markdown"
    epub_html = "epub_html"


class Novel(Base, StdMixin):
    __tablename__ = "novels"

    title: Mapped[str] = mapped_column(String(256), nullable=False)
    author: Mapped[str | None] = mapped_column(String(128))
    source_language_code: Mapped[str] = mapped_column(String(16), default="zh-CN", nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    cover_asset_id: Mapped[str | None] = mapped_column(String(32))
    default_target_languages: Mapped[list | None] = mapped_column(JSONB)
    # 原生世界观（source world）；目标世界观在 world_transforms 上
    source_world_profile_id: Mapped[str | None] = mapped_column(String(32))
    meta_json: Mapped[dict | None] = mapped_column(JSONB)


class Chapter(Base, StdMixin):
    __tablename__ = "chapters"
    __table_args__ = (
        Index("ix_chapters_novel_order", "novel_id", "order_no"),
        UniqueConstraint("novel_id", "order_no", name="uq_chapters_novel_order"),
    )

    novel_id: Mapped[str] = mapped_column(
        ForeignKey("novels.id", ondelete="CASCADE"), nullable=False
    )
    order_no: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(256))
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    word_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source_format: Mapped[SourceFormat] = mapped_column(
        default=SourceFormat.plain, nullable=False
    )
    ingest_meta_json: Mapped[dict | None] = mapped_column(JSONB)
