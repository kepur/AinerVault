"""SKILL 16: Critic Evaluation Suite — Input/Output DTOs.

Covers: 8 critic dimensions, per-dimension evidence, severity levels,
fix queue, weighted composite score, shot/scene evaluation, cross-shot
consistency, benchmark comparison, auto-pass/fail gate, feature flags,
and critic history.
"""
from __future__ import annotations

from typing import Optional

from ainern2d_shared.schemas.base import BaseSchema


# ── Severity enum values ────────────────────────────────────────
SEVERITY_BLOCKER = "blocker"
SEVERITY_CRITICAL = "critical"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"

VALID_SEVERITIES = {SEVERITY_BLOCKER, SEVERITY_CRITICAL, SEVERITY_WARNING, SEVERITY_INFO}

# ── 8 critic dimensions ────────────────────────────────────────
CRITIC_DIMENSIONS = [
    "visual_quality",
    "audio_sync",
    "narrative_coherence",
    "character_consistency",
    "cultural_accuracy",
    "style_adherence",
    "pacing_timing",
    "technical_quality",
]

# ── Decision values ─────────────────────────────────────────────
DECISION_PASS = "pass"
DECISION_RETRY = "retry_partial"
DECISION_DEGRADE = "degrade"
DECISION_MANUAL_REVIEW = "manual_review"

# ── State machine stages ───────────────────────────────────────
SM_INIT = "INIT"
SM_LOADING_ARTIFACTS = "LOADING_ARTIFACTS"
SM_EVALUATING_SHOTS = "EVALUATING_SHOTS"
SM_EVALUATING_SCENES = "EVALUATING_SCENES"
SM_CROSS_CHECKING = "CROSS_CHECKING"
SM_SCORING = "SCORING"
SM_GENERATING_FIXES = "GENERATING_FIXES"
SM_GATING = "GATING"
SM_READY = "READY"
SM_REVIEW_REQUIRED = "REVIEW_REQUIRED"
SM_FAILED = "FAILED"


# ── Evidence ────────────────────────────────────────────────────

class EvidenceItem(BaseSchema):
    """Single piece of evidence for a dimension evaluation."""
    check_name: str = ""
    passed: bool = True
    confidence: float = 1.0
    detail: str = ""
    ref_shot_id: str = ""
    ref_scene_id: str = ""
    time_range_ms: list[int] = []


# ── Dimension score (0-100) ────────────────────────────────────

class DimensionScore(BaseSchema):
    """Per-dimension evaluation result with 0-100 scoring."""
    dimension: str = ""
    score: float = 0.0
    max_score: float = 100.0
    weight: float = 1.0
    evidence: list[EvidenceItem] = []
    summary: str = ""


# ── Issue / problem ────────────────────────────────────────────

class CriticIssue(BaseSchema):
    """A single issue detected by a critic agent."""
    issue_id: str = ""
    critic: str = ""
    severity: str = SEVERITY_WARNING
    scene_id: str = ""
    shot_id: str = ""
    time_range_ms: list[int] = []
    category: str = ""
    message: str = ""
    auto_fix_possible: bool = False
    recommended_fix_type: str = ""


# ── Fix queue item ──────────────────────────────────────────────

class FixQueueItem(BaseSchema):
    """Ordered fix task for the recovery / degradation pipeline."""
    fix_id: str = ""
    dimension: str = ""
    severity: str = SEVERITY_WARNING
    description: str = ""
    suggested_action: str = ""
    affected_shots: list[str] = []
    estimated_effort: str = "medium"
    fix_type: str = ""
    target_skill: str = ""


# ── Shot-level evaluation ──────────────────────────────────────

class ShotEvaluation(BaseSchema):
    """Evaluation result for a single shot."""
    shot_id: str = ""
    scene_id: str = ""
    dimension_scores: list[DimensionScore] = []
    composite_score: float = 0.0
    issues: list[CriticIssue] = []
    passed: bool = True


# ── Scene-level evaluation (aggregated from shots) ─────────────

class SceneEvaluation(BaseSchema):
    """Aggregated evaluation for a scene built from its shots."""
    scene_id: str = ""
    shot_evaluations: list[ShotEvaluation] = []
    dimension_scores: list[DimensionScore] = []
    composite_score: float = 0.0
    issues: list[CriticIssue] = []
    passed: bool = True


# ── Cross-shot consistency result ──────────────────────────────

class CrossShotConsistencyResult(BaseSchema):
    """Result of cross-shot consistency checks within a scene."""
    scene_id: str = ""
    character_consistency_score: float = 0.0
    environment_consistency_score: float = 0.0
    lighting_consistency_score: float = 0.0
    overall_consistency_score: float = 0.0
    inconsistencies: list[CriticIssue] = []


# ── Benchmark comparison ───────────────────────────────────────

class BenchmarkComparison(BaseSchema):
    """Score comparison against project and global baselines."""
    dimension: str = ""
    current_score: float = 0.0
    project_baseline: float = 0.0
    global_baseline: float = 0.0
    delta_project: float = 0.0
    delta_global: float = 0.0


# ── Critic history entry ───────────────────────────────────────

class CriticHistoryEntry(BaseSchema):
    """Snapshot of scores for a single evaluation iteration."""
    iteration: int = 0
    timestamp: str = ""
    composite_score: float = 0.0
    dimension_scores: dict[str, float] = {}
    decision: str = ""


# ── Feature flags ──────────────────────────────────────────────

class Skill16FeatureFlags(BaseSchema):
    """Feature flags controlling SKILL 16 behaviour."""
    evaluation_depth: str = "standard"  # quick | standard | deep
    enable_cross_shot_check: bool = True
    auto_fail_threshold: float = 60.0
    dimension_weights: dict[str, float] = {}
    enable_visual_critic: bool = True
    enable_audio_visual_sync_critic: bool = True
    enable_prompt_traceability_critic: bool = True
    enable_auto_fix_suggestions: bool = True


# ── Artifact reference ─────────────────────────────────────────

class ArtifactRef(BaseSchema):
    """Reference to a generated artifact (image/video/audio)."""
    artifact_uri: str = ""
    artifact_type: str = ""
    shot_id: str = ""
    scene_id: str = ""


# ── Shot plan entry (from Skill 03) ────────────────────────────

class ShotPlanEntry(BaseSchema):
    """Minimal shot info needed for evaluation."""
    shot_id: str = ""
    scene_id: str = ""
    description: str = ""
    duration_ms: int = 0
    characters: list[str] = []
    environment: str = ""
    lighting: str = ""
    camera: str = ""


# ── Input ──────────────────────────────────────────────────────

class Skill16Input(BaseSchema):
    """Full input for SKILL 16 — Critic Evaluation Suite."""
    run_id: str = ""
    # Required artifact references
    artifact_refs: list[ArtifactRef] = []
    composed_artifact_uri: str = ""
    timeline_final: Optional[dict] = None
    audio_event_manifest: Optional[dict] = None
    shot_plan: list[ShotPlanEntry] = []
    creative_control_stack: Optional[dict] = None
    # Optional enrichment
    resolved_persona_profile: Optional[dict] = None
    cultural_constraints: Optional[dict] = None
    prompt_plan: Optional[dict] = None
    shot_dsl: Optional[dict] = None
    # Feature flags
    feature_flags: Skill16FeatureFlags = Skill16FeatureFlags()
    # Baselines for benchmark comparison
    project_baseline_scores: dict[str, float] = {}
    global_baseline_scores: dict[str, float] = {}
    # Previous history (for trend tracking)
    previous_iterations: list[CriticHistoryEntry] = []


# ── Output ─────────────────────────────────────────────────────

class Skill16Output(BaseSchema):
    """Full output of SKILL 16 — Critic Evaluation Suite."""
    version: str = "1.0"
    status: str = "completed"
    # Overall
    overall_decision: str = DECISION_PASS
    composite_score: float = 0.0
    dimension_scores: list[DimensionScore] = []
    # Issues
    issues: list[CriticIssue] = []
    # Fix queue
    fix_queue: list[FixQueueItem] = []
    # Shot & scene evaluations
    shot_evaluations: list[ShotEvaluation] = []
    scene_evaluations: list[SceneEvaluation] = []
    # Cross-shot consistency
    cross_shot_results: list[CrossShotConsistencyResult] = []
    # Benchmark
    benchmark_comparisons: list[BenchmarkComparison] = []
    # Gate
    auto_fail_threshold: float = 60.0
    passed: bool = False
    human_review_required: bool = False
    # Auto-fix
    auto_fix_recommendations: list[FixQueueItem] = []
    # History
    critic_history: list[CriticHistoryEntry] = []
    # Tracing
    warnings: list[str] = []
    trace_id: str = ""
    idempotency_key: str = ""
