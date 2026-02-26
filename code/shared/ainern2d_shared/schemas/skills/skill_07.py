"""SKILL 07: Entity Canonicalization & Cultural Binding — Input/Output DTOs."""
from __future__ import annotations

from ainern2d_shared.schemas.base import BaseSchema


# ── Sub-objects ───────────────────────────────────────────────────────────────

class SelectedCulturePack(BaseSchema):
    id: str
    locale: str = ""
    era: str = ""
    genre: str = ""
    source: str = ""  # user_override | genre+world_setting | default | language_hint


class CultureConstraints(BaseSchema):
    visual_do: list[str] = []
    visual_dont: list[str] = []
    signage_rules: list[str] = []
    hard_constraints: list[str] = []
    soft_preferences: list[str] = []


class RoutingReasoningSummary(BaseSchema):
    reason_tags: list[str] = []
    confidence: float = 0.0


class CanonicalEntityFull(BaseSchema):
    entity_uid: str
    entity_type: str
    surface_form: str = ""
    source_mentions: list[str] = []
    canonical_entity_root: str = ""
    canonical_entity_specific: str = ""
    attributes: dict = {}
    scene_scope: list[str] = []


class EntityVariantMapping(BaseSchema):
    entity_uid: str
    canonical_entity_specific: str = ""
    selected_variant_id: str = ""
    variant_display_name: str = ""
    culture_pack: str = ""
    match_confidence: float = 0.0
    visual_traits: list[str] = []
    prompt_template_refs: list[str] = []
    asset_refs: list[str] = []
    fallback_used: bool = False


class ConflictItem(BaseSchema):
    conflict_type: str  # ERA_CONFLICT | GENRE_CONFLICT | LANGUAGE_SIGNAGE_CONFLICT | etc.
    entity_uid: str = ""
    severity: str = "low"  # low | medium | high
    description: str = ""
    suggested_fix: str = ""


class UnresolvedEntity(BaseSchema):
    entity_uid: str
    reason: str = ""
    severity: str = "low"
    suggested_fallback: str = ""
    requires_review: bool = False


class FallbackAction07(BaseSchema):
    entity_uid: str = ""
    action: str = ""


class CultureBindingTrace(BaseSchema):
    culture_pack_id: str = ""
    constraint_source_item_ids: list[str] = []
    kb_version_id: str = ""


# ── Input / Output ────────────────────────────────────────────────────────────

class Skill07Input(BaseSchema):
    # From SKILL 04
    entities: list[dict] = []
    entity_aliases: list[dict] = []
    # From SKILL 03
    shots: list[dict] = []
    scenes: list[dict] = []
    # From SKILL 02
    culture_candidates: list[dict] = []
    language_route: dict = {}
    # Context
    genre: str = ""
    story_world_setting: str = ""
    time_period: str = ""
    target_language: str = "zh-CN"
    target_locale: str = ""
    style_mode: str = ""
    user_override: dict = {}
    feature_flags: dict = {}


class Skill07Output(BaseSchema):
    selected_culture_pack: SelectedCulturePack = SelectedCulturePack(id="generic")
    routing_reasoning_summary: RoutingReasoningSummary = RoutingReasoningSummary()
    culture_constraints: CultureConstraints = CultureConstraints()
    canonical_entities: list[CanonicalEntityFull] = []
    entity_variant_mapping: list[EntityVariantMapping] = []
    conflicts: list[ConflictItem] = []
    unresolved_entities: list[UnresolvedEntity] = []
    fallback_actions: list[FallbackAction07] = []
    culture_binding_trace: CultureBindingTrace = CultureBindingTrace()
    warnings: list[str] = []
    status: str = "ready_for_asset_match"
