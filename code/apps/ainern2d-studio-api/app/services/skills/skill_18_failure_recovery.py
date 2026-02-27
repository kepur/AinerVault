"""SKILL 18: FailureRecoveryService — 业务逻辑实现。
参考规格: SKILL_18_FAILURE_RECOVERY_DEGRADATION_POLICY.md
状态: SERVICE_READY

State machine:
  INIT → CLASSIFYING → ANALYZING_IMPACT → SELECTING_STRATEGY
       → EXECUTING_RECOVERY → MONITORING → READY | DEGRADED | MANUAL_REVIEW | FAILED
"""
from __future__ import annotations

import hashlib
import math
import random
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from ainern2d_shared.schemas.skills.skill_18 import (
    AuditEntry,
    BackendHealth,
    CascadeImpact,
    CircuitBreakerState,
    CircuitState,
    DegradationLevel,
    DegradationStep,
    FailureClassification,
    FailureType,
    FeatureFlags,
    FinalStatus,
    ManualReviewItem,
    RecoveryAction,
    RecoveryPlanStep,
    RecoveryStrategyType,
    RetryBudget,
    Severity,
    Skill18Input,
    Skill18Output,
)
from ainern2d_shared.services.base_skill import BaseSkillService, SkillContext
from ainern2d_shared.utils.time import utcnow

# ── Degradation ladder definition ─────────────────────────────────────────────

_DEGRADATION_LADDER: list[DegradationStep] = [
    DegradationStep(
        level=DegradationLevel.L0_FULL_QUALITY,
        param_adjustments={},
        description="Full quality — no degradation",
    ),
    DegradationStep(
        level=DegradationLevel.L1_SHORTEN_DURATION,
        param_adjustments={"duration_scale": 0.75},
        description="Shorten shot duration",
    ),
    DegradationStep(
        level=DegradationLevel.L2_LOWER_FPS,
        param_adjustments={"fps_scale": 0.5, "target_fps": 12},
        description="Lower frame rate",
    ),
    DegradationStep(
        level=DegradationLevel.L3_LOWER_RESOLUTION,
        param_adjustments={"resolution_scale": 0.5, "max_resolution": "720p"},
        description="Lower output resolution",
    ),
    DegradationStep(
        level=DegradationLevel.L4_SPLIT_MICROSHOTS,
        param_adjustments={"split_mode": "microshots", "max_microshot_ms": 800},
        description="Split into shorter micro-shots and retry",
    ),
    DegradationStep(
        level=DegradationLevel.L5_STATIC_IMAGE_MOTION,
        param_adjustments={"motion_mode": "static_keyframe", "effect": "ken_burns"},
        description="Static image plus lightweight motion effect",
    ),
    DegradationStep(
        level=DegradationLevel.L6_PLACEHOLDER_MANUAL_REVIEW,
        param_adjustments={"use_placeholder": True, "asset_type": "placeholder"},
        description="Placeholder output and queue manual review",
    ),
    DegradationStep(
        level=DegradationLevel.L7_SKIP_NON_CRITICAL,
        param_adjustments={"skip": True},
        description="Skip non-critical shot/entity",
    ),
]

# Map level enum to ladder index for ordering
_LEVEL_ORDER: dict[DegradationLevel, int] = {
    step.level: i for i, step in enumerate(_DEGRADATION_LADDER)
}

# Backward compatibility for old degradation enum strings.
_LEGACY_DEGRADATION_LEVEL_MAP: dict[str, DegradationLevel] = {
    "L0_FULL_QUALITY": DegradationLevel.L0_FULL_QUALITY,
    "L1_REDUCED_FX": DegradationLevel.L1_SHORTEN_DURATION,
    "L2_SIMPLIFIED_COMP": DegradationLevel.L2_LOWER_FPS,
    "L3_STATIC_KEYFRAME": DegradationLevel.L5_STATIC_IMAGE_MOTION,
    "L4_LOWER_RES": DegradationLevel.L3_LOWER_RESOLUTION,
    "L5_PLACEHOLDER_ASSET": DegradationLevel.L6_PLACEHOLDER_MANUAL_REVIEW,
    "L6_TEXT_ONLY": DegradationLevel.L6_PLACEHOLDER_MANUAL_REVIEW,
    "L7_SKIP": DegradationLevel.L7_SKIP_NON_CRITICAL,
}

# ── Failure classification rules ──────────────────────────────────────────────

# (error_code_prefix -> FailureType, default Severity, retryable)
_CLASSIFICATION_RULES: list[tuple[str, FailureType, Severity, bool]] = [
    ("ORCH-TIMEOUT", FailureType.TIMEOUT, Severity.MEDIUM, True),
    ("WORKER-EXEC", FailureType.MODEL_ERROR, Severity.HIGH, True),
    ("WORKER-CLAIM", FailureType.DEPENDENCY_FAILURE, Severity.MEDIUM, True),
    ("WORKER-GPU", FailureType.RESOURCE_EXHAUSTION, Severity.HIGH, True),
    ("SYS-DEPENDENCY", FailureType.DEPENDENCY_FAILURE, Severity.CRITICAL, False),
    ("SYS-RESOURCE", FailureType.RESOURCE_EXHAUSTION, Severity.CRITICAL, False),
    ("REQ-VALIDATION", FailureType.VALIDATION_ERROR, Severity.LOW, False),
    ("PLAN-GENERATE", FailureType.MODEL_ERROR, Severity.HIGH, True),
    ("ROUTE-NO_TARGET", FailureType.DEPENDENCY_FAILURE, Severity.HIGH, True),
    ("COMPOSE-FFMPEG", FailureType.MODEL_ERROR, Severity.MEDIUM, True),
    ("ASSET-UPLOAD", FailureType.DEPENDENCY_FAILURE, Severity.MEDIUM, True),
    ("RAG-EMBEDDING", FailureType.MODEL_ERROR, Severity.MEDIUM, True),
    ("RATE-LIMIT", FailureType.RATE_LIMIT, Severity.LOW, True),
]

# ── Recovery strategy selection matrix ────────────────────────────────────────
# (FailureType, max_severity_for_strategy) → ordered list of strategies to try

_STRATEGY_MATRIX: dict[FailureType, list[RecoveryStrategyType]] = {
    FailureType.TIMEOUT: [
        RecoveryStrategyType.RETRY_BACKOFF,
        RecoveryStrategyType.FALLBACK_BACKEND,
        RecoveryStrategyType.DEGRADE_ONE_LEVEL,
    ],
    FailureType.RESOURCE_EXHAUSTION: [
        RecoveryStrategyType.RETRY_BACKOFF,
        RecoveryStrategyType.FALLBACK_BACKEND,
        RecoveryStrategyType.DEGRADE_ONE_LEVEL,
        RecoveryStrategyType.SKIP_NON_CRITICAL,
    ],
    FailureType.MODEL_ERROR: [
        RecoveryStrategyType.RETRY_IMMEDIATE,
        RecoveryStrategyType.FALLBACK_BACKEND,
        RecoveryStrategyType.DEGRADE_ONE_LEVEL,
    ],
    FailureType.VALIDATION_ERROR: [
        RecoveryStrategyType.SKIP_NON_CRITICAL,
        RecoveryStrategyType.MANUAL_REVIEW,
    ],
    FailureType.DEPENDENCY_FAILURE: [
        RecoveryStrategyType.RETRY_BACKOFF,
        RecoveryStrategyType.FALLBACK_BACKEND,
        RecoveryStrategyType.DEGRADE_ONE_LEVEL,
    ],
    FailureType.DATA_CORRUPTION: [
        RecoveryStrategyType.MANUAL_REVIEW,
    ],
    FailureType.RATE_LIMIT: [
        RecoveryStrategyType.RETRY_BACKOFF,
        RecoveryStrategyType.FALLBACK_BACKEND,
    ],
    FailureType.UNKNOWN: [
        RecoveryStrategyType.RETRY_BACKOFF,
        RecoveryStrategyType.FALLBACK_BACKEND,
        RecoveryStrategyType.DEGRADE_ONE_LEVEL,
        RecoveryStrategyType.MANUAL_REVIEW,
    ],
}

# ── Skill-to-downstream dependency map (simplified) ──────────────────────────

_DOWNSTREAM_DEPS: dict[str, list[str]] = {
    "skill_03": ["skill_05", "skill_09", "skill_10"],
    "skill_05": ["skill_06"],
    "skill_09": ["skill_10", "skill_12"],
    "skill_10": ["skill_12"],
}


class FailureRecoveryService(BaseSkillService[Skill18Input, Skill18Output]):
    """SKILL 18 — Failure Recovery & Degradation Policy.

    Implements:
      1. Failure classification (8 types, severity, retryability)
      2. 8-step degradation ladder (L0–L7)
      3. Circuit breaker (closed / half_open / open)
      4. Manual review queue (L5+ or critical entities)
      5. Recovery strategy selection (6 strategies)
      6. Retry budget with exponential backoff + jitter
      7. Per-backend health monitoring
      8. Failure cascade impact analysis
      9. Ordered recovery plan generation
     10. Feature flags
     11. Full audit trail
    """

    skill_id = "skill_18"
    skill_name = "FailureRecoveryService"

    def __init__(self, db: Session) -> None:
        super().__init__(db)
        # In-memory circuit breaker store (keyed by backend_id)
        self._circuit_breakers: dict[str, CircuitBreakerState] = {}
        # In-memory health store
        self._backend_health: dict[str, BackendHealth] = {}
        # Audit trail accumulator (populated per-execution)
        self._audit: list[AuditEntry] = []

    # ── public execute ────────────────────────────────────────────────────────

    def execute(self, input_dto: Skill18Input, ctx: SkillContext) -> Skill18Output:
        self._audit = []
        ts = utcnow().isoformat()
        flags = input_dto.feature_flags

        # ── INIT → CLASSIFYING ────────────────────────────────────────────
        self._record_state(ctx, "INIT", "CLASSIFYING")
        self._log_audit(ts, "state_change", "INIT", "CLASSIFYING")

        classification = self._classify_failure(input_dto)
        self._log_audit(ts, "failure_classified", "CLASSIFYING", "CLASSIFYING", {
            "failure_type": classification.failure_type.value,
            "severity": classification.severity.value,
            "retryable": classification.retryable,
        })

        # ── CLASSIFYING → ANALYZING_IMPACT ────────────────────────────────
        self._record_state(ctx, "CLASSIFYING", "ANALYZING_IMPACT")
        self._log_audit(ts, "state_change", "CLASSIFYING", "ANALYZING_IMPACT")

        cascade = self._analyze_impact(input_dto, classification)
        self._log_audit(ts, "impact_analyzed", "ANALYZING_IMPACT", "ANALYZING_IMPACT", {
            "affected_shots": len(cascade.affected_shot_ids),
            "affected_entities": len(cascade.affected_entity_ids),
            "blocked_skills": cascade.blocked_skills,
        })

        # ── ANALYZING_IMPACT → SELECTING_STRATEGY ─────────────────────────
        self._record_state(ctx, "ANALYZING_IMPACT", "SELECTING_STRATEGY")
        self._log_audit(ts, "state_change", "ANALYZING_IMPACT", "SELECTING_STRATEGY")

        # Check circuit breaker for the failed backend
        cb_states, cb_triggered = self._evaluate_circuit_breakers(
            input_dto, classification, flags, ts,
        )

        # Build retry budgets
        retry_budgets = self._build_retry_budgets(input_dto, flags)

        # Select recovery strategies & build recovery plan
        recovery_plan = self._build_recovery_plan(
            input_dto, classification, cb_triggered, retry_budgets, flags,
        )
        self._log_audit(ts, "recovery_plan_built", "SELECTING_STRATEGY", "SELECTING_STRATEGY", {
            "plan_steps": len(recovery_plan),
        })

        # ── SELECTING_STRATEGY → EXECUTING_RECOVERY ───────────────────────
        self._record_state(ctx, "SELECTING_STRATEGY", "EXECUTING_RECOVERY")
        self._log_audit(ts, "state_change", "SELECTING_STRATEGY", "EXECUTING_RECOVERY")

        actions_taken, current_deg_level = self._simulate_plan_execution(
            recovery_plan, classification, flags, ts,
        )

        # ── EXECUTING_RECOVERY → MONITORING ───────────────────────────────
        self._record_state(ctx, "EXECUTING_RECOVERY", "MONITORING")
        self._log_audit(ts, "state_change", "EXECUTING_RECOVERY", "MONITORING")

        health = self._collect_health(input_dto, classification, ts)

        # ── Determine manual review ───────────────────────────────────────
        review_items: list[ManualReviewItem] = []
        manual_needed = False
        review_threshold = self._resolve_degradation_level(
            flags.manual_review_threshold,
            default=DegradationLevel.L6_PLACEHOLDER_MANUAL_REVIEW,
        )

        if _LEVEL_ORDER[current_deg_level] >= _LEVEL_ORDER[review_threshold]:
            manual_needed = True
            for sid in input_dto.failed_shot_ids or [""]:
                for eid in input_dto.failed_entity_ids or [""]:
                    review_items.append(ManualReviewItem(
                        entity_id=eid,
                        shot_id=sid,
                        reason=f"Degradation reached {current_deg_level.value}",
                        degradation_level=current_deg_level,
                        failure_classification=classification,
                        created_at=ts,
                    ))

        if classification.severity == Severity.CRITICAL:
            manual_needed = True
            if not review_items:
                review_items.append(ManualReviewItem(
                    reason="Critical severity failure",
                    failure_classification=classification,
                    created_at=ts,
                ))

        # ── Determine final status (FR4) ──────────────────────────────────
        degradation_applied = current_deg_level != DegradationLevel.L0_FULL_QUALITY
        final_status = self._determine_final_status(
            classification, degradation_applied, manual_needed, actions_taken,
        )

        # Resolve final state label
        if final_status == FinalStatus.FAILED_BLOCKING:
            terminal = "FAILED"
        elif manual_needed:
            terminal = "MANUAL_REVIEW"
        elif degradation_applied:
            terminal = "DEGRADED"
        else:
            terminal = "READY"

        self._record_state(ctx, "MONITORING", terminal)
        self._log_audit(ts, "state_change", "MONITORING", terminal, {
            "final_status": final_status.value,
        })

        # Build degradation trace
        deg_trace: list[DegradationStep] = []
        if degradation_applied:
            for step in _DEGRADATION_LADDER:
                deg_trace.append(step)
                if step.level == current_deg_level:
                    break

        logger.info(
            f"[{self.skill_id}] completed | run={ctx.run_id} "
            f"status={final_status.value} deg={current_deg_level.value} "
            f"cb_triggered={cb_triggered} manual={manual_needed} "
            f"actions={len(actions_taken)}"
        )

        return Skill18Output(
            status=final_status,
            stage=input_dto.stage,
            failure_classification=classification,
            recovery_plan=recovery_plan,
            actions_taken=actions_taken,
            degradation_applied=degradation_applied,
            degradation_level=current_deg_level,
            degradation_trace=deg_trace,
            hard_constraints_preserved=current_deg_level in (
                DegradationLevel.L0_FULL_QUALITY,
                DegradationLevel.L1_SHORTEN_DURATION,
                DegradationLevel.L2_LOWER_FPS,
            ),
            circuit_breaker_states=cb_states,
            circuit_breaker_triggered=cb_triggered,
            backend_health=health,
            cascade_impact=cascade,
            manual_review_required=manual_needed,
            manual_review_items=review_items,
            retry_budgets=retry_budgets,
            audit_trail=list(self._audit),
        )

    # ── FR1: Failure classification ───────────────────────────────────────────

    def _classify_failure(self, inp: Skill18Input) -> FailureClassification:
        error_code = inp.error_code or "UNKNOWN"

        for prefix, ftype, sev, retryable in _CLASSIFICATION_RULES:
            if error_code.startswith(prefix):
                return FailureClassification(
                    failure_type=ftype,
                    severity=sev,
                    retryable=retryable,
                    error_code=error_code,
                    source_module=inp.failed_skill,
                    description=inp.error_message or f"Failure from {inp.failed_skill}",
                )

        # Heuristic fallback from error_message keywords
        msg_lower = (inp.error_message or "").lower()
        if "timeout" in msg_lower:
            return FailureClassification(
                failure_type=FailureType.TIMEOUT,
                severity=Severity.MEDIUM,
                retryable=True,
                error_code=error_code,
                source_module=inp.failed_skill,
                description=inp.error_message,
            )
        if "rate" in msg_lower and "limit" in msg_lower:
            return FailureClassification(
                failure_type=FailureType.RATE_LIMIT,
                severity=Severity.LOW,
                retryable=True,
                error_code=error_code,
                source_module=inp.failed_skill,
                description=inp.error_message,
            )

        return FailureClassification(
            failure_type=FailureType.UNKNOWN,
            severity=Severity.MEDIUM,
            retryable=True,
            error_code=error_code,
            source_module=inp.failed_skill,
            description=inp.error_message or "Unclassified failure",
        )

    # ── Impact analysis ───────────────────────────────────────────────────────

    def _analyze_impact(
        self, inp: Skill18Input, classification: FailureClassification,
    ) -> CascadeImpact:
        blocked: list[str] = []
        skill = inp.failed_skill
        visited: set[str] = set()
        queue = [skill] if skill else []
        while queue:
            s = queue.pop(0)
            for dep in _DOWNSTREAM_DEPS.get(s, []):
                if dep not in visited:
                    visited.add(dep)
                    blocked.append(dep)
                    queue.append(dep)

        shots = list(inp.failed_shot_ids) if inp.failed_shot_ids else []
        entities = list(inp.failed_entity_ids) if inp.failed_entity_ids else []

        summary_parts: list[str] = []
        if shots:
            summary_parts.append(f"{len(shots)} shot(s) directly affected")
        if entities:
            summary_parts.append(f"{len(entities)} entity(ies) directly affected")
        if blocked:
            summary_parts.append(f"blocks downstream skills: {', '.join(blocked)}")

        return CascadeImpact(
            affected_shot_ids=shots,
            affected_entity_ids=entities,
            blocked_skills=blocked,
            impact_summary="; ".join(summary_parts) if summary_parts else "No cascade impact detected",
        )

    # ── Circuit breaker ───────────────────────────────────────────────────────

    def _evaluate_circuit_breakers(
        self,
        inp: Skill18Input,
        classification: FailureClassification,
        flags: FeatureFlags,
        ts: str,
    ) -> tuple[list[CircuitBreakerState], bool]:
        backend_id = inp.failed_backend or inp.failed_skill or "default"
        cb = self._circuit_breakers.get(backend_id)

        if cb is None:
            cb = CircuitBreakerState(
                backend_id=backend_id,
                threshold=flags.circuit_breaker_threshold,
            )
            self._circuit_breakers[backend_id] = cb

        # Record this failure
        cb.failure_count += 1
        cb.last_failure_ts = ts
        total = cb.failure_count + cb.success_count
        cb.failure_rate = cb.failure_count / max(total, 1)

        triggered = False
        if cb.state == CircuitState.CLOSED:
            if cb.failure_rate > cb.threshold and total >= 3:
                cb.state = CircuitState.OPEN
                triggered = True
                self._log_audit(ts, "circuit_breaker_opened", "", "", {
                    "backend_id": backend_id,
                    "failure_rate": cb.failure_rate,
                })
        elif cb.state == CircuitState.HALF_OPEN:
            # Failure during probe → back to open
            cb.state = CircuitState.OPEN
            triggered = True
        # If already OPEN, stays open
        if cb.state == CircuitState.OPEN:
            triggered = True

        return list(self._circuit_breakers.values()), triggered

    # ── Retry budget ──────────────────────────────────────────────────────────

    def _build_retry_budgets(
        self, inp: Skill18Input, flags: FeatureFlags,
    ) -> list[RetryBudget]:
        budgets: list[RetryBudget] = []
        ids = set(inp.failed_shot_ids or []) | set(inp.failed_entity_ids or [])
        if not ids:
            ids = {"_global"}

        for ident in ids:
            retries_used = inp.retry_count
            delay = _exp_backoff_with_jitter(retries_used)
            budgets.append(RetryBudget(
                entity_id=ident if ident in (inp.failed_entity_ids or []) else "",
                shot_id=ident if ident in (inp.failed_shot_ids or []) else "",
                max_retries=flags.max_retries,
                retries_used=retries_used,
                next_delay_seconds=round(delay, 2),
            ))
        return budgets

    # ── Recovery plan generation ──────────────────────────────────────────────

    def _build_recovery_plan(
        self,
        inp: Skill18Input,
        classification: FailureClassification,
        cb_triggered: bool,
        retry_budgets: list[RetryBudget],
        flags: FeatureFlags,
    ) -> list[RecoveryPlanStep]:
        strategies = _STRATEGY_MATRIX.get(
            classification.failure_type, _STRATEGY_MATRIX[FailureType.UNKNOWN],
        )
        budget_exhausted = all(b.retries_used >= b.max_retries for b in retry_budgets)
        plan: list[RecoveryPlanStep] = []
        order = 0

        for strat in strategies:
            # Skip retry strategies if budget exhausted
            if budget_exhausted and strat in (
                RecoveryStrategyType.RETRY_IMMEDIATE,
                RecoveryStrategyType.RETRY_BACKOFF,
            ):
                continue
            # Skip fallback if circuit breaker is tripped and no alt backend
            if cb_triggered and strat == RecoveryStrategyType.FALLBACK_BACKEND:
                if not inp.backend_capabilities:
                    continue
            if not flags.enable_backend_fallback and strat == RecoveryStrategyType.FALLBACK_BACKEND:
                continue
            # Skip degradation if disabled
            if (
                (not flags.auto_degrade_enabled or not flags.enable_degradation_ladder)
                and strat == RecoveryStrategyType.DEGRADE_ONE_LEVEL
            ):
                continue

            order += 1
            action = RecoveryAction(
                strategy=strat,
                target_skill=inp.failed_skill,
                target_backend=inp.failed_backend,
                params=self._strategy_params(strat, inp, flags),
                reason=self._strategy_reason(strat, classification, cb_triggered, budget_exhausted),
            )
            expected_deg = DegradationLevel.L0_FULL_QUALITY
            if strat == RecoveryStrategyType.DEGRADE_ONE_LEVEL:
                current_idx = _LEVEL_ORDER.get(
                    DegradationLevel.L0_FULL_QUALITY, 0,
                )
                # Estimate one level down from current
                expected_deg = _DEGRADATION_LADDER[min(current_idx + 1, len(_DEGRADATION_LADDER) - 1)].level

            plan.append(RecoveryPlanStep(
                order=order,
                action=action,
                expected_degradation=expected_deg,
                result="pending",
            ))

        # Always append manual_review as last resort if not already present
        if not any(s.action.strategy == RecoveryStrategyType.MANUAL_REVIEW for s in plan):
            order += 1
            plan.append(RecoveryPlanStep(
                order=order,
                action=RecoveryAction(
                    strategy=RecoveryStrategyType.MANUAL_REVIEW,
                    target_skill=inp.failed_skill,
                    reason="Last resort — all automated strategies exhausted",
                ),
                expected_degradation=DegradationLevel.L6_PLACEHOLDER_MANUAL_REVIEW,
                result="pending",
            ))

        return plan

    # ── Simulate plan execution ───────────────────────────────────────────────

    def _simulate_plan_execution(
        self,
        plan: list[RecoveryPlanStep],
        classification: FailureClassification,
        flags: FeatureFlags,
        ts: str,
    ) -> tuple[list[RecoveryPlanStep], DegradationLevel]:
        """Walk through plan steps deterministically.

        Since the actual retry/backend calls are outside this skill's scope,
        we produce a decision plan.  We mark the *first viable* strategy as
        the recommended action ("pending" = to be executed by orchestrator),
        and mark later steps as "pending" (fallback).

        If retries are exhausted and degradation is the recommended path,
        we walk the degradation ladder to find the target level.
        """
        _ = (classification, flags)
        current_level = DegradationLevel.L0_FULL_QUALITY
        executed: list[RecoveryPlanStep] = []
        primary_selected = False

        for step in plan:
            strat = step.action.strategy
            if primary_selected:
                executed.append(step.model_copy(update={"result": "skipped"}))
                self._log_audit(ts, "recovery_step_skipped", "", "", {
                    "order": step.order,
                    "strategy": strat.value,
                })
                continue

            if strat in (
                RecoveryStrategyType.RETRY_IMMEDIATE,
                RecoveryStrategyType.RETRY_BACKOFF,
                RecoveryStrategyType.FALLBACK_BACKEND,
            ):
                # These are actionable by the orchestrator
                executed.append(step.model_copy(update={"result": "pending"}))
                self._log_audit(ts, "recovery_step_planned", "", "", {
                    "order": step.order,
                    "strategy": strat.value,
                    "result": "pending",
                })
                primary_selected = True

            elif strat == RecoveryStrategyType.DEGRADE_ONE_LEVEL:
                # Walk degradation ladder one step
                cur_idx = _LEVEL_ORDER.get(current_level, 0)
                next_idx = min(cur_idx + 1, len(_DEGRADATION_LADDER) - 1)
                current_level = _DEGRADATION_LADDER[next_idx].level
                executed.append(step.model_copy(update={
                    "result": "pending",
                    "expected_degradation": current_level,
                }))
                self._log_audit(ts, "degradation_step", "", "", {
                    "from": _DEGRADATION_LADDER[cur_idx].level.value,
                    "to": current_level.value,
                })
                primary_selected = True

            elif strat == RecoveryStrategyType.SKIP_NON_CRITICAL:
                current_level = DegradationLevel.L7_SKIP_NON_CRITICAL
                executed.append(step.model_copy(update={
                    "result": "pending",
                    "expected_degradation": current_level,
                }))
                self._log_audit(ts, "skip_non_critical", "", "", {
                    "strategy": strat.value,
                })
                primary_selected = True

            elif strat == RecoveryStrategyType.MANUAL_REVIEW:
                executed.append(step.model_copy(update={"result": "pending"}))
                self._log_audit(ts, "manual_review_queued", "", "", {
                    "strategy": strat.value,
                })
                primary_selected = True

        return executed, current_level

    # ── Health monitoring ─────────────────────────────────────────────────────

    def _collect_health(
        self,
        inp: Skill18Input,
        classification: FailureClassification,
        ts: str,
    ) -> list[BackendHealth]:
        backend_id = inp.failed_backend or inp.failed_skill or "default"
        h = self._backend_health.get(backend_id)
        if h is None:
            h = BackendHealth(backend_id=backend_id)
            self._backend_health[backend_id] = h

        h.sample_count += 1
        h.error_rate = round(
            (h.error_rate * (h.sample_count - 1) + 1.0) / h.sample_count, 4,
        )
        h.success_rate = round(1.0 - h.error_rate, 4)

        cb = self._circuit_breakers.get(backend_id)
        if cb:
            h.circuit_state = cb.state

        return list(self._backend_health.values())

    # ── Final status (FR4) ────────────────────────────────────────────────────

    @staticmethod
    def _determine_final_status(
        classification: FailureClassification,
        degradation_applied: bool,
        manual_needed: bool,
        actions: list[RecoveryPlanStep],
    ) -> FinalStatus:
        if classification.severity == Severity.CRITICAL and not classification.retryable:
            return FinalStatus.FAILED_BLOCKING

        # If every action is skip or manual_review → blocking
        all_terminal = all(
            a.action.strategy in (
                RecoveryStrategyType.SKIP_NON_CRITICAL,
                RecoveryStrategyType.MANUAL_REVIEW,
            )
            for a in actions
        ) if actions else False

        if all_terminal and not degradation_applied:
            return FinalStatus.FAILED_BLOCKING

        if manual_needed:
            return FinalStatus.PARTIAL_REVIEW_REQUIRED

        if degradation_applied:
            return FinalStatus.SUCCESS_WITH_DEGRADATION

        return FinalStatus.SUCCESS

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _strategy_params(
        strat: RecoveryStrategyType,
        inp: Skill18Input,
        flags: FeatureFlags,
    ) -> dict[str, Any]:
        if strat == RecoveryStrategyType.RETRY_IMMEDIATE:
            return {"retry_count": inp.retry_count + 1}
        if strat == RecoveryStrategyType.RETRY_BACKOFF:
            delay = _exp_backoff_with_jitter(inp.retry_count)
            return {"retry_count": inp.retry_count + 1, "delay_seconds": round(delay, 2)}
        if strat == RecoveryStrategyType.FALLBACK_BACKEND:
            return {"backend_capabilities": inp.backend_capabilities}
        if strat == RecoveryStrategyType.DEGRADE_ONE_LEVEL:
            return {"auto_degrade_enabled": flags.auto_degrade_enabled}
        return {}

    @staticmethod
    def _strategy_reason(
        strat: RecoveryStrategyType,
        classification: FailureClassification,
        cb_triggered: bool,
        budget_exhausted: bool,
    ) -> str:
        parts = [f"failure_type={classification.failure_type.value}"]
        if cb_triggered:
            parts.append("circuit_breaker=open")
        if budget_exhausted:
            parts.append("retry_budget_exhausted")
        parts.append(f"strategy={strat.value}")
        return "; ".join(parts)

    @staticmethod
    def _resolve_degradation_level(
        level_raw: str | DegradationLevel,
        *,
        default: DegradationLevel,
    ) -> DegradationLevel:
        if isinstance(level_raw, DegradationLevel):
            return level_raw
        if level_raw in _LEGACY_DEGRADATION_LEVEL_MAP:
            return _LEGACY_DEGRADATION_LEVEL_MAP[level_raw]
        try:
            return DegradationLevel(str(level_raw))
        except ValueError:
            return default

    def _log_audit(
        self,
        ts: str,
        event: str,
        from_state: str,
        to_state: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self._audit.append(AuditEntry(
            timestamp=ts,
            event=event,
            from_state=from_state,
            to_state=to_state,
            details=details or {},
        ))


# ── Module-level utilities ────────────────────────────────────────────────────

def _exp_backoff_with_jitter(retries: int, base: float = 2.0, jitter_max: float = 1.0) -> float:
    """Exponential backoff: base^retries + uniform jitter."""
    backoff = math.pow(base, retries)
    jitter = random.uniform(0, jitter_max)  # noqa: S311
    return backoff + jitter
