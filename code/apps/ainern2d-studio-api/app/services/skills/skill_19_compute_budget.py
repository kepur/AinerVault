"""SKILL 19: ComputeBudgetService — 业务逻辑实现。
参考规格: SKILL_19_COMPUTE_AWARE_SHOT_BUDGETER.md
状态机: INIT → ESTIMATING → PRIORITIZING → ALLOCATING → ROUTING →
        PLANNING_PARALLEL → BALANCING_SLA → READY | OVER_BUDGET |
        REVIEW_REQUIRED | FAILED
"""
from __future__ import annotations

import hashlib
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from ainern2d_shared.schemas.skills.skill_19 import (
    BackendCapability,
    BudgetAlert,
    BudgetSummary,
    BudgeterState,
    Complexity,
    CostEstimate,
    DegradationLadderProfile,
    DegradationStep,
    ParallelBatch,
    PriorityScore,
    RenderPriority,
    SLAConfig,
    SLATier,
    HistoricalRenderStat,
    Skill19FeatureFlags,
    Skill19Input,
    Skill19Output,
    Skill19UserOverrides,
    ShotComputePlan,
    ShotInputDetail,
)
from ainern2d_shared.services.base_skill import BaseSkillService, SkillContext

# ── Error codes (PLAN-BUDGET-xxx) ────────────────────────────────────────────

ERR_NO_SHOTS = "PLAN-BUDGET-001"
ERR_OVER_BUDGET = "PLAN-BUDGET-002"
ERR_NO_BACKEND = "PLAN-BUDGET-003"
ERR_ESTIMATION_FAIL = "PLAN-BUDGET-004"

# ── GPU tier capability map ──────────────────────────────────────────────────

_GPU_TIERS: dict[str, dict[str, Any]] = {
    "A100": {"max_fps": 24, "max_resolution": "1280x720", "secs_per_frame": 0.5, "rate": 1.0},
    "A10G": {"max_fps": 24, "max_resolution": "1280x720", "secs_per_frame": 0.8, "rate": 0.7},
    "T4":   {"max_fps": 16, "max_resolution": "960x540",  "secs_per_frame": 1.5, "rate": 0.4},
    "CPU":  {"max_fps": 1,  "max_resolution": "640x360",  "secs_per_frame": 5.0, "rate": 0.1},
}

# ── Action complexity keywords ───────────────────────────────────────────────

_ACTION_COMPLEXITY: dict[str, float] = {
    "battle": 2.0, "fight": 2.0, "chase": 1.8, "explosion": 2.0,
    "run": 1.5, "walk": 1.2, "dance": 1.6,
    "dialogue": 0.8, "talk": 0.8, "static": 0.5, "establishing": 0.6,
}

# ── Shot type base complexity ────────────────────────────────────────────────

_SHOT_TYPE_COMPLEXITY: dict[str, float] = {
    "action": 1.8, "battle": 2.0, "chase": 1.8,
    "dialogue": 0.8, "establishing": 0.6,
    "transition": 0.5, "closeup": 1.0, "montage": 1.3,
}

# ── Baseline FPS per global load profile ─────────────────────────────────────

_LOAD_BASELINE_FPS: dict[str, int] = {"LOW": 8, "MEDIUM": 12, "HIGH": 24}

# ── Resolution pixel count for cost factor ───────────────────────────────────

_RES_PIXELS: dict[str, float] = {
    "1920x1080": 2073600, "1280x720": 921600, "960x540": 518400,
    "640x360": 230400, "512x512": 262144,
}
_REF_PIXELS: float = 921600.0  # 720p as reference = 1.0

# ── SLA tier configs ─────────────────────────────────────────────────────────

_SLA_CONFIGS: dict[SLATier, SLAConfig] = {
    SLATier.PREMIUM: SLAConfig(
        tier=SLATier.PREMIUM, min_fps=24, min_resolution="1280x720",
        min_quality=0.85, max_degradation_level=2, priority_boost=0.3,
    ),
    SLATier.STANDARD: SLAConfig(
        tier=SLATier.STANDARD, min_fps=12, min_resolution="960x540",
        min_quality=0.5, max_degradation_level=5, priority_boost=0.0,
    ),
    SLATier.ECONOMY: SLAConfig(
        tier=SLATier.ECONOMY, min_fps=8, min_resolution="640x360",
        min_quality=0.3, max_degradation_level=7, priority_boost=-0.2,
    ),
}

# ── 8-level degradation ladder (linked to SKILL 18) ─────────────────────────

_DEGRADATION_LADDER: list[DegradationStep] = [
    DegradationStep(level=1, action="retry_same", description="同参数重试", quality_floor=1.0),
    DegradationStep(level=2, action="switch_backend", description="换后端/换模型", quality_floor=0.95),
    DegradationStep(level=3, action="shorten_duration", description="缩短时长", quality_floor=0.85),
    DegradationStep(level=4, action="reduce_fps", description="降低帧率", quality_floor=0.70),
    DegradationStep(level=5, action="reduce_resolution", description="降低分辨率", quality_floor=0.55),
    DegradationStep(level=6, action="microshot_split", description="拆成更短微镜头重试", quality_floor=0.40),
    DegradationStep(level=7, action="static_with_effect", description="静态图+动效(Ken Burns)", quality_floor=0.25),
    DegradationStep(level=8, action="placeholder_review", description="placeholder+标记manual review", quality_floor=0.10),
]

# ── Default backends ─────────────────────────────────────────────────────────

_DEFAULT_BACKENDS: list[BackendCapability] = [
    BackendCapability(
        backend_id="comfyui_i2v", max_resolution="1280x720", max_fps=24,
        supported_modes=["T2I", "I2V"], gpu_sec_rate=1.0,
        max_concurrent_jobs=4, available_slots=4, quality_ceiling=0.9,
    ),
    BackendCapability(
        backend_id="wan_i2v", max_resolution="1280x720", max_fps=24,
        supported_modes=["I2V", "I2V_START_END"], gpu_sec_rate=1.3,
        max_concurrent_jobs=2, available_slots=2, quality_ceiling=1.0,
    ),
    BackendCapability(
        backend_id="hunyuan_i2v", max_resolution="1920x1080", max_fps=24,
        supported_modes=["T2I", "I2V"], gpu_sec_rate=1.5,
        max_concurrent_jobs=2, available_slots=2, quality_ceiling=1.0,
    ),
]


# ── Helpers ──────────────────────────────────────────────────────────────────


def _stable_id(prefix: str, *parts: str) -> str:
    raw = ":".join(parts)
    return f"{prefix}_{hashlib.md5(raw.encode()).hexdigest()[:8]}"


def _res_factor(resolution: str) -> float:
    return _RES_PIXELS.get(resolution, _REF_PIXELS) / _REF_PIXELS


def _compute_priority_score(shot: ShotInputDetail, boost_ids: list[str],
                            sla_boost: float) -> PriorityScore:
    """Score shots by narrative_importance, visual_complexity, entity_count,
    motion_score, user_priority (§6)."""
    user_p = shot.user_priority
    if shot.shot_id in boost_ids:
        user_p = max(user_p, 1.0)

    entity_factor = min(shot.entity_count / 5.0, 1.0)
    composite = (
        shot.narrative_importance * 0.30
        + shot.visual_complexity * 0.25
        + entity_factor * 0.10
        + shot.motion_score * 0.20
        + user_p * 0.15
        + sla_boost
    )
    return PriorityScore(
        narrative_importance=shot.narrative_importance,
        visual_complexity=shot.visual_complexity,
        entity_count=shot.entity_count,
        motion_score=shot.motion_score,
        user_priority=user_p,
        composite_score=round(min(max(composite, 0.0), 1.0), 4),
    )


def _complexity_from_shot(shot: ShotInputDetail) -> tuple[Complexity, float]:
    """Derive complexity enum + numeric multiplier from shot attributes."""
    base = _SHOT_TYPE_COMPLEXITY.get(shot.shot_type, 1.0)

    action_max = 1.0
    for cue in shot.action_cues:
        cue_lower = cue.lower()
        for kw, mult in _ACTION_COMPLEXITY.items():
            if kw in cue_lower:
                action_max = max(action_max, mult)

    combined = base * 0.4 + action_max * 0.3 + shot.motion_score * 1.5 * 0.3
    if combined >= 1.4:
        return Complexity.HIGH, combined
    if combined >= 0.9:
        return Complexity.MEDIUM, combined
    return Complexity.LOW, combined


def _estimate_shot_cost(
    duration: float, fps: int, resolution: str,
    backend_rate: float, quality_mult: float,
) -> CostEstimate:
    """Cost = resolution_factor × fps × duration × backend_rate × quality_mult."""
    rf = _res_factor(resolution)
    gpu_sec = duration * fps * rf * backend_rate * quality_mult
    return CostEstimate(
        gpu_sec=round(gpu_sec, 2),
        gpu_minutes=round(gpu_sec / 60.0, 4),
        cost_usd=round(gpu_sec * 0.0001, 6),
        resolution_factor=round(rf, 4),
        fps_factor=float(fps),
        duration_factor=duration,
        backend_rate=backend_rate,
        quality_multiplier=quality_mult,
    )


def _build_history_index(
    history_stats: list[HistoricalRenderStat],
) -> dict[tuple[str, str], HistoricalRenderStat]:
    idx: dict[tuple[str, str], HistoricalRenderStat] = {}
    for stat in history_stats:
        shot_type = (stat.shot_type or "*").strip().lower() or "*"
        if isinstance(stat.complexity, Complexity):
            complexity = stat.complexity.value
        elif stat.complexity:
            complexity = str(stat.complexity).strip().lower()
        else:
            complexity = "*"
        idx[(shot_type, complexity)] = stat
    return idx


def _resolve_history_stat(
    shot: ShotInputDetail,
    complexity: Complexity,
    history_idx: dict[tuple[str, str], HistoricalRenderStat],
) -> HistoricalRenderStat | None:
    shot_type = (shot.shot_type or "").strip().lower()
    candidates = [
        (shot_type, complexity.value),
        (shot_type, "*"),
        ("*", complexity.value),
        ("*", "*"),
    ]
    for key in candidates:
        if key in history_idx:
            return history_idx[key]
    return None


def _apply_historical_feedback(
    cost: CostEstimate,
    duration_seconds: float,
    stat: HistoricalRenderStat | None,
) -> CostEstimate:
    """Blend model estimate with historical rendering stats.

    sample_count drives confidence; overrun_rate adds conservative headroom.
    """
    if (
        stat is None
        or stat.sample_count < 3
        or duration_seconds <= 0.0
        or stat.avg_gpu_sec_per_second <= 0.0
    ):
        return cost

    base_gpu_sec = float(cost.gpu_sec)
    hist_gpu_sec = stat.avg_gpu_sec_per_second * duration_seconds
    if stat.p95_gpu_sec_per_second and stat.p95_gpu_sec_per_second > 0:
        hist_gpu_sec = max(hist_gpu_sec, stat.p95_gpu_sec_per_second * duration_seconds * 0.8)

    confidence = min(max(stat.sample_count / 20.0, 0.0), 1.0)
    blended_gpu_sec = base_gpu_sec * (1.0 - confidence) + hist_gpu_sec * confidence

    overrun_rate = min(max(stat.overrun_rate, -0.5), 1.0)
    adjusted_gpu_sec = max(blended_gpu_sec * (1.0 + overrun_rate * 0.35), 0.01)
    factor = adjusted_gpu_sec / max(base_gpu_sec, 0.001)

    return cost.model_copy(update={
        "gpu_sec": round(adjusted_gpu_sec, 2),
        "gpu_minutes": round(adjusted_gpu_sec / 60.0, 4),
        "cost_usd": round(adjusted_gpu_sec * 0.0001, 6),
        "historical_factor": round(factor, 4),
        "history_confidence": round(confidence, 4),
    })


def _build_degradation_profile(
    complexity: Complexity, criticality: str, sla_max_level: int,
) -> DegradationLadderProfile:
    """Per-shot degradation profile linked to SKILL 18's 8-level ladder."""
    if criticality == "critical":
        max_level = min(2, sla_max_level)
    elif complexity == Complexity.HIGH:
        max_level = min(4, sla_max_level)
    elif complexity == Complexity.LOW:
        max_level = min(sla_max_level, 7)
    else:
        max_level = min(sla_max_level, 5)

    profile_tag = f"DL_{complexity.value.upper()}_MOTION_V1"
    if criticality == "critical":
        profile_tag = f"DL_CRITICAL_{complexity.value.upper()}_V1"

    return DegradationLadderProfile(
        profile_id=profile_tag,
        max_acceptable_level=max_level,
        steps=[s for s in _DEGRADATION_LADDER if s.level <= max_level],
    )


def _select_backends(
    shot: ShotInputDetail, complexity: Complexity,
    available: list[BackendCapability], force_backend: str,
) -> list[str]:
    """Route shot to backend(s) based on compute requirements + capabilities.
    Support multi-backend splitting for complex shots."""
    if force_backend:
        return [force_backend]

    if shot.preferred_backend:
        return [shot.preferred_backend]

    candidates: list[tuple[float, str]] = []
    for be in available:
        if be.available_slots <= 0:
            continue
        score = be.quality_ceiling - (be.gpu_sec_rate * 0.1)
        if complexity == Complexity.HIGH:
            score += be.quality_ceiling * 0.3
        if be.available_slots > 1:
            score += 0.1
        candidates.append((score, be.backend_id))

    candidates.sort(key=lambda x: x[0], reverse=True)

    if complexity == Complexity.HIGH and len(candidates) >= 2:
        return [c[1] for c in candidates[:2]]
    if candidates:
        return [candidates[0][1]]
    return ["comfyui_i2v"]


def _render_priority_from_score(score: float) -> RenderPriority:
    if score >= 0.75:
        return RenderPriority.CRITICAL
    if score >= 0.55:
        return RenderPriority.HIGH
    if score >= 0.30:
        return RenderPriority.NORMAL
    return RenderPriority.LOW


# ── Service ──────────────────────────────────────────────────────────────────


class ComputeBudgetService(BaseSkillService[Skill19Input, Skill19Output]):
    """SKILL 19 — Compute-Aware Shot Budgeter.

    State machine:
      INIT → ESTIMATING → PRIORITIZING → ALLOCATING → ROUTING →
      PLANNING_PARALLEL → BALANCING_SLA → READY | OVER_BUDGET |
      REVIEW_REQUIRED | FAILED
    """

    skill_id = "skill_19"
    skill_name = "ComputeBudgetService"

    def __init__(self, db: Session) -> None:
        super().__init__(db)

    # ── public execute ───────────────────────────────────────────────────────

    def execute(self, input_dto: Skill19Input, ctx: SkillContext) -> Skill19Output:
        flags = input_dto.feature_flags
        overrides = input_dto.user_overrides
        sla_tier = flags.sla_tier
        sla_cfg = _SLA_CONFIGS.get(sla_tier, _SLA_CONFIGS[SLATier.STANDARD])

        cluster = input_dto.cluster_resources
        gpu_tier = cluster.gpu_tier if cluster.gpu_tier in _GPU_TIERS else "A100"
        tier_cfg = _GPU_TIERS[gpu_tier]
        total_budget_gpu_sec = cluster.gpu_hours_budget * 3600.0

        budget_cap = overrides.budget_cap_override
        if budget_cap is not None and budget_cap > 0:
            total_budget_gpu_sec = budget_cap * 3600.0

        backends = cluster.backends or _DEFAULT_BACKENDS
        global_profile = input_dto.global_load_profile.upper()
        baseline_fps = _LOAD_BASELINE_FPS.get(global_profile, 12)
        history_idx = _build_history_index(input_dto.historical_render_stats)

        # ── INIT → ESTIMATING ────────────────────────────────────────────────
        self._record_state(ctx, BudgeterState.INIT, BudgeterState.ESTIMATING)

        if not input_dto.shots:
            logger.warning(f"[{self.skill_id}] {ERR_NO_SHOTS}: no shots provided")
            self._record_state(ctx, BudgeterState.ESTIMATING, BudgeterState.FAILED)
            return Skill19Output(
                status="failed", state=BudgeterState.FAILED,
                global_profile=global_profile, sla_tier=sla_tier,
            )

        shot_plans: list[ShotComputePlan] = []
        reallocation_log: list[dict[str, Any]] = []

        for shot in input_dto.shots:
            complexity_enum, complexity_val = _complexity_from_shot(shot)

            # Cost estimation
            quality_mult = 1.0
            if complexity_enum == Complexity.HIGH:
                quality_mult = 1.3
            elif complexity_enum == Complexity.LOW:
                quality_mult = 0.7

            target_fps = baseline_fps
            if flags.enable_dynamic_fps:
                if complexity_enum == Complexity.HIGH:
                    target_fps = min(tier_cfg["max_fps"], 24)
                elif complexity_enum == Complexity.LOW:
                    target_fps = max(sla_cfg.min_fps, 8)

            target_resolution = tier_cfg["max_resolution"]
            backend_rate = tier_cfg["rate"]

            cost = _estimate_shot_cost(
                shot.duration_seconds, target_fps, target_resolution,
                backend_rate, quality_mult,
            )
            cost = _apply_historical_feedback(
                cost,
                shot.duration_seconds,
                _resolve_history_stat(shot, complexity_enum, history_idx),
            )

            # Segment policy for long high-complexity shots
            segment_policy = ""
            if complexity_enum == Complexity.HIGH and shot.duration_seconds > 1.0:
                segment_policy = "microshot_split_if_duration_gt_1000ms"

            plan = ShotComputePlan(
                shot_id=shot.shot_id,
                complexity=complexity_enum,
                fps=target_fps,
                resolution=target_resolution,
                target_fps=target_fps,
                target_resolution=target_resolution,
                gpu_tier=gpu_tier,
                estimated_seconds=round(cost.gpu_sec, 2),
                estimated_cost=cost,
                segment_policy=segment_policy,
            )
            shot_plans.append(plan)

        # ── ESTIMATING → PRIORITIZING ────────────────────────────────────────
        self._record_state(ctx, BudgeterState.ESTIMATING, BudgeterState.PRIORITIZING)

        boost_ids = overrides.priority_boost_shots
        for i, plan in enumerate(shot_plans):
            shot = input_dto.shots[i]
            pscore = _compute_priority_score(shot, boost_ids, sla_cfg.priority_boost)
            plan.priority_score = pscore
            plan.render_priority = _render_priority_from_score(pscore.composite_score)

        # Sort by priority descending for allocation
        shot_plans.sort(key=lambda p: p.priority_score.composite_score, reverse=True)

        # ── PRIORITIZING → ALLOCATING ────────────────────────────────────────
        self._record_state(ctx, BudgeterState.PRIORITIZING, BudgeterState.ALLOCATING)

        total_estimated = sum(p.estimated_cost.gpu_sec for p in shot_plans)
        self._allocate_budgets(shot_plans, total_budget_gpu_sec, total_estimated)

        # Retry budget based on priority
        for plan in shot_plans:
            if plan.render_priority == RenderPriority.CRITICAL:
                plan.retry_budget = 3
            elif plan.render_priority == RenderPriority.HIGH:
                plan.retry_budget = 2
            else:
                plan.retry_budget = 1

        # ── ALLOCATING → ROUTING ─────────────────────────────────────────────
        self._record_state(ctx, BudgeterState.ALLOCATING, BudgeterState.ROUTING)

        for i, plan in enumerate(shot_plans):
            shot = input_dto.shots[self._find_shot_index(input_dto.shots, plan.shot_id)]
            plan.backend_preference = _select_backends(
                shot, plan.complexity, backends, overrides.force_backend,
            )

            # Build degradation profile
            plan.degradation_profile = _build_degradation_profile(
                plan.complexity, shot.criticality, sla_cfg.max_degradation_level,
            )
            plan.degrade_ladder_profile = plan.degradation_profile.profile_id

        # ── ROUTING → PLANNING_PARALLEL ──────────────────────────────────────
        self._record_state(ctx, BudgeterState.ROUTING, BudgeterState.PLANNING_PARALLEL)

        dep_map = {s.shot_id: set(s.dependencies) for s in input_dto.shots}
        batches = self._plan_parallel_batches(
            shot_plans, dep_map, backends, flags.max_parallel_batches,
        )

        # ── PLANNING_PARALLEL → BALANCING_SLA ────────────────────────────────
        self._record_state(ctx, BudgeterState.PLANNING_PARALLEL, BudgeterState.BALANCING_SLA)

        self._enforce_sla_minimums(shot_plans, sla_cfg)

        # Recalculate totals after SLA enforcement
        total_estimated = sum(p.estimated_cost.gpu_sec for p in shot_plans)
        total_gpu_hours = round(total_estimated / 3600.0, 4)
        total_gpu_minutes = round(total_estimated / 60.0, 4)
        utilization = round(total_estimated / max(total_budget_gpu_sec, 0.001), 4)
        max_gpu_minutes = round(total_budget_gpu_sec / 60.0, 4)
        total_cost_usd = round(sum(p.estimated_cost.cost_usd for p in shot_plans), 6)

        # ── Budget alerting ──────────────────────────────────────────────────
        alerts = self._check_budget_alerts(utilization, flags.budget_alert_thresholds)

        # ── Dynamic reallocation (if under-budget, redistribute to high-priority) ─
        if flags.enable_dynamic_reallocation and utilization < 0.95:
            reallocation_log = self._dynamic_reallocation(
                shot_plans, total_budget_gpu_sec, total_estimated,
            )

        # ── Determine final state ────────────────────────────────────────────
        final_state = BudgeterState.READY
        status = "compute_plan_ready"
        staged = False

        if utilization > 1.0:
            final_state = BudgeterState.OVER_BUDGET
            status = "over_budget"
            staged = True
        elif any(a.severity == "critical" for a in alerts):
            final_state = BudgeterState.REVIEW_REQUIRED
            status = "review_required"

        self._record_state(ctx, BudgeterState.BALANCING_SLA, final_state)

        budget_summary = BudgetSummary(
            max_gpu_minutes=max_gpu_minutes,
            estimated_gpu_minutes=total_gpu_minutes,
            total_gpu_hours=total_gpu_hours,
            budget_utilization=utilization,
            total_cost_usd=total_cost_usd,
        )

        logger.info(
            f"[{self.skill_id}] {final_state.value} | run={ctx.run_id} "
            f"shots={len(shot_plans)} gpu_h={total_gpu_hours} util={utilization} "
            f"alerts={len(alerts)} batches={len(batches)}"
        )

        return Skill19Output(
            version="1.0",
            status=status,
            state=final_state,
            global_profile=global_profile,
            sla_tier=sla_tier,
            budget_summary=budget_summary,
            shot_plans=shot_plans,
            parallel_batches=batches,
            alerts=alerts,
            staged_delivery=staged,
            reallocation_log=reallocation_log,
            total_gpu_hours=total_gpu_hours,
            budget_utilization=utilization,
        )

    # ── Budget allocation ────────────────────────────────────────────────────

    def _allocate_budgets(
        self, plans: list[ShotComputePlan],
        total_budget: float, total_estimated: float,
    ) -> None:
        """Allocate budget with a blended loop:
        priority score + estimated demand + historical risk feedback.
        """
        if total_estimated <= 0:
            return

        total_priority = sum(p.priority_score.composite_score for p in plans) or 1.0
        raw_weights: list[float] = []
        for plan in plans:
            priority_norm = plan.priority_score.composite_score / total_priority
            demand_norm = plan.estimated_cost.gpu_sec / total_estimated
            history_factor = min(max(plan.estimated_cost.historical_factor, 0.75), 1.35)
            raw_weights.append((0.6 * priority_norm + 0.4 * demand_norm) * history_factor)

        total_raw = sum(raw_weights) or 1.0
        for i, plan in enumerate(plans):
            weight = raw_weights[i] / total_raw
            plan.allocated_budget_gpu_sec = round(total_budget * weight, 2)

    # ── Dynamic reallocation ─────────────────────────────────────────────────

    def _dynamic_reallocation(
        self, plans: list[ShotComputePlan],
        total_budget: float, total_estimated: float,
    ) -> list[dict[str, Any]]:
        """Budget feedback loop for under-budget scenarios.

        Phase-1: fill high-priority deficit shots first (allocated < estimated).
        Phase-2: distribute leftover surplus by priority score.
        """
        log: list[dict[str, Any]] = []
        surplus = total_budget - total_estimated
        if surplus <= 0:
            return log

        target_plans = [p for p in plans if p.priority_score.composite_score >= 0.3]
        if not target_plans:
            return log

        remaining = surplus
        deficit_plans = [
            p for p in target_plans
            if p.estimated_cost.gpu_sec > p.allocated_budget_gpu_sec + 0.01
        ]

        if deficit_plans:
            weighted_gap: dict[str, float] = {}
            for plan in deficit_plans:
                gap = plan.estimated_cost.gpu_sec - plan.allocated_budget_gpu_sec
                weighted_gap[plan.shot_id] = gap * (0.5 + plan.priority_score.composite_score)
            total_gap_weight = sum(weighted_gap.values()) or 1.0

            distributed = 0.0
            for plan in deficit_plans:
                gap = max(plan.estimated_cost.gpu_sec - plan.allocated_budget_gpu_sec, 0.0)
                if gap <= 0:
                    continue
                share = min(
                    remaining * (weighted_gap[plan.shot_id] / total_gap_weight),
                    gap,
                )
                if share <= 0.01:
                    continue
                old_alloc = plan.allocated_budget_gpu_sec
                new_alloc = round(old_alloc + share, 2)
                plan.allocated_budget_gpu_sec = new_alloc
                distributed += float(new_alloc - old_alloc)
                log.append({
                    "shot_id": plan.shot_id,
                    "action": "deficit_fill",
                    "old_budget_gpu_sec": old_alloc,
                    "new_budget_gpu_sec": new_alloc,
                    "added_gpu_sec": round(new_alloc - old_alloc, 2),
                })
            remaining = max(0.0, remaining - distributed)

        if remaining <= 0.01:
            return log

        total_score = sum(p.priority_score.composite_score for p in target_plans) or 1.0
        for plan in target_plans:
            share = remaining * (plan.priority_score.composite_score / total_score)
            if share <= 0.01:
                continue
            old_alloc = plan.allocated_budget_gpu_sec
            new_alloc = round(old_alloc + share, 2)
            plan.allocated_budget_gpu_sec = new_alloc
            log.append({
                "shot_id": plan.shot_id,
                "action": "surplus_reallocation",
                "old_budget_gpu_sec": old_alloc,
                "new_budget_gpu_sec": new_alloc,
                "surplus_share": round(new_alloc - old_alloc, 2),
            })

        return log

    # ── SLA enforcement ──────────────────────────────────────────────────────

    def _enforce_sla_minimums(
        self, plans: list[ShotComputePlan], sla: SLAConfig,
    ) -> None:
        """Enforce SLA minimum quality per tier; adjust fps/resolution upward
        if plan falls below SLA floor."""
        for plan in plans:
            if plan.target_fps < sla.min_fps:
                plan.target_fps = sla.min_fps
                plan.fps = sla.min_fps

            # Check resolution (compare pixel counts)
            plan_pixels = _RES_PIXELS.get(plan.target_resolution, _REF_PIXELS)
            sla_pixels = _RES_PIXELS.get(sla.min_resolution, 0)
            if plan_pixels < sla_pixels:
                plan.target_resolution = sla.min_resolution
                plan.resolution = sla.min_resolution

            # Clamp degradation profile to SLA max level
            if plan.degradation_profile.max_acceptable_level > sla.max_degradation_level:
                plan.degradation_profile.max_acceptable_level = sla.max_degradation_level
                plan.degradation_profile.steps = [
                    s for s in plan.degradation_profile.steps
                    if s.level <= sla.max_degradation_level
                ]

    # ── Backend routing helpers ──────────────────────────────────────────────

    @staticmethod
    def _find_shot_index(shots: list[ShotInputDetail], shot_id: str) -> int:
        for i, s in enumerate(shots):
            if s.shot_id == shot_id:
                return i
        return 0

    # ── Parallel execution planning ──────────────────────────────────────────

    def _plan_parallel_batches(
        self, plans: list[ShotComputePlan],
        dep_map: dict[str, set[str]],
        backends: list[BackendCapability],
        max_batches: int,
    ) -> list[ParallelBatch]:
        """Group non-dependent shots for parallel execution.
        Calculate optimal batch sizes per backend."""
        scheduled: set[str] = set()
        batches: list[ParallelBatch] = []
        remaining = [p for p in plans]
        batch_num = 0

        backend_slots = {b.backend_id: b.max_concurrent_jobs for b in backends}

        while remaining and batch_num < max_batches * 3:
            batch_num += 1
            ready: list[ShotComputePlan] = []
            for plan in remaining:
                deps = dep_map.get(plan.shot_id, set())
                if deps.issubset(scheduled):
                    ready.append(plan)

            if not ready:
                break

            # Group by preferred backend, respecting concurrency limits
            per_backend: dict[str, list[ShotComputePlan]] = {}
            for plan in ready:
                be = plan.backend_preference[0] if plan.backend_preference else "comfyui_i2v"
                per_backend.setdefault(be, []).append(plan)

            for be_id, be_plans in per_backend.items():
                slots = backend_slots.get(be_id, 4)
                chunk = be_plans[:slots]
                if not chunk:
                    continue

                batch_id = _stable_id("batch", str(batch_num), be_id)
                est = sum(p.estimated_cost.gpu_sec for p in chunk)

                for p in chunk:
                    p.batch_id = batch_id

                batches.append(ParallelBatch(
                    batch_id=batch_id,
                    shot_ids=[p.shot_id for p in chunk],
                    backend_id=be_id,
                    estimated_gpu_sec=round(est, 2),
                    max_concurrency=min(len(chunk), slots),
                ))

                for p in chunk:
                    scheduled.add(p.shot_id)

            remaining = [p for p in remaining if p.shot_id not in scheduled]

        return batches

    # ── Budget alerting ──────────────────────────────────────────────────────

    @staticmethod
    def _check_budget_alerts(
        utilization: float, thresholds: list[float],
    ) -> list[BudgetAlert]:
        """Warn when estimated cost exceeds configurable thresholds."""
        alerts: list[BudgetAlert] = []
        for threshold in sorted(thresholds):
            if utilization >= threshold:
                pct = int(threshold * 100)
                severity = "info"
                if threshold >= 1.0:
                    severity = "critical"
                elif threshold >= 0.9:
                    severity = "error"
                elif threshold >= 0.75:
                    severity = "warning"

                alerts.append(BudgetAlert(
                    threshold=threshold,
                    current_utilization=round(utilization, 4),
                    message=f"Budget utilization at {round(utilization * 100, 1)}% — "
                            f"exceeded {pct}% threshold",
                    severity=severity,
                ))
        return alerts
