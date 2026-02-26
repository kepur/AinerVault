"""SKILL 10: Prompt Planner — Input/Output DTOs.

Full prompt-plan contract per SKILL_10_PROMPT_PLANNER.md §17.
Covers: 9-layer architecture, micro-shot plans, backend presets,
LoRA/embedding injection, negative layers, RAG recipe, fallback,
token budget, consistency scoring, feature flags, user overrides.
"""
from __future__ import annotations

from typing import Any

from ainern2d_shared.schemas.base import BaseSchema


# ── Feature Flags & User Overrides ───────────────────────────────────────────


class Skill10FeatureFlags(BaseSchema):
    """Runtime feature toggles for prompt generation (§3.2)."""

    prompt_format_version: str = "1.0"
    enable_lora_injection: bool = True
    negative_prompt_mode: str = "layered"  # layered | flat | off
    token_budget_strict: bool = False
    enable_prompt_layer_export: bool = True
    enable_model_specific_variants: bool = True
    enable_negative_prompt_auto_expand: bool = True
    enable_prompt_fallback_variants: bool = True


class Skill10UserOverrides(BaseSchema):
    """User-specified overrides for prompt generation (§3.2)."""

    style_override: str = ""
    negative_prompt_append: list[str] = []
    quality_preset_override: str = ""
    forced_culture_fragments: list[str] = []
    forced_entity_descriptions: dict[str, str] = {}


# ── Backend Capability ───────────────────────────────────────────────────────


class BackendCapability(BaseSchema):
    """Target execution backend description (§3.2)."""

    backend_id: str = "comfyui"  # comfyui | sdxl | flux
    supported_models: list[str] = []
    supported_lora: bool = True
    supported_controlnet: bool = True
    max_prompt_tokens: int = 77
    supported_modes: list[str] = ["T2I", "I2V_START_END"]
    preset_catalog_ids: list[str] = []


# ── RAG Recipe Context ───────────────────────────────────────────────────────


class RAGRecipeContext(BaseSchema):
    """Recipe context from SKILL 02 / KB for prompt injection (§23)."""

    kb_version_id: str = ""
    recipe_id: str = ""
    retrieved_item_ids: list[str] = []
    constraint_conflict_flags: list[str] = []
    hard_constraints: list[str] = []
    soft_hints: list[str] = []
    role_filter: list[str] = []
    tag_filter: list[str] = []


# ── 9-Layer Prompt Architecture (§6) ────────────────────────────────────────


class PromptLayers(BaseSchema):
    """Positive prompt layers — 9-layer architecture per §6.1.

    Order: base → cultural → entity → shot → motion →
           lighting_mood → quality → consistency_anchor
    (negative_constraints stored separately in NegativeLayers)
    """

    base: list[str] = []
    cultural: list[str] = []
    entity: list[str] = []
    shot: list[str] = []
    motion: list[str] = []
    lighting_mood: list[str] = []
    quality: list[str] = []
    consistency_anchor: list[str] = []


class NegativeLayers(BaseSchema):
    """Layered negative prompts per §13.1."""

    global_negative: list[str] = []
    culture_negative: list[str] = []
    entity_negative: list[str] = []
    motion_negative: list[str] = []
    model_specific_negative: list[str] = []


# ── Assembly & Traceability ──────────────────────────────────────────────────


class AssemblyRules(BaseSchema):
    """How to compose the final prompt string from layers (§11)."""

    positive_order: list[str] = [
        "base", "cultural", "entity", "shot", "motion",
        "lighting_mood", "quality", "consistency_anchor",
    ]
    negative_order: list[str] = [
        "global_negative", "culture_negative",
        "entity_negative", "motion_negative",
    ]
    separator: str = ", "


class DerivedFrom(BaseSchema):
    """Upstream traceability references."""

    asset_match_refs: list[str] = []
    visual_render_plan_ref: str = ""
    continuity_anchor_refs: list[str] = []
    persona_runtime_ref: str = ""


# ── Consistency Anchors (§14) ────────────────────────────────────────────────


class GlobalConsistencyAnchors(BaseSchema):
    scene_anchor_ids: list[str] = []
    character_anchor_ids: list[str] = []


# ── Shot & Micro-shot Prompt Plans (§17.3 / §17.4) ──────────────────────────


class ShotPromptPlan(BaseSchema):
    """Prompt plan for a single shot."""

    shot_id: str
    scene_id: str = ""
    criticality: str = "normal"  # normal | high | critical
    prompt_layers: PromptLayers = PromptLayers()
    negative_layers: NegativeLayers = NegativeLayers()
    consistency_anchors: list[str] = []
    derived_from: DerivedFrom = DerivedFrom()
    assembly_rules: AssemblyRules = AssemblyRules()
    lora_triggers: list[str] = []
    embedding_tokens: list[str] = []
    token_budget_used: int = 0
    token_budget_limit: int = 77
    warnings: list[str] = []


class MicroshotOverrides(BaseSchema):
    motion: list[str] = []
    shot: list[str] = []
    quality: list[str] = []


class MicroshotPromptPlan(BaseSchema):
    """Prompt plan for a micro-shot (§17.4)."""

    microshot_id: str
    parent_shot_id: str
    criticality: str = "normal"
    inherits_from_shot_layers: bool = True
    overrides: MicroshotOverrides = MicroshotOverrides()
    prompt_layers: PromptLayers = PromptLayers()
    negative_layers: NegativeLayers = NegativeLayers()
    alignment_points: list[int] = []
    lora_triggers: list[str] = []
    embedding_tokens: list[str] = []
    token_budget_used: int = 0
    warnings: list[str] = []


# ── Model Variants (§17.5) ──────────────────────────────────────────────────


class KeyframePrompt(BaseSchema):
    slot: str  # start | mid | end | frame_N
    prompt: str = ""


class ParameterHints(BaseSchema):
    style_strength: str = "medium"
    motion_strength: str = "medium"
    guidance_hint: str = "balanced"
    quality_priority: str = "standard"


class LengthEstimate(BaseSchema):
    positive_tokens: int = 0
    negative_tokens: int = 0
    positive_chars: int = 0
    negative_chars: int = 0


class ModelVariant(BaseSchema):
    """Model-specific prompt variant."""

    variant_id: str
    target_type: str = "shot"  # shot | microshot
    target_id: str = ""
    model_mode: str = "T2I"  # T2I | I2V_START_END | I2V_START_MID_END | …
    positive_prompt: str = ""
    negative_prompt: str = ""
    keyframe_prompts: list[KeyframePrompt] = []
    parameter_hints: ParameterHints = ParameterHints()
    length_estimate: LengthEstimate = LengthEstimate()
    preset_mapping_ref: str = ""


# ── Preset Mapping (§17.6 / §16) ────────────────────────────────────────────


class PresetModeMapping(BaseSchema):
    preset_id_hint: str = ""
    keyframe_prompt_slots: list[str] = []
    reference_image_refs: list[str] = []
    positive_prompt_field: str = "prompt"
    negative_prompt_field: str = "negative_prompt"
    style_lora_refs: list[str] = []
    control_hints: dict[str, Any] = {}


class PresetMappingHints(BaseSchema):
    """ComfyUI / executor mapping hints (§17.6)."""

    default_mappings: dict[str, str] = {
        "positive_prompt_field": "prompt",
        "negative_prompt_field": "negative_prompt",
    }
    per_model_mode_mappings: dict[str, PresetModeMapping] = {}
    fallback_mappings: dict[str, PresetModeMapping] = {}


# ── Fallback Actions (§17.7) ────────────────────────────────────────────────


class FallbackPromptAction(BaseSchema):
    target_type: str = "shot"  # shot | microshot
    target_id: str = ""
    action: str = ""  # simplify_entity_layer | reduce_motion_complexity | …
    reason_tags: list[str] = []
    before_summary: str = ""
    after_summary: str = ""


# ── Prompt Consistency Scoring ───────────────────────────────────────────────


class PromptConsistencyScore(BaseSchema):
    """Cross-shot consistency score within a scene."""

    scene_id: str = ""
    character_consistency: float = 1.0
    environment_consistency: float = 1.0
    lighting_consistency: float = 1.0
    overall_score: float = 1.0
    issues: list[str] = []


# ── Summary & Review ────────────────────────────────────────────────────────


class PromptPlanSummary(BaseSchema):
    total_shots: int = 0
    total_microshots: int = 0
    model_variants_generated: int = 0
    fallback_prompt_actions: int = 0
    review_required: int = 0
    avg_consistency_score: float = 1.0


class ReviewRequiredItem(BaseSchema):
    target_type: str = "shot"
    target_id: str = ""
    reason: str = ""
    severity: str = "medium"  # low | medium | high


# ── Global Prompt Constraints (§17.2) ────────────────────────────────────────


class GlobalPromptConstraints(BaseSchema):
    selected_culture_pack: str = "generic"
    global_positive_fragments: list[str] = []
    global_negative_fragments: list[str] = []
    style_mode: str = ""
    quality_profile: str = "standard"  # preview | standard | final
    global_consistency_anchors: GlobalConsistencyAnchors = GlobalConsistencyAnchors()
    continuity_anchor_ids: list[str] = []
    persona_runtime_ref: str = ""
    persona_style_ref: str = ""
    persona_policy_ref: str = ""
    persona_critic_ref: str = ""
    user_overrides_applied: list[str] = []
    rag_recipe_applied: RAGRecipeContext | None = None


# ── Input / Output ───────────────────────────────────────────────────────────


class Skill10Input(BaseSchema):
    """Prompt Planner inputs (§3)."""

    # Required — from SKILL 07 / 08 / 09
    entity_canonicalization_result: dict = {}
    asset_match_result: dict = {}
    visual_render_plan: dict = {}
    shot_plan: dict = {}
    entity_registry_continuity_result: dict = {}
    continuity_exports: dict = {}
    persona_dataset_index_result: dict = {}
    active_persona_ref: str = ""

    # Optional context
    story_context: dict = {}
    character_consistency_profile: dict = {}
    style_mode: str = ""
    model_target: str = "T2I"
    backend_capability: BackendCapability = BackendCapability()
    comfyui_preset_catalog: dict = {}
    quality_profile: str = "standard"
    user_overrides: Skill10UserOverrides = Skill10UserOverrides()
    feature_flags: Skill10FeatureFlags = Skill10FeatureFlags()
    recipe_context: RAGRecipeContext | None = None


class Skill10Output(BaseSchema):
    """Prompt plan output contract (§17.1)."""

    version: str = "1.0"
    status: str = "ready_for_prompt_execution"
    prompt_plan_summary: PromptPlanSummary = PromptPlanSummary()
    global_prompt_constraints: GlobalPromptConstraints = GlobalPromptConstraints()
    shot_prompt_plans: list[ShotPromptPlan] = []
    microshot_prompt_plans: list[MicroshotPromptPlan] = []
    model_variants: list[ModelVariant] = []
    preset_mapping_hints: PresetMappingHints = PresetMappingHints()
    fallback_prompt_actions: list[FallbackPromptAction] = []
    consistency_scores: list[PromptConsistencyScore] = []
    warnings: list[str] = []
    review_required_items: list[ReviewRequiredItem] = []
