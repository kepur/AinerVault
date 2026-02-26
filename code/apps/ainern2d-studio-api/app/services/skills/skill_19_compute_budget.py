"""SKILL 19: ComputeBudgetService — 业务逻辑实现。
参考规格: SKILL_19_COMPUTE_AWARE_SHOT_BUDGETER.md
状态: SERVICE_READY
"""
from __future__ import annotations

from loguru import logger
from sqlalchemy.orm import Session

from ainern2d_shared.schemas.skills.skill_19 import (
    Skill19Input,
    Skill19Output,
    ShotComputePlan,
)
from ainern2d_shared.services.base_skill import BaseSkillService, SkillContext

# ── GPU tier capability map ───────────────────────────────────────────────────
_GPU_TIERS: dict[str, dict] = {
    "A100": {"fps": 24, "resolution": "1280x720", "secs_per_frame": 0.5},
    "A10G": {"fps": 24, "resolution": "1280x720", "secs_per_frame": 0.8},
    "T4":   {"fps": 16, "resolution": "960x540",  "secs_per_frame": 1.5},
    "CPU":  {"fps": 1,  "resolution": "640x360",  "secs_per_frame": 5.0},
}

_ACTION_COMPLEXITY: dict[str, float] = {
    "battle": 2.0, "fight": 2.0, "chase": 1.8,
    "walk": 1.2, "run": 1.5,
    "dialogue": 0.8, "talk": 0.8, "static": 0.5,
}


class ComputeBudgetService(BaseSkillService[Skill19Input, Skill19Output]):
    """SKILL 19 — Compute-Aware Shot Budgeter.

    State machine:
      INIT → PROFILING_CLUSTER → ESTIMATING_SHOTS → ALLOCATING → COMPUTE_PLAN_READY | FAILED
    """

    skill_id = "skill_19"
    skill_name = "ComputeBudgetService"

    def __init__(self, db: Session) -> None:
        super().__init__(db)

    def execute(self, input_dto: Skill19Input, ctx: SkillContext) -> Skill19Output:
        self._record_state(ctx, "INIT", "PROFILING_CLUSTER")

        cluster = input_dto.cluster_resources or {}
        gpu_tier = cluster.get("gpu_tier", "A100")
        if gpu_tier not in _GPU_TIERS:
            gpu_tier = "A100"
        tier_cfg = _GPU_TIERS[gpu_tier]

        total_gpu_budget_hours = float(cluster.get("gpu_hours_budget", 10.0))

        self._record_state(ctx, "PROFILING_CLUSTER", "ESTIMATING_SHOTS")

        shot_plans: list[ShotComputePlan] = []
        total_secs = 0.0

        for i, shot in enumerate(input_dto.shots or []):
            shot_id = shot.get("shot_id", f"shot_{i:03d}")
            duration = float(shot.get("duration_seconds", 3.0))
            action_cues = shot.get("action_cues", [])

            complexity = 1.0
            for cue in action_cues:
                cue_lower = str(cue).lower()
                for kw, mult in _ACTION_COMPLEXITY.items():
                    if kw in cue_lower:
                        complexity = max(complexity, mult)

            est_secs = duration * tier_cfg["secs_per_frame"] * tier_cfg["fps"] * complexity / tier_cfg["fps"]
            total_secs += est_secs

            shot_plans.append(ShotComputePlan(
                shot_id=shot_id,
                fps=tier_cfg["fps"],
                resolution=tier_cfg["resolution"],
                priority=i,
                gpu_tier=gpu_tier,
                estimated_seconds=round(est_secs, 2),
            ))

        self._record_state(ctx, "ESTIMATING_SHOTS", "ALLOCATING")

        total_gpu_hours = round(total_secs / 3600.0, 4)
        utilization = round(total_gpu_hours / max(total_gpu_budget_hours, 0.001), 4)

        self._record_state(ctx, "ALLOCATING", "COMPUTE_PLAN_READY")

        logger.info(
            f"[{self.skill_id}] completed | run={ctx.run_id} "
            f"shots={len(shot_plans)} gpu_hours={total_gpu_hours} util={utilization}"
        )

        return Skill19Output(
            shot_plans=shot_plans,
            total_gpu_hours=total_gpu_hours,
            budget_utilization=utilization,
            status="compute_plan_ready",
        )
