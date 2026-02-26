from __future__ import annotations

from sqlalchemy.orm import Session

from ainern2d_shared.schemas.timeline import ShotPlan, ShotPlanItem

# Rough cost per second of rendered video (USD)
_COST_PER_SEC: dict[str, float] = {
    "draft": 0.01,
    "standard": 0.05,
    "ultra": 0.15,
}


class BudgetDegrader:
    def __init__(self, db: Session) -> None:
        self.db = db

    def estimate_cost(self, shot_plan: ShotPlan) -> float:
        total = 0.0
        for item in shot_plan.shots:
            tags_lower = [t.lower() for t in item.style_tags]
            if "draft" in tags_lower:
                rate = _COST_PER_SEC["draft"]
            elif "ultra" in tags_lower:
                rate = _COST_PER_SEC["ultra"]
            else:
                rate = _COST_PER_SEC["standard"]
            total += (item.duration_ms / 1000.0) * rate
        return round(total, 4)

    def apply(
        self,
        shot_plan: ShotPlan,
        budget_profile: str,
        max_cost: float | None = None,
    ) -> ShotPlan:
        if max_cost is None:
            return shot_plan

        current_cost = self.estimate_cost(shot_plan)
        if current_cost <= max_cost:
            return shot_plan

        # Degrade: lower quality tags and shorten durations
        adjusted: list[ShotPlanItem] = []
        for item in shot_plan.shots:
            new_tags = [t for t in item.style_tags if t.lower() != "ultra"]
            if "draft" not in [t.lower() for t in new_tags]:
                new_tags.append("draft")
            new_dur = max(3000, int(item.duration_ms * 0.7))
            adjusted.append(
                item.model_copy(update={"style_tags": new_tags, "duration_ms": new_dur})
            )

        degraded = ShotPlan(run_id=shot_plan.run_id, shots=adjusted)

        # If still over budget, reduce shot count
        if self.estimate_cost(degraded) > max_cost and len(adjusted) > 1:
            ratio = max_cost / self.estimate_cost(degraded)
            keep = max(1, int(len(adjusted) * ratio))
            degraded = ShotPlan(run_id=shot_plan.run_id, shots=adjusted[:keep])

        return degraded
