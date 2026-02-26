"""SKILL 08: Asset Matcher — Input/Output DTOs.

Full contract per SKILL_08_ASSET_MATCHER.md including:
- 7-component scoring (culture 0-25, semantic 0-25, era_genre 0-15, style 0-15,
  quality 0-10, backend 0-5, reuse 0-5)
- 6-level fallback cascade
- State machine: INIT → … → READY_FOR_PROMPT_PLANNER | REVIEW_REQUIRED | FAILED
- Quality thresholds per criticality level
- Conflict types for culture/era/style/backend/quality/consistency
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from ainern2d_shared.schemas.base import BaseSchema


# ── Enums & Constants ─────────────────────────────────────────────────────────

class MatchState(str, Enum):
    INIT = "INIT"
    PRECHECKING = "PRECHECKING"
    PRECHECK_READY = "PRECHECK_READY"
    PRIORITIZING = "PRIORITIZING"
    RETRIEVING_CANDIDATES = "RETRIEVING_CANDIDATES"
    SCORING_RANKING = "SCORING_RANKING"
    FALLBACK_PROCESSING = "FALLBACK_PROCESSING"
    ASSEMBLING_MANIFEST = "ASSEMBLING_MANIFEST"
    READY_FOR_PROMPT_PLANNER = "READY_FOR_PROMPT_PLANNER"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    FAILED = "FAILED"


class FallbackLevel(str, Enum):
    VARIANT_EXACT = "variant_exact"
    VARIANT_PARENT = "variant_same_pack_parent"
    ERA_SIMILAR = "variant_similar_era_genre"
    GENERIC = "generic_culturally_safe"
    PLACEHOLDER = "placeholder_to_generate"
    REVIEW = "manual_review_required"


class ConflictType(str, Enum):
    ASSET_CULTURE_CONFLICT = "ASSET_CULTURE_CONFLICT"
    ASSET_ERA_CONFLICT = "ASSET_ERA_CONFLICT"
    ASSET_STYLE_CONFLICT = "ASSET_STYLE_CONFLICT"
    ASSET_BACKEND_INCOMPATIBLE = "ASSET_BACKEND_INCOMPATIBLE"
    ASSET_QUALITY_BELOW_THRESHOLD = "ASSET_QUALITY_BELOW_THRESHOLD"
    CHARACTER_CONSISTENCY_RISK = "CHARACTER_CONSISTENCY_RISK"


class Criticality(str, Enum):
    CRITICAL = "critical"
    IMPORTANT = "important"
    NORMAL = "normal"
    BACKGROUND = "background"


QUALITY_THRESHOLDS: dict[str, float] = {
    "critical": 80.0,
    "important": 70.0,
    "normal": 60.0,
    "background": 45.0,
}

SCORE_WEIGHTS: dict[str, float] = {
    "culture": 25.0,
    "semantic": 25.0,
    "era_genre": 15.0,
    "style": 15.0,
    "quality": 10.0,
    "backend": 5.0,
    "reuse": 5.0,
}


# ── Sub-objects ───────────────────────────────────────────────────────────────

class FeatureFlags(BaseSchema):
    auto_placeholder: bool = True
    generic_fallback_policy: str = "allowed"  # allowed | restricted | disabled
    cross_culture_substitution: bool = False


class CultureConstraints(BaseSchema):
    required_culture_packs: list[str] = []
    forbidden_culture_packs: list[str] = []
    era_whitelist: list[str] = []
    era_blacklist: list[str] = []
    genre_whitelist: list[str] = []
    genre_blacklist: list[str] = []


class MatchingSummary(BaseSchema):
    total_entities: int = 0
    matched: int = 0
    matched_with_fallback: int = 0
    missing: int = 0
    review_required: int = 0


class ScoreBreakdown(BaseSchema):
    culture: float = 0.0
    semantic: float = 0.0
    era_genre: float = 0.0
    style: float = 0.0
    quality: float = 0.0
    backend: float = 0.0
    reuse: float = 0.0

    @property
    def total(self) -> float:
        return round(
            self.culture + self.semantic + self.era_genre
            + self.style + self.quality + self.backend + self.reuse,
            2,
        )


class CandidateAsset(BaseSchema):
    asset_id: str
    asset_type: str = "ref_image"
    source: str = "public_library"
    path_or_ref: str = ""
    culture_pack: str = ""
    style_tags: list[str] = []
    era_tags: list[str] = []
    genre_tags: list[str] = []
    visual_tags: list[str] = []
    backend_compatibility: list[str] = ["prompt_only"]
    quality_tier: str = "standard"
    score: float = 0.0
    score_breakdown: ScoreBreakdown = ScoreBreakdown()
    fallback_level: str = FallbackLevel.VARIANT_EXACT.value


class SelectedAsset(BaseSchema):
    asset_id: str
    asset_type: str  # ref_image | lora | scene_pack | sfx | ambience | template | placeholder
    source: str = "public_library"  # project_pack | public_library | generated_placeholder
    path_or_ref: str = ""
    culture_pack: str = ""
    style_tags: list[str] = []
    era_tags: list[str] = []
    backend_compatibility: list[str] = ["prompt_only"]
    quality_tier: str = "standard"
    license_or_usage_policy: str = ""


class AssetConflict(BaseSchema):
    conflict_type: str  # ConflictType value
    entity_uid: str = ""
    severity: str = "low"  # low | medium | high
    description: str = ""
    asset_id: str = ""


class EntityAssetMatch(BaseSchema):
    entity_uid: str
    entity_type: str = ""
    criticality: str = "normal"
    canonical_entity_specific: str = ""
    selected_variant_id: str = ""
    match_status: str = "matched"  # matched | matched_with_fallback | missing | review_required
    selected_asset: SelectedAsset | None = None
    candidate_assets: list[CandidateAsset] = []
    score_breakdown: ScoreBreakdown = ScoreBreakdown()
    fallback_used: bool = False
    fallback_level: str = ""
    warnings: list[str] = []
    conflicts: list[AssetConflict] = []


class AssetManifestGroup(BaseSchema):
    entity_uid: str
    asset_id: str
    use_as: str = ""


class AssetManifest(BaseSchema):
    for_prompt_planner: list[AssetManifestGroup] = []
    for_visual_render_planner: list[AssetManifestGroup] = []
    for_audio_planner: list[AssetManifestGroup] = []
    for_consistency_checker: list[AssetManifestGroup] = []


class MissingAsset(BaseSchema):
    entity_uid: str
    reason: str = ""
    placeholder_type: str = "prompt_only"  # prompt_only | reference_needed | manual_asset_required


class FallbackAction08(BaseSchema):
    entity_uid: str = ""
    action: str = ""
    fallback_level: str = ""
    from_variant: str = ""
    to_variant: str = ""


class ReviewRequiredItem(BaseSchema):
    entity_uid: str
    entity_type: str = ""
    criticality: str = "normal"
    reason: str = ""
    suggested_action: str = ""


# ── Input / Output ────────────────────────────────────────────────────────────

class Skill08Input(BaseSchema):
    # From SKILL 07
    canonical_entities: list[dict[str, Any]] = []
    entity_variant_mapping: list[dict[str, Any]] = []
    selected_culture_pack: dict[str, Any] = {}
    culture_constraints: dict[str, Any] = {}
    conflicts: list[dict[str, Any]] = []
    unresolved_entities: list[dict[str, Any]] = []
    # Config
    style_mode: str = ""  # realistic | anime | guochao | cyber | cinematic
    quality_profile: str = "standard"  # preview | standard | high
    global_render_profile: str = "MEDIUM_LOAD"  # LOW_LOAD | MEDIUM_LOAD | HIGH_LOAD
    backend_capability: list[str] = ["comfyui", "sdxl", "flux", "prompt_only"]
    user_preferences: dict[str, Any] = {}
    project_asset_pack: dict[str, Any] = {}
    feature_flags: dict[str, Any] = {}


class Skill08Output(BaseSchema):
    version: str = "1.0"
    status: str = "ready_for_prompt_planner"
    selected_culture_pack: dict[str, Any] = {}
    matching_summary: MatchingSummary = MatchingSummary()
    entity_asset_matches: list[EntityAssetMatch] = []
    asset_manifest: AssetManifest = AssetManifest()
    missing_assets: list[MissingAsset] = []
    fallback_actions: list[FallbackAction08] = []
    warnings: list[str] = []
    review_required_items: list[ReviewRequiredItem] = []
