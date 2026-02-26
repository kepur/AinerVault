"""SKILL 09: Visual Render Planner — Input/Output DTOs.

Full contract per SKILL_09_VISUAL_RENDER_PLANNER.md including:
- Audio feature aggregation per shot (rhythm_density, tempo_bpm, energy_level)
- Motion complexity scoring 0-100 with multi-signal inputs
- Micro-shot splitting for motion_score > 75
- 4-level backend degradation cascade
- Render profile assignment (resolution, fps, render_backend, quality_preset)
- Camera motion inference, transition planning, layer composition
- Feature flags & user overrides

State machine:
  INIT → PRECHECKING → PRECHECK_READY → AGGREGATING_AUDIO → AUDIO_FEATURES_READY
       → SCORING_MOTION → MOTION_SCORED → ASSIGNING_RENDER → STRATEGY_READY
       → SPLITTING_MICRO → PLANNING_CAMERA → PLANNING_TRANSITIONS
       → COMPOSING_LAYERS → DEGRADE_PROCESSING → ASSEMBLING_RENDER_PLAN
       → READY_FOR_RENDER_EXECUTION | REVIEW_REQUIRED | FAILED
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from ainern2d_shared.schemas.base import BaseSchema


# ── Enums ─────────────────────────────────────────────────────────────────────

class RenderState(str, Enum):
    INIT = "INIT"
    PRECHECKING = "PRECHECKING"
    PRECHECK_READY = "PRECHECK_READY"
    AGGREGATING_AUDIO = "AGGREGATING_AUDIO"
    AUDIO_FEATURES_READY = "AUDIO_FEATURES_READY"
    SCORING_MOTION = "SCORING_MOTION"
    MOTION_SCORED = "MOTION_SCORED"
    ASSIGNING_RENDER = "ASSIGNING_RENDER"
    STRATEGY_READY = "STRATEGY_READY"
    SPLITTING_MICRO = "SPLITTING_MICRO"
    PLANNING_CAMERA = "PLANNING_CAMERA"
    PLANNING_TRANSITIONS = "PLANNING_TRANSITIONS"
    COMPOSING_LAYERS = "COMPOSING_LAYERS"
    DEGRADE_PROCESSING = "DEGRADE_PROCESSING"
    ASSEMBLING_RENDER_PLAN = "ASSEMBLING_RENDER_PLAN"
    READY_FOR_RENDER_EXECUTION = "READY_FOR_RENDER_EXECUTION"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    FAILED = "FAILED"


class MotionLevel(str, Enum):
    LOW_MOTION = "LOW_MOTION"
    MEDIUM_MOTION = "MEDIUM_MOTION"
    HIGH_MOTION = "HIGH_MOTION"


class GlobalRenderProfile(str, Enum):
    LOW_LOAD = "LOW_LOAD"
    MEDIUM_LOAD = "MEDIUM_LOAD"
    HIGH_LOAD = "HIGH_LOAD"


class I2VMode(str, Enum):
    START_END = "start_end"
    START_MID_END = "start_mid_end"
    MULTI_KEYFRAME = "multi_keyframe"


class DegradeLevel(str, Enum):
    FULL_QUALITY = "FULL_QUALITY"
    REDUCED_FX = "REDUCED_FX"
    SIMPLIFIED_COMP = "SIMPLIFIED_COMP"
    STATIC_FALLBACK = "STATIC_FALLBACK"


class CameraMotion(str, Enum):
    STATIC = "static"
    PAN = "pan"
    TILT = "tilt"
    ZOOM = "zoom"
    TRACKING = "tracking"


class TransitionType(str, Enum):
    CUT = "cut"
    DISSOLVE = "dissolve"
    FADE = "fade"
    WIPE = "wipe"


class Criticality(str, Enum):
    CRITICAL = "critical"
    IMPORTANT = "important"
    NORMAL = "normal"
    BACKGROUND = "background"


# ── Constants ─────────────────────────────────────────────────────────────────

SHOT_TYPE_MOTION_WEIGHT: dict[str, int] = {
    "close": 20,
    "close_up": 20,
    "medium": 40,
    "medium_shot": 40,
    "wide": 60,
    "wide_shot": 60,
    "action": 90,
    "establishing": 15,
}

# §15 D3: frame budget mapping [profile][motion_level] → budget
FRAME_BUDGET_MAP: dict[str, dict[str, int]] = {
    "LOW_LOAD": {"LOW_MOTION": 8, "MEDIUM_MOTION": 10, "HIGH_MOTION": 12},
    "MEDIUM_LOAD": {"LOW_MOTION": 8, "MEDIUM_MOTION": 12, "HIGH_MOTION": 24},
    "HIGH_LOAD": {"LOW_MOTION": 12, "MEDIUM_MOTION": 20, "HIGH_MOTION": 24},
}

# §7.3: motion level thresholds
MOTION_THRESHOLDS = {"low_max": 25, "medium_max": 55}

MICRO_SHOT_MIN_DURATION_MS = 300
MICRO_SHOT_MAX_DURATION_MS = 1000
MICRO_SHOT_MOTION_THRESHOLD = 75


# ── Sub-schemas ───────────────────────────────────────────────────────────────

class FeatureFlags(BaseSchema):
    micro_shot_enabled: bool = True
    max_motion_score_cap: int = 100
    static_fallback_only: bool = False
    parallel_render_groups: int = 2
    enable_compute_aware_planning: bool = True
    enable_backend_auto_degrade: bool = True
    enable_audio_beat_alignment: bool = True


class UserOverrides(BaseSchema):
    render_profile_override: str | None = None
    backend_force: str | None = None
    resolution_cap: str | None = None
    locked_shot_ids: list[str] = []
    forced_high_quality_shot_ids: list[str] = []


class BackendCapability(BaseSchema):
    gpu_model: str = "A100"
    supported_i2v_modes: list[str] = ["start_end", "start_mid_end", "multi_keyframe"]
    max_concurrency: int = 4
    suggested_frame_budget: int = 24
    supported_workflows: list[str] = []


class BackendLoadStatus(BaseSchema):
    queue_length: int = 0
    vram_usage_pct: float = 0.0
    avg_task_duration_s: float = 0.0
    congestion_level: str = "low"  # low | medium | high


class AudioFeatures(BaseSchema):
    tts_density: float = 0.0
    sfx_events_per_sec: float = 0.0
    transient_peak_density: float = 0.0
    bgm_beat_intensity: float = 0.0
    ambience_intensity: float = 0.0
    alignment_points: list[int] = []
    rhythm_density: float = 0.0
    tempo_bpm: float = 0.0
    energy_level: float = 0.0


class RenderStrategy(BaseSchema):
    frame_budget: int = 12
    i2v_mode: str = I2VMode.START_END.value
    target_shot_duration_ms: int = 0
    beat_alignment_strength: str = "low"  # low | medium | high
    quality_priority: str = "medium"  # low | medium | high
    compute_priority: str = "medium"  # low | medium | high
    degrade_allowed: bool = True
    degrade_level: str = DegradeLevel.FULL_QUALITY.value
    fallback_i2v_mode: str = I2VMode.START_END.value
    backend_constraints_applied: list[str] = []
    render_backend: str = "comfyui"
    resolution: str = "1280x720"
    fps: int = 24
    quality_preset: str = "standard"  # preview | standard | high


class LayerComposition(BaseSchema):
    background: bool = True
    midground: bool = False
    character: bool = True
    fx_overlay: bool = False
    text_overlay: bool = False


class TransitionPlan(BaseSchema):
    from_shot_id: str = ""
    to_shot_id: str = ""
    transition_type: str = TransitionType.CUT.value
    duration_ms: int = 0


class ShotRenderPlan(BaseSchema):
    shot_id: str
    scene_id: str = ""
    start_ms: int = 0
    end_ms: int = 0
    duration_ms: int = 0
    motion_complexity_score: int = 0
    motion_level: str = MotionLevel.LOW_MOTION.value
    audio_features: AudioFeatures = AudioFeatures()
    render_strategy: RenderStrategy = RenderStrategy()
    split_into_microshots: bool = False
    criticality: str = Criticality.NORMAL.value
    reasoning_tags: list[str] = []
    warnings: list[str] = []
    camera_motion: str = CameraMotion.STATIC.value
    layer_composition: LayerComposition = LayerComposition()
    rag_retrieval_tags: dict[str, str] = {}


class MicroshotRenderPlan(BaseSchema):
    microshot_id: str
    parent_shot_id: str
    start_ms: int = 0
    end_ms: int = 0
    duration_ms: int = 0
    split_reason_tags: list[str] = []
    alignment_points: list[int] = []
    motion_complexity_score: int = 0
    render_strategy: RenderStrategy = RenderStrategy()
    criticality: str = Criticality.NORMAL.value
    camera_motion: str = CameraMotion.STATIC.value
    layer_composition: LayerComposition = LayerComposition()


class DegradeAction(BaseSchema):
    target_type: str = "shot"  # shot | microshot | global
    target_id: str = ""
    action: str = ""  # reduce_frame_budget | simplify_i2v_mode | merge_microshots | ...
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    reason_tags: list[str] = []
    degrade_level: str = DegradeLevel.FULL_QUALITY.value
    degrade_policy_id: str = ""


class ReviewRequiredItem(BaseSchema):
    item_type: str = "shot"
    item_id: str = ""
    reason: str = ""
    severity: str = "medium"  # low | medium | high
    suggested_action: str = ""


class PlanningSummary(BaseSchema):
    total_shots: int = 0
    high_motion_shots: int = 0
    microshot_splits: int = 0
    total_microshots: int = 0
    degraded_shots: int = 0
    critical_segments_protected: int = 0


class ResourceStrategy(BaseSchema):
    recommended_parallelism: int = 2
    queue_priority_mode: str = "critical_first"
    preview_first: bool = False


# ── Backward-compat alias ─────────────────────────────────────────────────────
class ShotRenderConfig(BaseSchema):
    """Thin backward-compatible wrapper mapping legacy fields to ShotRenderPlan."""
    shot_id: str
    render_mode: str = "i2v"
    fps: int = 24
    resolution: str = "1280x720"
    priority: int = 0
    gpu_tier: str = "A100"
    fallback_chain: list[str] = []


# ── Input / Output ────────────────────────────────────────────────────────────

class Skill09Input(BaseSchema):
    # §3.1 Required inputs
    audio_timeline: dict[str, Any] = {}         # timeline_final from SKILL 06
    shots: list[dict[str, Any]] = []            # shot_plan from SKILL 03
    asset_manifest: list[dict[str, Any]] = []   # asset_match_result from SKILL 08
    compute_budget: dict[str, Any] = {}         # contains global_render_profile

    # §3.2 Optional inputs
    backend_capability: dict[str, Any] = {}
    backend_load_status: dict[str, Any] = {}
    quality_profile: str = "standard"           # preview | standard | final
    user_overrides: dict[str, Any] = {}
    feature_flags: dict[str, Any] = {}
    project_constraints: dict[str, Any] = {}


class Skill09Output(BaseSchema):
    version: str = "1.0"
    status: str = "ready_for_render_execution"
    global_render_profile: str = GlobalRenderProfile.MEDIUM_LOAD.value
    planning_summary: PlanningSummary = PlanningSummary()
    resource_strategy: ResourceStrategy = ResourceStrategy()
    shot_render_plans: list[ShotRenderPlan] = []
    microshot_render_plans: list[MicroshotRenderPlan] = []
    degrade_actions: list[DegradeAction] = []
    warnings: list[str] = []
    review_required_items: list[ReviewRequiredItem] = []
    transitions: list[TransitionPlan] = []

    # Backward-compat
    render_plans: list[ShotRenderConfig] = []
    total_gpu_hours_estimate: float = 0.0
