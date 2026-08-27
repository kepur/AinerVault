"""基础素材包 —— 画面生成的唯一真源。

继承 v1 SKILL_33 的核心主张：服装/表情/动作/道具/场景/氛围必须**资产化**，
不塞自然语言。镜头只引用素材，不自己描述外观 —— 否则同一件长袍在十个镜头里
会长成十个样子。

v1 缺的、v2 补上的一点：素材必须绑定目标世界观。
同一件「文士长袍」在昭和日本是「着物（書生風）」，在中世纪欧洲是 "scholar's tunic"，
两者是同一 canonical_key 的两个变体，而不是两条不相干的记录。

三层叠加（Stage 不覆盖 Core，Override 不污染 Stage）：
  AssetVariant           素材在某世界观下的稳定形态       ← 基础包
  EntityChapterState     角色成长，按章节范围生效          ← 阶段
  ShotAssetBinding       镜头级临时状态（脏污/伤痕/汗水）  ← 覆盖
"""
from __future__ import annotations

from enum import Enum

from sqlalchemy import (
    Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, StdMixin
from app.models.world import ReviewStatus


class AssetKindSpec(str, Enum):
    """素材类别。

    与 world_entities 的分工：
      world_entities  有专名、需要人名映射的叙事实体（人物 / 地点 / 势力）
      asset_specs     可复用的视觉素材（服装 / 道具 / 表情 / 动作 / 环境 / 画风）
    人物的「外观」在 entity_world_visual；人物「穿什么」引用这里的 costume。
    """

    costume = "costume"          # 服装
    prop = "prop"                # 道具
    location = "location"        # 场景/环境
    expression = "expression"    # 表情
    action = "action"            # 动作/姿态
    ambience = "ambience"        # 视觉氛围/光线
    style = "style"              # 画风基调
    creature = "creature"        # 非人角色/坐骑
    # ── 音频素材：与视觉素材完全对称，走同一条流水线 ──
    # ref_asset_ids 存的是参考音频（音色样本），而非参考图。
    # 音色一致性的根 = 参考音频 + voice_id，正如视觉一致性的根 = 参考图 + seed。
    voice = "voice"              # 角色音色
    sfx = "sfx"                  # 音效
    bgm = "bgm"                  # 配乐
    room_tone = "room_tone"      # 环境底噪（听觉版 ambience）


class AssetOrigin(str, Enum):
    """素材来源。与 gen.AssetSource（产物来源）区分，两者是不同维度。"""

    mined = "mined"        # 从原文抽取
    llm = "llm"            # 按世界观标准自动生成
    template = "template"  # 预置模板
    manual = "manual"      # 人工录入


class AssetSpec(Base, StdMixin):
    """素材语义 —— 世界观无关的那一层。

    canonical_key 是上位语义（costume.scholar_robe），跨世界观稳定，
    与 world_lexicon 的设计同构：一个语义，N 个世界观形态。
    """

    __tablename__ = "asset_specs"
    __table_args__ = (
        UniqueConstraint("novel_id", "canonical_key", name="uq_asset_specs_novel_key"),
        Index("ix_asset_specs_novel_kind", "novel_id", "kind"),
        Index("ix_asset_specs_entity", "entity_id"),
    )

    novel_id: Mapped[str] = mapped_column(
        ForeignKey("novels.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[AssetKindSpec] = mapped_column(nullable=False)
    canonical_key: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    aliases_json: Mapped[list | None] = mapped_column(JSONB)
    summary: Mapped[str | None] = mapped_column(Text)

    #: 该素材专属于某实体时填写（如「李清照的青莲剑」）；通用素材留空
    entity_id: Mapped[str | None] = mapped_column(
        ForeignKey("world_entities.id", ondelete="SET NULL")
    )
    #: {chapter_ids: [], excerpts: []} —— 出处，可点开复核
    evidence_json: Mapped[dict | None] = mapped_column(JSONB)
    first_seen_chapter_order: Mapped[int | None] = mapped_column(Integer)
    importance: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    source: Mapped[AssetOrigin] = mapped_column(default=AssetOrigin.mined, nullable=False)


class AssetVariant(Base, StdMixin):
    """素材在某个目标世界观下的具体形态。

    structured_json 存结构化字段而非整段自然语言 —— 这是 SKILL_33 的核心主张：
    「材质=木綿、廓形=着流し、时代记号=昭和初期」比一句
    「一件昭和时期的棉布和服」更可控、可比对、可局部改写。
    """

    __tablename__ = "asset_variants"
    __table_args__ = (
        UniqueConstraint(
            "asset_spec_id", "world_profile_id", name="uq_asset_variants_spec_profile"
        ),
        Index("ix_asset_variants_profile_status", "world_profile_id", "status"),
    )

    asset_spec_id: Mapped[str] = mapped_column(
        ForeignKey("asset_specs.id", ondelete="CASCADE"), nullable=False
    )
    world_profile_id: Mapped[str] = mapped_column(
        ForeignKey("world_profiles.id", ondelete="CASCADE"), nullable=False
    )
    target_name: Mapped[str] = mapped_column(String(256), nullable=False)
    target_reading: Mapped[str | None] = mapped_column(String(256))
    visual_prompt: Mapped[str | None] = mapped_column(Text)
    negative_prompt: Mapped[str | None] = mapped_column(Text)
    #: 按 kind 而异的结构化字段，见 asset_requirements
    structured_json: Mapped[dict | None] = mapped_column(JSONB)
    ref_asset_ids: Mapped[list | None] = mapped_column(JSONB)

    status: Mapped[ReviewStatus] = mapped_column(
        default=ReviewStatus.candidate, nullable=False
    )
    #: 完整度检查的产物：还缺哪些必填字段。空列表 = 完整
    missing_fields: Mapped[list | None] = mapped_column(JSONB)
    confidence: Mapped[float | None] = mapped_column(Float)
    rationale: Mapped[str | None] = mapped_column(Text)
    source: Mapped[AssetOrigin] = mapped_column(default=AssetOrigin.llm, nullable=False)


class ShotAssetBinding(Base, StdMixin):
    """镜头级素材绑定与临时状态覆盖。

    Override 不污染 Stage：脏污、伤痕、汗水这类一次性状态只写在这里，
    不回写素材本体，否则下一个镜头会继承上一个镜头的泥点。
    """

    __tablename__ = "shot_asset_bindings"
    __table_args__ = (
        Index("ix_shot_asset_bindings_shot", "shot_id"),
        Index("ix_shot_asset_bindings_entity", "entity_id"),
    )

    shot_id: Mapped[str] = mapped_column(
        ForeignKey("shots.id", ondelete="CASCADE"), nullable=False
    )
    entity_id: Mapped[str | None] = mapped_column(
        ForeignKey("world_entities.id", ondelete="SET NULL")
    )
    #: subject | background | prop | ambience
    binding_role: Mapped[str] = mapped_column(String(32), default="subject", nullable=False)
    asset_variant_ids: Mapped[list | None] = mapped_column(JSONB)
    #: {dirt, scars, sweat, wet, expression, pose}
    state_override_json: Mapped[dict | None] = mapped_column(JSONB)
    edited_by_human: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class DirectorProfile(Base, StdMixin):
    """导演包 —— 镜头语言与视觉叙事的风格档案。

    与 world_profile 的分工：
      world_profile     决定「画面里有什么」（名物、服饰、建筑）
      director_profile  决定「怎么拍」（景别、运镜、节奏、构图、光线）
    两者正交：昭和日本 × 小津式静态长镜，或 昭和日本 × 黑泽式动态多机位。
    """

    __tablename__ = "director_profiles"
    __table_args__ = (
        UniqueConstraint("code", "version", name="uq_director_profiles_code_version"),
    )

    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("director_profiles.id", ondelete="SET NULL")
    )
    novel_id: Mapped[str | None] = mapped_column(
        ForeignKey("novels.id", ondelete="CASCADE")
    )
    summary: Mapped[str | None] = mapped_column(Text)

    #: {shot_sizes: {ecu:.05, cu:.2, ms:.4,...}, movement: {...}, angle_bias, lens_mm}
    camera_json: Mapped[dict | None] = mapped_column(JSONB)
    #: {avg_shot_ms, rhythm, transitions: [], scene_open_with, scene_close_with}
    editing_json: Mapped[dict | None] = mapped_column(JSONB)
    #: {framing, symmetry, headroom, depth, negative_space}
    composition_json: Mapped[dict | None] = mapped_column(JSONB)
    #: {key_ratio, color_temp, contrast, palette, grain}
    lighting_json: Mapped[dict | None] = mapped_column(JSONB)
    #: 该导演风格要避免的东西
    avoid_json: Mapped[list | None] = mapped_column(JSONB)
    #: RAG：该导演风格的参考语料集合
    kb_collection_id: Mapped[str | None] = mapped_column(String(64))

    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
