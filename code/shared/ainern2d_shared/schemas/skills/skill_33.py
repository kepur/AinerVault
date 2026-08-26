"""SKILL 33: Prompt Asset Library & Character Growth Continuity — DTOs.

Four-layer model: Character Core → Character Stage → Shot State Override → Prompt Snapshot
"""
from __future__ import annotations

from typing import Any

from ainern2d_shared.schemas.base import BaseSchema


# ── Feature Flags ─────────────────────────────────────────────────────────────

class Skill33FeatureFlags(BaseSchema):
    enable_core_building: bool = True
    enable_stage_resolving: bool = True
    enable_asset_assembling: bool = True
    enable_shot_binding: bool = True
    enable_snapshot_export: bool = True
    enable_consistency_check: bool = True


# ── Character Core (read from EntityContinuityProfile) ────────────────────────

class CharacterCoreProfile(BaseSchema):
    entity_id: str
    entity_label: str = ""
    entity_type: str = "character"
    anchors: dict[str, Any] = {}  # from EntityContinuityProfile.anchors_json
    rules: dict[str, Any] = {}    # from EntityContinuityProfile.rules_json
    base_appearance: dict[str, Any] = {}
    base_temperament: dict[str, Any] = {}
    forbidden: list[str] = []
    must_not: list[str] = []


# ── Character Stage ───────────────────────────────────────────────────────────

class CharacterStageOut(BaseSchema):
    stage_id: str = ""
    entity_id: str
    stage_name: str = ""
    chapter_start: int = 1
    chapter_end: int | None = None
    appearance_override: dict[str, Any] = {}
    temperament_override: dict[str, Any] = {}
    default_costume_asset_id: str | None = None
    default_prop_asset_ids: list[str] = []
    emotional_baseline: dict[str, Any] = {}
    status_tags: list[str] = []


# ── Semantic Asset ────────────────────────────────────────────────────────────

class SemanticAssetOut(BaseSchema):
    asset_id: str = ""
    novel_id: str = ""
    entity_id: str | None = None
    asset_type: str = ""
    canonical_name: str = ""
    aliases: list[str] = []
    tags: list[str] = []
    status: str = "draft"
    structured: dict[str, Any] = {}
    prompt: dict[str, Any] = {}
    negative_prompt: dict[str, Any] = {}
    is_active: bool = True


# ── Shot Asset Binding ────────────────────────────────────────────────────────

class ShotAssetBindingOut(BaseSchema):
    binding_id: str = ""
    chapter_id: str = ""
    shot_id: str = ""
    entity_id: str | None = None
    binding_role: str = "subject"
    stage_profile_id: str | None = None
    selected_asset_ids: list[str] = []
    state_override: dict[str, Any] = {}
    prompt_snapshot_id: str | None = None


# ── Prompt Snapshot Seed ──────────────────────────────────────────────────────

class PromptSnapshotSeed(BaseSchema):
    shot_id: str = ""
    entity_id: str | None = None
    source_type: str = "auto"
    core_layer: dict[str, Any] = {}
    stage_layer: dict[str, Any] = {}
    override_layer: dict[str, Any] = {}
    asset_layers: list[dict[str, Any]] = []
    merged_prompt_text: str = ""
    merged_negative_prompt_text: str = ""
    consistency_hash: str = ""


# ── Consistency Rule ──────────────────────────────────────────────────────────

class ConsistencyRule(BaseSchema):
    entity_id: str
    rule_type: str = ""  # forbidden/must_not/anchor
    description: str = ""
    source: str = ""  # core/stage/policy


# ── Review Item ───────────────────────────────────────────────────────────────

class ReviewRequiredItem33(BaseSchema):
    item_type: str = ""  # forbidden_hit/must_not_violation/missing_asset/low_confidence
    entity_id: str = ""
    shot_id: str = ""
    description: str = ""
    severity: str = "warning"  # warning/error


# ── Skill 33 Input / Output ──────────────────────────────────────────────────

class Skill33Input(BaseSchema):
    tenant_id: str
    project_id: str
    novel_id: str
    chapter_ids: list[str] = []
    run_id: str | None = None
    shot_plan: list[dict[str, Any]] = []
    entity_registry_resolution: dict[str, Any] = {}
    entity_canonicalization_result: dict[str, Any] = {}
    user_overrides: dict[str, Any] = {}
    feature_flags: Skill33FeatureFlags = Skill33FeatureFlags()


class Skill33Output(BaseSchema):
    status: str = "INIT"
    character_core_profiles: list[CharacterCoreProfile] = []
    character_stage_profiles: list[CharacterStageOut] = []
    semantic_assets: list[SemanticAssetOut] = []
    shot_asset_bindings: list[ShotAssetBindingOut] = []
    prompt_snapshot_seeds: list[PromptSnapshotSeed] = []
    consistency_rules: list[ConsistencyRule] = []
    warnings: list[str] = []
    review_required_items: list[ReviewRequiredItem33] = []
