"""剧本层：ScriptDoc → Scene → Block。

主干决策：ScriptDoc 语言无关，只算一次；翻译是 Block 的语言层（见 translation.py）。
"""
from __future__ import annotations

from enum import Enum

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, StdMixin


class DocStatus(str, Enum):
    draft = "draft"
    active = "active"
    archived = "archived"


class DocMode(str, Enum):
    """剧本文档的两种形态。

    prose      译本模式：按段落切块，不调 LLM、不切场景。
               产出的是可读的译本小说，不是分镜脚本。
    screenplay 剧本模式：LLM 拆场景与镜头单元，供分镜编译消费。

    先做 prose 再升级到 screenplay 是有意的顺序 ——
    译本的人名、名物、身份称谓都校对锁定之后，剧本才有可信的地基。
    """

    prose = "prose"
    screenplay = "screenplay"


class BlockType(str, Enum):
    """v1 的 5 种扩到 8 种。

    TRANSLATABLE 之外的类型（action / scene_break）不进翻译线 —— 它们只服务画面生成，
    用内部语言即可。这是 v1 最大的心智混乱点，此处写死。
    """

    narration = "narration"          # 旁白
    dialogue = "dialogue"            # 对白
    action = "action"                # 动作描述 —— 不翻译
    signage = "signage"              # 画面文字/招牌
    title = "title"                  # 标题
    inner_monolog = "inner_monolog"  # 内心独白
    heading = "heading"              # 章节标题
    scene_break = "scene_break"      # 分场分隔 —— 不翻译


TRANSLATABLE_TYPES: frozenset[BlockType] = frozenset(
    {
        BlockType.narration,
        BlockType.dialogue,
        BlockType.signage,
        BlockType.title,
        BlockType.inner_monolog,
        BlockType.heading,
    }
)


class ScriptDoc(Base, StdMixin):
    __tablename__ = "script_docs"
    __table_args__ = (
        UniqueConstraint("chapter_id", "version", name="uq_script_docs_chapter_version"),
        Index("ix_script_docs_chapter_status", "chapter_id", "status"),
    )

    chapter_id: Mapped[str] = mapped_column(
        ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[DocStatus] = mapped_column(default=DocStatus.draft, nullable=False)
    doc_mode: Mapped[DocMode] = mapped_column(default=DocMode.screenplay, nullable=False)
    language_source: Mapped[str] = mapped_column(String(16), default="zh-CN", nullable=False)
    input_fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)
    generator_meta: Mapped[dict | None] = mapped_column(JSONB)
    stats_json: Mapped[dict | None] = mapped_column(JSONB)


class Scene(Base, StdMixin):
    __tablename__ = "scenes"
    __table_args__ = (Index("ix_scenes_doc_order", "script_doc_id", "order_no"),)

    script_doc_id: Mapped[str] = mapped_column(
        ForeignKey("script_docs.id", ondelete="CASCADE"), nullable=False
    )
    order_no: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(256))
    time_of_day: Mapped[str | None] = mapped_column(String(64))
    location_entity_id: Mapped[str | None] = mapped_column(String(32))
    location_text: Mapped[str | None] = mapped_column(String(256))
    weather: Mapped[str | None] = mapped_column(String(64))
    mood: Mapped[str | None] = mapped_column(String(64))
    summary: Mapped[str | None] = mapped_column(Text)
    # 场景级共享素材 —— 同场景所有镜头复用，省钱且保证空间一致
    bg_asset_id: Mapped[str | None] = mapped_column(String(32))
    bgm_asset_id: Mapped[str | None] = mapped_column(String(32))
    ambience_asset_id: Mapped[str | None] = mapped_column(String(32))
    edited_by_human: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ScriptBlock(Base, StdMixin):
    __tablename__ = "script_blocks"
    __table_args__ = (
        Index("ix_script_blocks_doc_seq", "script_doc_id", "seq_no"),
        Index("ix_script_blocks_scene", "scene_id"),
    )

    script_doc_id: Mapped[str] = mapped_column(
        ForeignKey("script_docs.id", ondelete="CASCADE"), nullable=False
    )
    scene_id: Mapped[str | None] = mapped_column(ForeignKey("scenes.id", ondelete="SET NULL"))
    seq_no: Mapped[int] = mapped_column(Integer, nullable=False)
    block_type: Mapped[BlockType] = mapped_column(default=BlockType.narration, nullable=False)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    speaker_tag: Mapped[str | None] = mapped_column(String(128))
    speaker_entity_id: Mapped[str | None] = mapped_column(String(32), index=True)
    edited_by_human: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    meta_json: Mapped[dict | None] = mapped_column(JSONB)

    @property
    def translatable(self) -> bool:
        return self.block_type in TRANSLATABLE_TYPES
