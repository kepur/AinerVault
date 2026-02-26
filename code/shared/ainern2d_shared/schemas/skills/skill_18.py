"""SKILL 18: Failure Recovery & Degradation Policy — Input/Output DTOs.

Covers: failure classification, 8-step degradation ladder, circuit breaker,
manual review queue, recovery strategies, retry budget, health monitoring,
impact analysis, recovery plan, feature flags, and audit trail.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field

from ainern2d_shared.schemas.base import BaseSchema


# ── Enums ─────────────────────────────────────────────────────────────────────

class FailureType(str, Enum):
    TIMEOUT = "timeout"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    MODEL_ERROR = "model_error"
    VALIDATION_ERROR = "validation_error"
    DEPENDENCY_FAILURE = "dependency_failure"
    DATA_CORRUPTION = "data_corruption"
    RATE_LIMIT = "rate_limit"
    UNKNOWN = "unknown"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DegradationLevel(str, Enum):
    L0_FULL_QUALITY = "L0_FULL_QUALITY"
    L1_REDUCED_FX = "L1_REDUCED_FX"
    L2_SIMPLIFIED_COMP = "L2_SIMPLIFIED_COMP"
    L3_STATIC_KEYFRAME = "L3_STATIC_KEYFRAME"
    L4_LOWER_RES = "L4_LOWER_RES"
    L5_PLACEHOLDER_ASSET = "L5_PLACEHOLDER_ASSET"
    L6_TEXT_ONLY = "L6_TEXT_ONLY"
    L7_SKIP = "L7_SKIP"


class CircuitState(str, Enum):
    CLOSED = "closed"
    HALF_OPEN = "half_open"
    OPEN = "open"


class RecoveryStrategyType(str, Enum):
    RETRY_IMMEDIATE = "retry_immediate"
    RETRY_BACKOFF = "retry_backoff"
    FALLBACK_BACKEND = "fallback_backend"
    DEGRADE_ONE_LEVEL = "degrade_one_level"
    SKIP_NON_CRITICAL = "skip_non_critical"
    MANUAL_REVIEW = "manual_review"


class FinalStatus(str, Enum):
    SUCCESS = "success"
    SUCCESS_WITH_DEGRADATION = "success_with_degradation"
    PARTIAL_REVIEW_REQUIRED = "partial_review_required"
    FAILED_BLOCKING = "failed_blocking"


# ── Sub-schemas ───────────────────────────────────────────────────────────────

class FailureClassification(BaseSchema):
    failure_type: FailureType = FailureType.UNKNOWN
    severity: Severity = Severity.MEDIUM
    retryable: bool = True
    error_code: str = ""
    source_module: str = ""
    description: str = ""


class DegradationStep(BaseSchema):
    """One rung of the 8-step degradation ladder."""
    level: DegradationLevel = DegradationLevel.L0_FULL_QUALITY
    param_adjustments: dict[str, Any] = Field(default_factory=dict)
    description: str = ""


class CircuitBreakerState(BaseSchema):
    backend_id: str = ""
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    failure_rate: float = 0.0
    last_failure_ts: str = ""
    last_success_ts: str = ""
    window_seconds: int = 60
    threshold: float = 0.5


class RecoveryAction(BaseSchema):
    strategy: RecoveryStrategyType = RecoveryStrategyType.RETRY_IMMEDIATE
    target_skill: str = ""
    target_backend: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""


class RetryBudget(BaseSchema):
    entity_id: str = ""
    shot_id: str = ""
    max_retries: int = 3
    retries_used: int = 0
    next_delay_seconds: float = 1.0
    backoff_base: float = 2.0
    jitter_max: float = 1.0


class BackendHealth(BaseSchema):
    backend_id: str = ""
    success_rate: float = 1.0
    avg_latency_ms: float = 0.0
    error_rate: float = 0.0
    circuit_state: CircuitState = CircuitState.CLOSED
    sample_count: int = 0


class CascadeImpact(BaseSchema):
    """Downstream entities / shots affected by a failure."""
    affected_shot_ids: list[str] = Field(default_factory=list)
    affected_entity_ids: list[str] = Field(default_factory=list)
    blocked_skills: list[str] = Field(default_factory=list)
    impact_summary: str = ""


class ManualReviewItem(BaseSchema):
    entity_id: str = ""
    shot_id: str = ""
    reason: str = ""
    degradation_level: DegradationLevel = DegradationLevel.L5_PLACEHOLDER_ASSET
    failure_classification: FailureClassification | None = None
    created_at: str = ""


class RecoveryPlanStep(BaseSchema):
    order: int = 0
    action: RecoveryAction = Field(default_factory=RecoveryAction)
    expected_degradation: DegradationLevel = DegradationLevel.L0_FULL_QUALITY
    result: str = ""  # pending | success | failed | skipped


class AuditEntry(BaseSchema):
    timestamp: str = ""
    event: str = ""
    from_state: str = ""
    to_state: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class FeatureFlags(BaseSchema):
    max_retries: int = 3
    circuit_breaker_threshold: float = 0.5
    auto_degrade_enabled: bool = True
    manual_review_threshold: str = DegradationLevel.L5_PLACEHOLDER_ASSET.value
    health_check_interval_seconds: int = 30
    enable_partial_success: bool = True
    enable_backend_fallback: bool = True
    enable_degradation_ladder: bool = True


# ── Top-level Input / Output ──────────────────────────────────────────────────

class Skill18Input(BaseSchema):
    # Failure context
    error_code: str = ""
    failed_skill: str = ""
    stage: str = ""
    retry_count: int = 0

    # Failure details (optional rich payload)
    error_message: str = ""
    failed_backend: str = ""
    failed_shot_ids: list[str] = Field(default_factory=list)
    failed_entity_ids: list[str] = Field(default_factory=list)

    # Policy inputs
    creative_controls: dict[str, Any] = Field(default_factory=dict)
    compute_budget_policy: dict[str, Any] = Field(default_factory=dict)
    critic_fix_queue: list[dict[str, Any]] = Field(default_factory=list)
    backend_capabilities: dict[str, Any] = Field(default_factory=dict)
    retry_history: list[dict[str, Any]] = Field(default_factory=list)

    # Feature flags
    feature_flags: FeatureFlags = Field(default_factory=FeatureFlags)


class Skill18Output(BaseSchema):
    # Final status (FR4)
    status: FinalStatus = FinalStatus.SUCCESS
    stage: str = ""

    # Failure classification (FR1)
    failure_classification: FailureClassification = Field(
        default_factory=FailureClassification,
    )

    # Recovery plan (FR2 + recovery plan generation)
    recovery_plan: list[RecoveryPlanStep] = Field(default_factory=list)
    actions_taken: list[RecoveryPlanStep] = Field(default_factory=list)

    # Degradation (FR3)
    degradation_applied: bool = False
    degradation_level: DegradationLevel = DegradationLevel.L0_FULL_QUALITY
    degradation_trace: list[DegradationStep] = Field(default_factory=list)
    hard_constraints_preserved: bool = True

    # Circuit breaker
    circuit_breaker_states: list[CircuitBreakerState] = Field(default_factory=list)
    circuit_breaker_triggered: bool = False

    # Health monitoring
    backend_health: list[BackendHealth] = Field(default_factory=list)

    # Impact analysis
    cascade_impact: CascadeImpact = Field(default_factory=CascadeImpact)

    # Manual review queue
    manual_review_required: bool = False
    manual_review_items: list[ManualReviewItem] = Field(default_factory=list)

    # Retry budget
    retry_budgets: list[RetryBudget] = Field(default_factory=list)

    # Audit trail
    audit_trail: list[AuditEntry] = Field(default_factory=list)
