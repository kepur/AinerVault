"""叙事结构：剧情节拍与风格提示。

v1 的世界模型抽离产出五类，其中两类 v2 一直缺：

    beats        剧情节拍，带张力值。分镜密度的依据 ——
                 高张力段落该切碎，低张力段落该给长镜头。
    style_hints  章节级的光影与影调提示，是画风素材的候选来源。

两者都带 evidence：任何判断都要能回到原文复核，这是 v1 做对的地方。
"""
from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, StdMixin


class StoryBeat(Base, StdMixin):
    """剧情节拍。一章切成若干叙事单元，每个带张力值。"""

    __tablename__ = "story_beats"
    __table_args__ = (
        UniqueConstraint("chapter_id", "order_no", name="uq_story_beats_chapter_order"),
        Index("ix_story_beats_chapter", "chapter_id"),
    )

    chapter_id: Mapped[str] = mapped_column(
        ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False
    )
    order_no: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    #: 1–5。分镜按它决定切分密度：5 该切碎，1 可以给长镜头
    tension_level: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    location_text: Mapped[str | None] = mapped_column(String(256))
    entity_names: Mapped[list | None] = mapped_column(JSONB)
    evidence_json: Mapped[list | None] = mapped_column(JSONB)
    scene_id: Mapped[str | None] = mapped_column(String(32))


class StyleHint(Base, StdMixin):
    """章节级风格提示。画风素材的候选来源。"""

    __tablename__ = "style_hints"
    __table_args__ = (Index("ix_style_hints_chapter", "chapter_id"),)

    chapter_id: Mapped[str] = mapped_column(
        ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False
    )
    lighting_style: Mapped[str | None] = mapped_column(Text)
    color_palette: Mapped[list | None] = mapped_column(JSONB)
    mood: Mapped[str | None] = mapped_column(String(128))
    camera_hint: Mapped[str | None] = mapped_column(Text)
    texture: Mapped[str | None] = mapped_column(Text)
    evidence_json: Mapped[list | None] = mapped_column(JSONB)
