from __future__ import annotations

from sqlalchemy.orm import Session

from ainern2d_shared.schemas.timeline import ShotPlan


class ProductionScheduler:
    def __init__(self, db: Session) -> None:
        self.db = db

    def schedule(self, run_id: str, shot_plan: ShotPlan) -> list[dict]:
        """Order shots for parallel/sequential execution.

        Groups shots by scene; shots within a scene run in parallel,
        scenes execute sequentially.
        """
        if not shot_plan.shots:
            return []

        scene_groups: dict[str, list[str]] = {}
        for item in shot_plan.shots:
            scene_groups.setdefault(item.scene_id, []).append(item.shot_id)

        steps: list[dict] = []
        step_no = 1
        for scene_id, shot_ids in scene_groups.items():
            steps.append(
                {
                    "step": step_no,
                    "run_id": run_id,
                    "scene_id": scene_id,
                    "shot_ids": shot_ids,
                    "parallel": True,
                }
            )
            step_no += 1

        return steps

    def estimate_time(self, shot_plan: ShotPlan) -> int:
        """Estimated total production time in ms.

        Assumes parallel rendering per scene, sequential across scenes.
        Per-shot render time heuristic: ~10x real duration.
        """
        if not shot_plan.shots:
            return 0

        scene_max: dict[str, int] = {}
        for item in shot_plan.shots:
            render_ms = item.duration_ms * 10
            if item.scene_id not in scene_max or render_ms > scene_max[item.scene_id]:
                scene_max[item.scene_id] = render_ms

        return sum(scene_max.values())
