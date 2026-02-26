"""SKILL 08: Asset Matcher — Input/Output DTOs."""
from __future__ import annotations

from ainern2d_shared.schemas.base import BaseSchema


# ── Sub-objects ───────────────────────────────────────────────────────────────

class MatchingSummary(BaseSchema):
    total_entities: int = 0
    matched: int = 0
    matched_with_fallback: int = 0
    missing: int = 0
    review_required: int = 0


class SelectedAsset(BaseSchema):
    asset_id: str
    asset_type: str  # ref_image | lora | scene_pack | sfx | ambience | template | placeholder
    source: str = "public_library"
    path_or_ref: str = ""
    culture_pack: str = ""
    style_tags: list[str] = []
    era_tags: list[str] = []
    backend_compatibility: list[str] = ["prompt_only"]
    quality_tier: str = "standard"


class CandidateAsset(BaseSchema):
    asset_id: str
    score: float = 0.0


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
        return self.culture + self.semantic + self.era_genre + self.style + self.quality + self.backend + self.reuse


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
    warnings: list[str] = []


class AssetManifestGroup(BaseSchema):
    entity_uid: str
    asset_id: str
    use_as: str = ""


class AssetManifest(BaseSchema):
    for_prompt_planner: list[AssetManifestGroup] = []
    for_visual_render_planner: list[AssetManifestGroup] = []
    for_audio_planner: list[AssetManifestGroup] = []


class MissingAsset(BaseSchema):
    entity_uid: str
    reason: str = ""
    placeholder_type: str = "prompt_only"  # prompt_only | reference_needed | manual_asset_required


class FallbackAction08(BaseSchema):
    entity_uid: str = ""
    action: str = ""


# ── Input / Output ────────────────────────────────────────────────────────────

class Skill08Input(BaseSchema):
    # From SKILL 07
    canonical_entities: list[dict] = []
    entity_variant_mapping: list[dict] = []
    selected_culture_pack: dict = {}
    culture_constraints: dict = {}
    conflicts: list[dict] = []
    unresolved_entities: list[dict] = []
    # Config
    style_mode: str = ""
    quality_profile: str = "standard"  # preview | standard | high
    global_render_profile: str = "MEDIUM_LOAD"
    backend_capability: list[str] = ["comfyui", "sdxl", "flux", "prompt_only"]
    user_preferences: dict = {}
    project_asset_pack: dict = {}
    feature_flags: dict = {}


class Skill08Output(BaseSchema):
    selected_culture_pack: dict = {}
    matching_summary: MatchingSummary = MatchingSummary()
    entity_asset_matches: list[EntityAssetMatch] = []
    asset_manifest: AssetManifest = AssetManifest()
    missing_assets: list[MissingAsset] = []
    fallback_actions: list[FallbackAction08] = []
    warnings: list[str] = []
    review_required_items: list[str] = []
    status: str = "ready_for_prompt_planner"
