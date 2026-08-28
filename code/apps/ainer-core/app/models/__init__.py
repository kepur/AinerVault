"""全部 ORM 模型。导入此模块即注册所有表到 Base.metadata。"""
from app.models.base import Base, StdMixin, TimestampMixin, utcnow
from app.models.asset_pack import (
    AssetKindSpec, AssetOrigin, AssetSpec, AssetVariant, DirectorProfile,
    ShotAssetBinding,
)
from app.models.content import Chapter, Novel, SourceFormat
from app.models.entity import EntityChapterState, EntityKind, WorldEntity
from app.models.gen import Asset, AssetKind, AssetSource, GenTask, TaskStatus
from app.models.narrative import StoryBeat, StyleHint
from app.models.narrative_device import (
    BackTranslationCheck, CulturalLoad, DeviceEffect, DeviceStrategy, DeviceType,
    NarrativeDevice,
)
from app.models.script import (
    TRANSLATABLE_TYPES, BlockType, DocMode, DocStatus, Scene, ScriptBlock,
    ScriptDoc,
)
from app.models.settings import (
    CapabilityEndpoint, CapabilityRoute, PromptTemplate, User,
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
