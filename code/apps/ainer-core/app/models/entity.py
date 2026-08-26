"""世界观实体：人物 / 地点 / 道具 / 势力 / 风格。

合并了 v1 过度拆分的 entity_instance_links / continuity_profiles / preview_variants /
persona_* 等表；但保留两处独立表（见 world.py）：
  - entity_world_names   实体 × 映射 的名字
  - entity_world_visual  实体 × 目标世界观 的视觉变体
本表上的 localized_names 只是只读缓存，权威在 entity_world_names。
"""
from __future__ import annotations

from enum import Enum

from sqlalchemy import (
    Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, StdMixin


class EntityKind(str, Enum):
    character = "character"
    location = "location"
    prop = "prop"
    faction = "faction"
    style = "style"


class WorldEntity(Base, StdMixin):
    __tablename__ = "world_entities"
    __table_args__ = (
        UniqueConstraint("novel_id", "canonical_key", name="uq_world_entities_novel_key"),
        Index("ix_world_entities_novel_kind", "novel_id", "kind"),
    )

    novel_id: Mapped[str] = mapped_column(
        ForeignKey("novels.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[EntityKind] = mapped_column(default=EntityKind.character, nullable=False)
    canonical_key: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    aliases_json: Mapped[list | None] = mapped_column(JSONB)
    # 只读缓存，权威在 entity_world_names
    localized_names: Mapped[dict | None] = mapped_column(JSONB)
    summary: Mapped[str | None] = mapped_column(Text)

    # 家族分组 —— 驱动姓氏一致性命名
    family_key: Mapped[str | None] = mapped_column(String(64), index=True)

    # 基础视觉（目标世界观下的变体在 entity_world_visual）
    visual_prompt: Mapped[str | None] = mapped_column(Text)
    negative_prompt: Mapped[str | None] = mapped_column(Text)
    ref_asset_ids: Mapped[list | None] = mapped_column(JSONB)
    style_entity_id: Mapped[str | None] = mapped_column(String(32))

    # {voice_id, pitch, speed, emotion, sample_asset_id}
    voice_profile_json: Mapped[dict | None] = mapped_column(JSONB)

    locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    first_seen_chapter_order: Mapped[int | None] = mapped_column(Integer)
    appear_chapters_json: Mapped[list | None] = mapped_column(JSONB)


class EntityChapterState(Base, StdMixin):
    """角色成长 / 场景历史：某章节起该实体的状态变体。

    渲染第 N 章时取 chapter_order_from <= N 的最新一条，叠加到基础 visual_prompt 上。
    对应旧 SKILL_33「角色成长连续性」，v2 中是主线能力而非扩展位。
    """

    __tablename__ = "entity_chapter_states"
    __table_args__ = (
        Index("ix_entity_chapter_states_lookup", "entity_id", "chapter_order_from"),
    )

    entity_id: Mapped[str] = mapped_column(
        ForeignKey("world_entities.id", ondelete="CASCADE"), nullable=False
    )
    chapter_order_from: Mapped[int] = mapped_column(Integer, nullable=False)
    # {appearance, costume, age, injury, rank, mood}
    state_json: Mapped[dict | None] = mapped_column(JSONB)
    visual_prompt_override: Mapped[str | None] = mapped_column(Text)
    ref_asset_ids: Mapped[list | None] = mapped_column(JSONB)
    note: Mapped[str | None] = mapped_column(Text)
