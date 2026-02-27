"""SKILL 17: Experiment & A/B Test Orchestrator — Input/Output DTOs.

参考规格: SKILL_17_EXPERIMENT_AB_TEST_ORCHESTRATOR.md

State machine:
  INIT → DESIGNING → GENERATING_VARIANTS → ALLOCATING → EXECUTING
       → COLLECTING_METRICS → ANALYZING → RECOMMENDING
       → READY | REVIEW_REQUIRED | FAILED
"""
from __future__ import annotations

from typing import Optional

from ainern2d_shared.schemas.base import BaseSchema

# ── Standard critic dimensions (sourced from SKILL 16) ────────────────────────
CRITIC_DIMENSIONS: list[str] = [
    "visual_quality",
    "audio_sync",
    "narrative_coherence",
    "character_consistency",
    "cultural_accuracy",
    "style_adherence",
    "pacing_timing",
    "technical_quality",
]


# ── Benchmark ──────────────────────────────────────────────────────────────────

class BenchmarkCase(BaseSchema):
    """A fixed benchmark scene/shot used for controlled comparison."""
    case_id: str
    scene_id: str = ""
    shot_id: str = ""
    description: str = ""
    reference_artifact_uri: str = ""
    # Normalized quality floor in [0, 1].
    expected_quality_floor: float = 0.5


# ── Variant configuration ─────────────────────────────────────────────────────

class VariantConfig(BaseSchema):
    """Version-locked configuration for one experiment arm."""
    variant_id: str
    variant_name: str = ""
    description: str = ""
    is_control: bool = False
    # Version-locked references (experiment dimensions from spec §4)
    persona_version: str = ""
    kb_version: str = ""
    rag_recipe_version: str = ""
    prompt_policy_version: str = ""
    compute_policy_version: str = ""
    model_backend: str = ""
    model_version: str = ""
    # Fine-grained parameter overrides (prompt layers, style weights, etc.)
    param_overrides: dict = {}


# ── Evaluation ─────────────────────────────────────────────────────────────────

class EvaluationCriteria(BaseSchema):
    """Defines how variants are evaluated and compared."""
    dimensions: list[str] = CRITIC_DIMENSIONS.copy()
    dimension_weights: dict[str, float] = {}
    # Normalized quality threshold in [0, 1].
    pass_threshold: float = 0.6
    confidence_level: float = 0.95
    primary_metric: str = "quality_score"
    enable_cost_weighted_ranking: bool = False
    cost_weight: float = 0.2


# ── Traffic allocation ─────────────────────────────────────────────────────────

class TrafficAllocation(BaseSchema):
    """How benchmark cases are distributed across variants."""
    strategy: str = "even_split"  # even_split | weighted | multi_arm_bandit
    variant_weights: dict[str, float] = {}
    adaptive_rebalance_interval: int = 10


# ── Feature flags ──────────────────────────────────────────────────────────────

class FeatureFlags(BaseSchema):
    """Runtime feature toggles for experiment behavior."""
    max_concurrent_experiments: int = 3
    auto_promote_threshold: float = 0.85
    min_sample_size: int = 10
    enable_adaptive_allocation: bool = False
    enable_multi_variant: bool = True
    enable_cost_weighted_ranking: bool = False
    enable_auto_promote: bool = False
    enable_early_stop: bool = True
    early_stop_confidence: float = 0.99


# ── Metrics ────────────────────────────────────────────────────────────────────

class DimensionScore(BaseSchema):
    """Aggregated score for a single critic dimension."""
    dimension: str
    mean: float = 0.0
    std: float = 0.0
    min_val: float = 0.0
    max_val: float = 0.0
    sample_count: int = 0


class VariantMetrics(BaseSchema):
    """Aggregated metrics for one variant across all benchmark runs."""
    variant_id: str
    sample_count: int = 0
    # Quality (from SKILL 16 critic scores)
    dimension_scores: list[DimensionScore] = []
    # Normalized quality in [0, 1].
    quality_score: float = 0.0
    # Efficiency
    avg_latency_ms: float = 0.0
    total_cost_units: float = 0.0
    cost_score: float = 0.0
    # Stability
    failure_rate: float = 0.0
    retry_rate: float = 0.0
    partial_success_rate: float = 0.0
    # User ratings (optional, from real tasks)
    user_rating_mean: float = 0.0
    user_rating_count: int = 0


# ── Statistical analysis ──────────────────────────────────────────────────────

class StatisticalResult(BaseSchema):
    """Significance test between control and a test variant (Welch t-test)."""
    test_variant_id: str
    control_variant_id: str
    metric: str = "quality_score"
    control_mean: float = 0.0
    test_mean: float = 0.0
    difference: float = 0.0
    confidence_interval_low: float = 0.0
    confidence_interval_high: float = 0.0
    p_value: float = 1.0
    is_significant: bool = False
    confidence_level: float = 0.95
    effect_size: float = 0.0


class DimensionRanking(BaseSchema):
    """Ranking of variants for a single critic dimension."""
    dimension: str
    ranked_variant_ids: list[str] = []
    scores: dict[str, float] = {}


# ── Promotion & rollback ──────────────────────────────────────────────────────

class RollbackPlan(BaseSchema):
    """Safety plan if a promoted variant underperforms in production."""
    variant_id: str
    rollback_to_variant_id: str
    rollback_trigger: str = ""
    rollback_steps: list[str] = []


class PromotionRecommendation(BaseSchema):
    """Recommendation for a single variant."""
    variant_id: str
    decision: str  # promote_to_default | merge_partial | reject | needs_more_data
    confidence: float = 0.0
    reasoning: str = ""
    improvements_to_adopt: list[str] = []  # for merge_partial
    rollback_plan: Optional[RollbackPlan] = None


# ── Audit trail ────────────────────────────────────────────────────────────────

class ExperimentHistoryEntry(BaseSchema):
    """Audit trail entry for experiment lifecycle."""
    timestamp: str = ""
    stage: str = ""
    action: str = ""
    detail: str = ""
    actor: str = "system"


# ── Top-level Input / Output ──────────────────────────────────────────────────

class Skill17Input(BaseSchema):
    """Input DTO for SKILL 17 — Experiment & A/B Test Orchestrator."""
    experiment_name: str = ""
    hypothesis: str = ""
    # Benchmark case set (§2.1)
    benchmark_cases: list[BenchmarkCase] = []
    # Variants — A/B/n (§2.1)
    control_variant: Optional[VariantConfig] = None
    test_variants: list[VariantConfig] = []
    # Evaluation
    evaluation_criteria: Optional[EvaluationCriteria] = None
    sample_size: int = 30
    # Traffic
    traffic_allocation: Optional[TrafficAllocation] = None
    # Feature flags (§2.2)
    feature_flags: Optional[FeatureFlags] = None
    # Optional external data (§2.2)
    user_ratings: dict[str, list[float]] = {}   # variant_id → ratings
    cost_data: dict[str, dict] = {}             # variant_id → {gpu_minutes, …}
    critic_reports: dict[str, list[dict]] = {}  # variant_id → SKILL 16 outputs
    persona_dataset_index_result: dict = {}     # from SKILL 22
    active_persona_ref: str = ""


class Skill17Output(BaseSchema):
    """Output DTO for SKILL 17 — Experiment & A/B Test Orchestrator."""
    version: str = "1.0"
    experiment_id: str = ""
    experiment_name: str = ""
    status: str = "concluded"  # draft | running | collecting | analyzing | concluded | failed
    stage: str = "READY"
    # Variants & metrics (§3 experiment_result_report)
    variants: list[VariantConfig] = []
    variant_metrics: list[VariantMetrics] = []
    # Rankings — overall + per-dimension (§6)
    overall_ranking: list[str] = []
    dimension_rankings: list[DimensionRanking] = []
    # Statistics
    statistical_results: list[StatisticalResult] = []
    # Recommendations (§3 promotion_recommendation)
    recommendations: list[PromotionRecommendation] = []
    winner_variant_id: str = ""
    promotion_gate_passed: bool = False
    promotion_candidate_id: str = ""
    promotion_block_reason: str = ""
    # Manifest (§3 experiment_run_manifest)
    traffic_allocation: Optional[TrafficAllocation] = None
    # Audit trail (§8)
    history: list[ExperimentHistoryEntry] = []
    warnings: list[str] = []
    # Governance fields
    trace_id: str = ""
    idempotency_key: str = ""
