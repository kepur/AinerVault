"""SKILL 14: Persona & Style Pack Manager — Input/Output DTOs.

Covers:
  - Style DNA (structured visual-parameter axes)
  - Persona manifest (visual / voice / behavioral identity)
  - Inheritance chain resolution & conflict detection
  - Version management (semver, diff, rollback)
  - CRUD + clone + compare operations
  - Export formats (json / prompt_fragment / comfyui / lora_recipe)
  - Feature flags & culture-pack integration
"""
from __future__ import annotations

from typing import Any

from ainern2d_shared.schemas.base import BaseSchema


# ── Style DNA sub-structures ──────────────────────────────────────────────────

class ColorPalette(BaseSchema):
    primary: str = "#000000"
    secondary: str = "#333333"
    accent: str = "#FF5500"
    neutral: str = "#CCCCCC"


class LineStyle(BaseSchema):
    weight: float = 1.0          # 0.1 – 5.0
    texture: str = "smooth"      # smooth | rough | sketchy | clean
    consistency: float = 0.9     # 0.0 – 1.0


class TextureProfile(BaseSchema):
    grain: float = 0.0           # 0.0 – 1.0
    noise: float = 0.0
    smoothness: float = 1.0


class ProportionRules(BaseSchema):
    head_body_ratio: float = 0.14   # realistic ≈ 0.125
    limb_style: str = "realistic"   # realistic | stylised | chibi


class MotionStyle(BaseSchema):
    squash_stretch_factor: float = 0.0  # 0 = off, 1 = full cartoon
    anticipation_frames: int = 0


class StyleDNA(BaseSchema):
    """Structured visual-parameter axes."""
    color_palette: ColorPalette = ColorPalette()
    line_style: LineStyle = LineStyle()
    shading_method: str = "flat"         # flat | cel | gradient | realistic
    texture_profile: TextureProfile = TextureProfile()
    proportion_rules: ProportionRules = ProportionRules()
    motion_style: MotionStyle = MotionStyle()
    # Director-level creative axes (0.0 – 1.0)
    cut_density: float = 0.5
    motion_aggressiveness: float = 0.5
    dialogue_patience: float = 0.5
    atmospheric_hold_preference: float = 0.5
    impact_alignment_priority: float = 0.5
    symmetry_preference: float = 0.5


# ── Persona identity sub-structures ──────────────────────────────────────────

class FaceFeatures(BaseSchema):
    shape: str = "oval"
    eyes: str = "standard"
    distinctive_marks: list[str] = []


class VisualIdentity(BaseSchema):
    face_features: FaceFeatures = FaceFeatures()
    body_type: str = "average"       # slim | average | muscular | heavy
    outfit_default: str = ""
    color_scheme: ColorPalette = ColorPalette()


class VoiceIdentity(BaseSchema):
    pitch: str = "medium"            # low | medium | high
    speed: float = 1.0               # multiplier
    accent: str = ""


class BehavioralTraits(BaseSchema):
    gesture_style: str = "neutral"   # neutral | expressive | restrained
    expression_default: str = "calm" # calm | cheerful | stern | mysterious


class PersonaManifest(BaseSchema):
    visual_identity: VisualIdentity = VisualIdentity()
    voice_identity: VoiceIdentity = VoiceIdentity()
    behavioral_traits: BehavioralTraits = BehavioralTraits()


# ── Version & inheritance ─────────────────────────────────────────────────────

class PersonaVersion(BaseSchema):
    version: str = "0.1.0"           # semver
    changelog: str = ""
    parent_version: str = ""         # for rollback
    snapshot: dict[str, Any] = {}    # frozen field snapshot


class ConflictItem(BaseSchema):
    field_path: str = ""             # e.g. "style_dna.shading_method"
    parent_value: Any = None
    child_value: Any = None
    severity: str = "warn"           # warn | error
    description: str = ""


class InheritanceNode(BaseSchema):
    pack_id: str = ""
    layer: str = "base"              # base | culture | genre | project | user_override
    version: str = ""


# ── RAG / Policy / Critic overrides ──────────────────────────────────────────

class RAGRecipeOverride(BaseSchema):
    director_top_k: int = 5
    cinematographer_top_k: int = 5
    editor_top_k: int = 5
    extra: dict[str, Any] = {}


class PolicyOverride(BaseSchema):
    prefer_microshots_in_high_motion: bool = False
    max_dialogue_hold_ms_in_action: int = 1200
    extra: dict[str, Any] = {}


class CriticThresholdOverride(BaseSchema):
    motion_readability_min: float = 0.7
    extra: dict[str, Any] = {}


# ── Feature flags ─────────────────────────────────────────────────────────────

class Skill14FeatureFlags(BaseSchema):
    enable_inheritance: bool = True
    auto_resolve_conflicts: bool = False
    strict_version_control: bool = False
    max_chain_depth: int = 5


# ── Export helpers ────────────────────────────────────────────────────────────

class ExportRequest(BaseSchema):
    format: str = "json"             # json | prompt_fragment | comfyui | lora_recipe


class ExportResult(BaseSchema):
    format: str = "json"
    payload: dict[str, Any] = {}
    prompt_fragment: str = ""


# ── Style consistency check ───────────────────────────────────────────────────

class EntityStyleEntry(BaseSchema):
    entity_uid: str = ""
    applied_pack_id: str = ""
    shading_method: str = ""
    line_weight: float = 0.0


class ConsistencyIssue(BaseSchema):
    entity_uid: str = ""
    field: str = ""
    expected: str = ""
    actual: str = ""
    severity: str = "warn"


# ── Persona Pack (top-level domain object) ────────────────────────────────────

class PersonaPack(BaseSchema):
    persona_pack_id: str = ""
    display_name: str = ""
    base_role: str = "director"      # director | cinematographer | editor
    inherits_from: list[str] = []    # ordered parent pack ids
    status: str = "draft"            # draft | active | archived | stale_eval
    style_dna: StyleDNA = StyleDNA()
    persona_manifest: PersonaManifest = PersonaManifest()
    rag_recipe_override: RAGRecipeOverride = RAGRecipeOverride()
    policy_override: PolicyOverride = PolicyOverride()
    critic_threshold_override: CriticThresholdOverride = CriticThresholdOverride()
    versions: list[PersonaVersion] = []
    current_version: str = "0.1.0"
    tags: list[str] = []


# ── Culture pack reference (from SKILL 07) ───────────────────────────────────

class CulturePackRef(BaseSchema):
    culture_pack_id: str = ""
    locale: str = ""
    era: str = ""
    genre: str = ""
    visual_traits: list[str] = []
    constraint_rules: dict[str, Any] = {}


# ── Input / Output ────────────────────────────────────────────────────────────

class Skill14Input(BaseSchema):
    action: str = "create"
    # create | read | update | delete | list | clone | compare
    # | publish | resolve | validate | export | import_culture

    persona_pack: PersonaPack = PersonaPack()

    # For read / delete / clone — target by id
    target_pack_id: str = ""

    # For compare — second pack id
    compare_pack_id: str = ""

    # For resolve — explicit chain (optional; auto-loaded if empty)
    inheritance_chain: list[PersonaPack] = []

    # For validate — entities to check consistency against
    entity_styles: list[EntityStyleEntry] = []

    # For export
    export_request: ExportRequest = ExportRequest()

    # Culture pack import (SKILL 07 output)
    culture_pack_ref: CulturePackRef = CulturePackRef()

    # Version management
    rollback_to_version: str = ""

    # Feature flags
    feature_flags: Skill14FeatureFlags = Skill14FeatureFlags()


class Skill14Output(BaseSchema):
    persona_pack_id: str = ""
    current_version: str = ""
    status: str = "draft"
    state: str = "READY"

    # Resolved persona (after inheritance)
    resolved_style_dna: StyleDNA | None = None
    resolved_rag_override: RAGRecipeOverride | None = None
    resolved_policy_override: PolicyOverride | None = None
    resolved_from: list[str] = []
    inheritance_chain_used: list[InheritanceNode] = []

    # Conflict detection
    conflicts: list[ConflictItem] = []
    conflict_auto_resolved: bool = False

    # Consistency validation
    consistency_issues: list[ConsistencyIssue] = []

    # Diff / compare
    diff: dict[str, Any] = {}

    # Export
    export_result: ExportResult | None = None

    # Manifest snapshot
    persona_pack_manifest: PersonaPack | None = None

    # Warnings
    warnings: list[str] = []
