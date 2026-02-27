"""SKILL 19: Compute-Aware Shot Budgeter — Input/Output DTOs.

Full compute-plan contract per SKILL_19_COMPUTE_AWARE_SHOT_BUDGETER.md.
Covers: cost estimation, priority scoring, SLA tiers, degradation ladder
profiles, backend routing, parallel execution planning, dynamic reallocation,
budget alerting, feature flags, user overrides.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from ainern2d_shared.schemas.base import BaseSchema


# ── Enums ────────────────────────────────────────────────────────────────────


class BudgeterState(str, Enum):
    """State machine per task spec §7."""

    INIT = "INIT"
    ESTIMATING = "ESTIMATING"
    PRIORITIZING = "PRIORITIZING"
    ALLOCATING = "ALLOCATING"
    ROUTING = "ROUTING"
    PLANNING_PARALLEL = "PLANNING_PARALLEL"
    BALANCING_SLA = "BALANCING_SLA"
    READY = "READY"
    OVER_BUDGET = "OVER_BUDGET"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    FAILED = "FAILED"


class SLATier(str, Enum):
    """SLA quality tiers per project."""

    PREMIUM = "premium"
    STANDARD = "standard"
    ECONOMY = "economy"


class Complexity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RenderPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


# ── Feature Flags & User Overrides ───────────────────────────────────────────


class Skill19FeatureFlags(BaseSchema):
    """Runtime feature toggles for shot budgeting."""

    enable_dynamic_reallocation: bool = True
    sla_tier: SLATier = SLATier.STANDARD
    cost_model_version: str = "1.0"
    max_parallel_batches: int = 4
    budget_alert_thresholds: list[float] = [0.50, 0.75, 0.90, 1.00]
    enable_shot_level_budget: bool = True
    enable_dynamic_fps: bool = True
    enable_backend_priority_assignment: bool = True


class Skill19UserOverrides(BaseSchema):
    """User-specified overrides for budget planning."""

    force_backend: str = ""
    budget_cap_override: float | None = None
    priority_boost_shots: list[str] = []


# ── Backend & Cost Models ────────────────────────────────────────────────────


class BackendCapability(BaseSchema):
    """Describes a compute backend's capabilities and pricing."""

    backend_id: str
    max_resolution: str = "1280x720"
    max_fps: int = 24
    supported_modes: list[str] = ["T2I", "I2V"]
    gpu_sec_rate: float = 1.0
    max_concurrent_jobs: int = 4
    available_slots: int = 4
    quality_ceiling: float = 1.0


class CostEstimate(BaseSchema):
    """Cost breakdown for a single shot."""

    gpu_sec: float = 0.0
    gpu_minutes: float = 0.0
    cost_usd: float = 0.0
    resolution_factor: float = 1.0
    fps_factor: float = 1.0
    duration_factor: float = 1.0
    backend_rate: float = 1.0
    quality_multiplier: float = 1.0
    historical_factor: float = 1.0
    history_confidence: float = 0.0


class PriorityScore(BaseSchema):
    """Composite priority score for a shot."""

    narrative_importance: float = 0.5
    visual_complexity: float = 0.5
    entity_count: int = 0
    motion_score: float = 0.5
    user_priority: float = 0.0
    composite_score: float = 0.0


# ── Degradation Ladder ───────────────────────────────────────────────────────


class DegradationStep(BaseSchema):
    """Single step on the 8-level degradation ladder (linked to SKILL 18)."""

    level: int = 0
    action: str = ""
    description: str = ""
    quality_floor: float = 0.0


class DegradationLadderProfile(BaseSchema):
    """Per-shot degradation profile with acceptable level based on criticality."""

    profile_id: str = ""
    max_acceptable_level: int = 3
    steps: list[DegradationStep] = []


# ── Parallel Execution ───────────────────────────────────────────────────────


class ParallelBatch(BaseSchema):
    """A group of non-dependent shots scheduled for parallel execution."""

    batch_id: str = ""
    shot_ids: list[str] = []
    backend_id: str = ""
    estimated_gpu_sec: float = 0.0
    max_concurrency: int = 4


# ── Budget Alert ─────────────────────────────────────────────────────────────


class BudgetAlert(BaseSchema):
    """Alert raised when estimated cost exceeds a threshold."""

    threshold: float = 0.0
    current_utilization: float = 0.0
    message: str = ""
    severity: str = "warning"


# ── SLA Config ───────────────────────────────────────────────────────────────


class SLAConfig(BaseSchema):
    """SLA tier configuration with minimum quality constraints."""

    tier: SLATier = SLATier.STANDARD
    min_fps: int = 8
    min_resolution: str = "640x360"
    min_quality: float = 0.5
    max_degradation_level: int = 5
    priority_boost: float = 0.0


# ── Shot Compute Plan (enhanced) ────────────────────────────────────────────


class ShotComputePlan(BaseSchema):
    """Compute plan for a single shot — runtime-ready."""

    shot_id: str
    complexity: Complexity = Complexity.MEDIUM
    render_priority: RenderPriority = RenderPriority.NORMAL
    fps: int = 24
    resolution: str = "1280x720"
    target_fps: int = 24
    target_resolution: str = "1280x720"
    gpu_tier: str = "A100"
    backend_preference: list[str] = []
    retry_budget: int = 1
    degrade_ladder_profile: str = ""
    segment_policy: str = ""
    estimated_seconds: float = 0.0
    estimated_cost: CostEstimate = CostEstimate()
    priority_score: PriorityScore = PriorityScore()
    degradation_profile: DegradationLadderProfile = DegradationLadderProfile()
    allocated_budget_gpu_sec: float = 0.0
    batch_id: str = ""


# ── Shot Input Detail ────────────────────────────────────────────────────────


class ShotInputDetail(BaseSchema):
    """Structured shot info from upstream (shot_plan.json)."""

    shot_id: str
    shot_type: str = "dialogue"
    duration_seconds: float = 3.0
    action_cues: list[str] = []
    entity_count: int = 1
    criticality: str = "normal"
    narrative_importance: float = 0.5
    visual_complexity: float = 0.5
    motion_score: float = 0.5
    user_priority: float = 0.0
    dependencies: list[str] = []
    preferred_backend: str = ""


class HistoricalRenderStat(BaseSchema):
    """Historical render profile keyed by shot type/complexity."""

    shot_type: str = ""
    complexity: Complexity | None = None
    sample_count: int = 0
    avg_gpu_sec_per_second: float = 0.0
    p95_gpu_sec_per_second: float | None = None
    overrun_rate: float = 0.0


# ── Resource State ───────────────────────────────────────────────────────────


class ClusterResourceState(BaseSchema):
    """Current cluster resource snapshot."""

    gpu_tier: str = "A100"
    gpu_hours_budget: float = 10.0
    available_vram_gb: float = 40.0
    gpu_queue_depth: int = 0
    worker_status: dict[str, str] = {}
    backends: list[BackendCapability] = []


# ── Main Input / Output ─────────────────────────────────────────────────────


class Skill19Input(BaseSchema):
    """Input contract for SKILL 19 — Compute-Aware Shot Budgeter."""

    shots: list[ShotInputDetail] = []
    audio_manifest: dict[str, Any] = {}
    cluster_resources: ClusterResourceState = ClusterResourceState()
    creative_controls: dict[str, Any] = {}
    historical_render_stats: list[HistoricalRenderStat] = []
    global_load_profile: str = "MEDIUM"
    user_mode: str = "standard"
    feature_flags: Skill19FeatureFlags = Skill19FeatureFlags()
    user_overrides: Skill19UserOverrides = Skill19UserOverrides()


class BudgetSummary(BaseSchema):
    """Aggregate budget summary."""

    max_gpu_minutes: float = 0.0
    estimated_gpu_minutes: float = 0.0
    total_gpu_hours: float = 0.0
    budget_utilization: float = 0.0
    total_cost_usd: float = 0.0


class Skill19Output(BaseSchema):
    """Output contract for SKILL 19 — Compute-Aware Shot Budgeter."""

    version: str = "1.0"
    status: str = "compute_plan_ready"
    state: BudgeterState = BudgeterState.READY
    global_profile: str = "MEDIUM"
    sla_tier: SLATier = SLATier.STANDARD
    budget_summary: BudgetSummary = BudgetSummary()
    shot_plans: list[ShotComputePlan] = []
    parallel_batches: list[ParallelBatch] = []
    alerts: list[BudgetAlert] = []
    staged_delivery: bool = False
    reallocation_log: list[dict[str, Any]] = []
    total_gpu_hours: float = 0.0
    budget_utilization: float = 0.0
