"""全部 ORM 模型。导入此模块即注册所有表到 Base.metadata。"""
from app.models.base import Base, StdMixin, TimestampMixin, utcnow
from app.models.asset_pack import (
    AssetKindSpec, AssetOrigin, AssetSpec, AssetVariant, DirectorProfile,
    ShotAssetBinding,
)
from app.models.asset_epoch import (
    INVARIANT_FIELDS, VARIANT_FIELDS, AssetEpoch, EpochBinding, EpochKind,
)
from app.models.appellation import EntityAppellation, REGISTER_BRIEF, Register
from app.models.content import Chapter, Novel, SourceFormat
from app.models.culture_review import (
    CultureFinding, CultureReview, GapKind, ReviewRunStatus, Verdict,
)
from app.models.entity import (
    EntityChapterState, EntityKind, NameType, WorldEntity,
)
from app.models.gen import Asset, AssetKind, AssetSource, GenTask, TaskStatus
from app.models.meme import MemeEntry, MemeRegister, MemeRendering
from app.models.narrative import StoryBeat, StyleHint
from app.models.narrative_device import (
    BackTranslationCheck, CulturalLoad, DeviceEffect, DeviceStrategy, DeviceType,
    NarrativeDevice, PlotLoad, STRATEGY_BRIEF, Volatility, choose_strategy,
    strategy_brief,
)
from app.models.performance import (
    Facing, ShotPerformance, SpeechRole, StagePosition,
)
from app.models.script import (
    TRANSLATABLE_TYPES, BlockType, DocMode, DocStatus, Scene, ScriptBlock,
    ScriptDoc,
)
from app.models.settings import (
    DEFAULT_TIER, CapabilityEndpoint, CapabilityRoute, PromptTemplate,
    QualityTier, User,
)
from app.models.shot import (
    AudioKind, AudioSpec, FrameRole, FrameSpec, Shot, ShotPlan, SpecStatus,
)
from app.models.translation import (
    CandidateStatus, ConsistencyMode, ConsistencyWarning, GlossaryCandidate,
    GlossaryTerm, NovelTranslationSettings, RunStatus, TermStatus, TermType,
    TranslationBlock, TranslationBlockStatus, TranslationRun, WarningStatus, WarningType,
)
from app.models.world import (
    EntityWorldName, EntityWorldVisual, LexiconCategory, LexiconSource, NamingPolicy,
    ProfileRole, ProfileStatus, ReviewStatus, Severity, TransformStatus, ViolationKind,
    ViolationScope, ViolationStatus, WorldLexicon, WorldLexiconTemplate, WorldProfile,
    WorldTransform, WorldViolation,
)

__all__ = [
    "Base", "StdMixin", "TimestampMixin", "utcnow",
    "EntityAppellation", "Register", "REGISTER_BRIEF",
    "MemeEntry", "MemeRendering", "MemeRegister",
    "AssetEpoch", "EpochBinding", "EpochKind",
    "INVARIANT_FIELDS", "VARIANT_FIELDS",
    "CultureReview", "CultureFinding", "GapKind", "Verdict", "ReviewRunStatus",
    "ShotPerformance", "SpeechRole", "StagePosition", "Facing",
    "NameType",
    "QualityTier", "DEFAULT_TIER",
    "PlotLoad", "Volatility", "choose_strategy",
    "STRATEGY_BRIEF", "strategy_brief",
    "Novel", "Chapter", "SourceFormat",
    "AssetSpec", "AssetVariant", "ShotAssetBinding", "DirectorProfile",
    "AssetKindSpec", "AssetOrigin",
    "ScriptDoc", "Scene", "ScriptBlock", "BlockType", "DocStatus", "DocMode",
    "TRANSLATABLE_TYPES",
    "NovelTranslationSettings", "TranslationRun", "TranslationBlock",
    "TranslationBlockStatus", "ConsistencyMode", "RunStatus",
    "GlossaryTerm", "GlossaryCandidate", "TermStatus", "TermType", "CandidateStatus",
    "ConsistencyWarning", "WarningType", "WarningStatus",
    "WorldProfile", "WorldTransform", "WorldLexicon", "WorldLexiconTemplate",
    "EntityWorldName", "EntityWorldVisual", "WorldViolation",
    "ProfileRole", "ProfileStatus", "TransformStatus", "ReviewStatus",
    "LexiconCategory", "LexiconSource", "NamingPolicy",
    "ViolationKind", "ViolationScope", "ViolationStatus", "Severity",
    "WorldEntity", "EntityChapterState", "EntityKind",
    "StoryBeat", "StyleHint",
    "NarrativeDevice", "BackTranslationCheck",
    "DeviceType", "DeviceEffect", "CulturalLoad", "DeviceStrategy",
    "ShotPlan", "Shot", "FrameSpec", "AudioSpec", "FrameRole", "AudioKind", "SpecStatus",
    "GenTask", "Asset", "TaskStatus", "AssetKind", "AssetSource",
    "CapabilityEndpoint", "CapabilityRoute", "PromptTemplate", "User",
]
