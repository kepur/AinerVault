"""世界观转译层 —— 本系统第一稀缺能力。

中国古代 → 日本昭和 / 欧洲中世纪，四层映射：
  L1 人名   entity_world_names   （含 target_reading 与 family_key 家族姓氏一致性）
  L2 称谓   world_profiles.language_json.honorifics
  L3 名物   world_lexicon        ★ v1 完全缺失的一层
  L4 视觉   entity_world_visual

设计依据见 docs/v2/06_WORLDVIEW_TRANSLATION.md。
"""
from __future__ import annotations

from enum import Enum

from sqlalchemy import (
    Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, StdMixin


class ProfileRole(str, Enum):
    source = "source"
    target = "target"
    both = "both"


class ProfileStatus(str, Enum):
    draft = "draft"
    active = "active"
    archived = "archived"


class TransformStatus(str, Enum):
    draft = "draft"
    active = "active"
    archived = "archived"


class ReviewStatus(str, Enum):
    """转译条目的三级状态。locked 的条目任何重译都不会改动。"""

    candidate = "candidate"
    approved = "approved"
    locked = "locked"


class LexiconCategory(str, Enum):
    place = "place"
    office = "office"          # 职官：县令 → 代官 → bailiff
    title = "title"            # 头衔
    honorific = "honorific"    # 称谓：娘子 → 奥様 → milady
    garment = "garment"
    food = "food"
    currency = "currency"      # 铜钱 → 文 → silver penny
    weapon = "weapon"
    vehicle = "vehicle"
    architecture = "architecture"
    custom = "custom"          # 风俗
    ritual = "ritual"
    measure = "measure"        # 度量衡：里 → 里 → league
    other = "other"


class LexiconSource(str, Enum):
    template = "template"
    mined = "mined"
    rag = "rag"
    manual = "manual"


class NamingPolicy(str, Enum):
    transliteration = "transliteration"
    literal = "literal"
    cultural_equivalent = "cultural_equivalent"
    hybrid = "hybrid"


class ViolationKind(str, Enum):
    name_drift = "name_drift"
    name_family_conflict = "name_family_conflict"
    lexicon_miss = "lexicon_miss"
    forbidden_token = "forbidden_token"
    register_conflict = "register_conflict"
    era_conflict = "era_conflict"
    genre_conflict = "genre_conflict"
    costume_conflict = "costume_conflict"
    prop_region_conflict = "prop_region_conflict"
    architecture_conflict = "architecture_conflict"
    signage_conflict = "signage_conflict"
    social_norm_conflict = "social_norm_conflict"


class Severity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class ViolationStatus(str, Enum):
    open = "open"
    resolved = "resolved"
    ignored = "ignored"


class ViolationScope(str, Enum):
    block = "block"
    shot = "shot"
    entity = "entity"
    scene = "scene"


# ── L0 世界观档案 ──────────────────────────────────────────────────────────────

class WorldProfile(Base, StdMixin):
    """世界观档案。novel_id 为 NULL 表示全局模板，可被任何小说引用。

    parent_id 支持继承：jp_showa_rural 只需覆写差异项，其余继承 jp_showa。
    v1 借 CreativePolicyStack.stack_json 存放 culture pack，无法按 axes 检索，此处独立成表。
    """

    __tablename__ = "world_profiles"
    __table_args__ = (
        UniqueConstraint("code", "version", name="uq_world_profiles_code_version"),
        Index("ix_world_profiles_novel_status", "novel_id", "status"),
    )

    novel_id: Mapped[str | None] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[ProfileRole] = mapped_column(default=ProfileRole.both, nullable=False)
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("world_profiles.id", ondelete="SET NULL")
    )

    # {region, era, era_span:[from,to], genre, world_setting, social_context, tech_level}
    axes_json: Mapped[dict | None] = mapped_column(JSONB)
    # {visual_do[], visual_dont[], signage_rules{}, costume_norms{}, prop_norms{},
    #  architecture{}, palette[]}
    visual_json: Mapped[dict | None] = mapped_column(JSONB)
    # ★ v1 完全没有这块：{register, name_pattern, name_script, honorifics{},
    #                     forbidden_tokens[], numerals, date_style}
    language_json: Mapped[dict | None] = mapped_column(JSONB)

    kb_collection_id: Mapped[str | None] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[ProfileStatus] = mapped_column(default=ProfileStatus.draft, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


# ── 映射实例 ──────────────────────────────────────────────────────────────────

class WorldTransform(Base, StdMixin):
    """一本小说的一次世界观映射：source_profile → target_profile。

    一本书可同时挂多个 active transform（英文版走中世纪欧洲、日文版走昭和日本），
    共用同一套剧本与镜头，各自一套 L1–L4 映射。
    """

    __tablename__ = "world_transforms"
    __table_args__ = (
        UniqueConstraint(
            "novel_id", "target_language_code", "version", name="uq_wt_novel_lang_version"
        ),
        Index("ix_world_transforms_novel_status", "novel_id", "status"),
    )

    novel_id: Mapped[str] = mapped_column(
        ForeignKey("novels.id", ondelete="CASCADE"), nullable=False
    )
    target_language_code: Mapped[str] = mapped_column(String(16), nullable=False)
    source_profile_id: Mapped[str] = mapped_column(
        ForeignKey("world_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    target_profile_id: Mapped[str] = mapped_column(
        ForeignKey("world_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[TransformStatus] = mapped_column(
        default=TransformStatus.draft, nullable=False
    )
    # {naming_policy, honorific_policy, lexicon_policy, preserve_original_for[], strictness}
    policy_json: Mapped[dict | None] = mapped_column(JSONB)
    stats_json: Mapped[dict | None] = mapped_column(JSONB)


# ── L3 名物词表 ★ ─────────────────────────────────────────────────────────────

class WorldLexicon(Base, StdMixin):
    """名物转译表。v1 完全缺失，是「世界观只换了人名的皮」的修复点。

    canonical_key 是上位语义（place.lodging_venue），跨世界观稳定 ——
    它让一份词表可跨小说复用，是长期资产。
    """

    __tablename__ = "world_lexicon"
    __table_args__ = (
        UniqueConstraint("transform_id", "source_term", name="uq_lexicon_transform_source"),
        Index("ix_world_lexicon_canonical", "transform_id", "canonical_key"),
        Index("ix_world_lexicon_status", "transform_id", "status"),
        Index("ix_world_lexicon_category", "transform_id", "category"),
    )

    transform_id: Mapped[str] = mapped_column(
        ForeignKey("world_transforms.id", ondelete="CASCADE"), nullable=False
    )
    canonical_key: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[LexiconCategory] = mapped_column(
        default=LexiconCategory.other, nullable=False
    )
    source_term: Mapped[str] = mapped_column(String(256), nullable=False)
    source_aliases: Mapped[list | None] = mapped_column(JSONB)
    target_term: Mapped[str] = mapped_column(String(256), nullable=False)
    target_reading: Mapped[str | None] = mapped_column(String(256))  # 假名/罗马音，给 TTS
    # ★ 译文中出现即违规。闸二的执行依据。
    forbidden_targets: Mapped[list | None] = mapped_column(JSONB)

    status: Mapped[ReviewStatus] = mapped_column(default=ReviewStatus.candidate, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    rationale: Mapped[str | None] = mapped_column(Text)
    # {block_ids[], kb_doc_ids[], chapter_ids[]} —— 证据链，可点开看依据
    evidence_json: Mapped[dict | None] = mapped_column(JSONB)
    source: Mapped[LexiconSource] = mapped_column(default=LexiconSource.manual, nullable=False)
    hit_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class WorldLexiconTemplate(Base, StdMixin):
    """预置词表，解决冷启动。用户一键导入后再增删改，而不是从零手填。"""

    __tablename__ = "world_lexicon_templates"
    __table_args__ = (
        UniqueConstraint("pair_code", "version", name="uq_lexicon_tpl_pair_version"),
    )

    pair_code: Mapped[str] = mapped_column(String(128), nullable=False)  # cn_ancient__jp_showa
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    source_profile_code: Mapped[str] = mapped_column(String(64), nullable=False)
    target_profile_code: Mapped[str] = mapped_column(String(64), nullable=False)
    entries_json: Mapped[list] = mapped_column(JSONB, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


# ── L1 人名 ───────────────────────────────────────────────────────────────────

class EntityWorldName(Base, StdMixin):
    """实体 × 映射 的名字。

    family_key 是 v1 没有的一层：同 family_key 的实体在同一 transform 下必须共享姓氏映射。
    李清照与李格非同为 li_family，映射到昭和日本时姓氏统一，不会一个綾小路一个佐藤。
    生成候选时把整个家族一次性喂给模型，而不是逐个独立生成。
    """

    __tablename__ = "entity_world_names"
    __table_args__ = (
        UniqueConstraint("entity_id", "transform_id", name="uq_ewn_entity_transform"),
        Index("ix_entity_world_names_family", "transform_id", "family_key"),
        Index("ix_entity_world_names_status", "transform_id", "status"),
    )

    entity_id: Mapped[str] = mapped_column(
        ForeignKey("world_entities.id", ondelete="CASCADE"), nullable=False
    )
    transform_id: Mapped[str] = mapped_column(
        ForeignKey("world_transforms.id", ondelete="CASCADE"), nullable=False
    )
    target_name: Mapped[str] = mapped_column(String(256), nullable=False)
    target_reading: Mapped[str | None] = mapped_column(String(256))
    family_key: Mapped[str | None] = mapped_column(String(64))
    family_surname: Mapped[str | None] = mapped_column(String(128))
    naming_policy: Mapped[NamingPolicy] = mapped_column(
        default=NamingPolicy.cultural_equivalent, nullable=False
    )
    # [{name, reading, policy, rationale, register}]
    candidates_json: Mapped[list | None] = mapped_column(JSONB)
    rationale: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ReviewStatus] = mapped_column(default=ReviewStatus.candidate, nullable=False)
    locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


# ── L4 视觉变体 ───────────────────────────────────────────────────────────────

class EntityWorldVisual(Base, StdMixin):
    """实体 × 目标世界观 的视觉变体（继承 v1 的 EntityPromptVariant）。

    挂 world_profile_id 而非 transform_id：视觉只取决于目标世界观，与源世界观无关，
    可跨小说复用。同一个角色在昭和日本与中世纪欧洲是两套外观。
    """

    __tablename__ = "entity_world_visual"
    __table_args__ = (
        UniqueConstraint("entity_id", "world_profile_id", name="uq_ewv_entity_profile"),
    )

    entity_id: Mapped[str] = mapped_column(
        ForeignKey("world_entities.id", ondelete="CASCADE"), nullable=False
    )
    world_profile_id: Mapped[str] = mapped_column(
        ForeignKey("world_profiles.id", ondelete="CASCADE"), nullable=False
    )
    visual_prompt: Mapped[str | None] = mapped_column(Text)
    negative_prompt: Mapped[str | None] = mapped_column(Text)
    costume_note: Mapped[str | None] = mapped_column(Text)
    prop_note: Mapped[str | None] = mapped_column(Text)
    ref_asset_ids: Mapped[list | None] = mapped_column(JSONB)
    status: Mapped[ReviewStatus] = mapped_column(default=ReviewStatus.candidate, nullable=False)


# ── 违规 ──────────────────────────────────────────────────────────────────────

class WorldViolation(Base, StdMixin):
    """转译违规。扩展 v1 只覆盖人名的 consistency_warnings 到 12 类。

    high 且属关键实体 → 阻断进入素材生成（继承 SKILL_07 的 REVIEW_REQUIRED 语义）。
    """

    __tablename__ = "world_violations"
    __table_args__ = (
        Index("ix_world_violations_scope", "transform_id", "status", "severity"),
        Index("ix_world_violations_ref", "scope", "ref_id"),
    )

    transform_id: Mapped[str] = mapped_column(
        ForeignKey("world_transforms.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[ViolationKind] = mapped_column(nullable=False)
    severity: Mapped[Severity] = mapped_column(default=Severity.medium, nullable=False)
    scope: Mapped[ViolationScope] = mapped_column(default=ViolationScope.block, nullable=False)
    ref_id: Mapped[str | None] = mapped_column(String(32))
    detected: Mapped[str] = mapped_column(String(512), nullable=False)
    expected: Mapped[str | None] = mapped_column(String(512))
    suggested_fix: Mapped[str | None] = mapped_column(Text)
    evidence_json: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[ViolationStatus] = mapped_column(
        default=ViolationStatus.open, nullable=False
    )
