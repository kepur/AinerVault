"""SKILL 09: VisualRenderPlanService — 业务逻辑实现。
参考规格: SKILL_09_VISUAL_RENDER_PLANNER.md
状态: SERVICE_READY
"""
from __future__ import annotations

from loguru import logger
from sqlalchemy.orm import Session

from ainern2d_shared.schemas.skills.skill_09 import (
    Skill09Input,
    Skill09Output,
    ShotRenderConfig,
)
from ainern2d_shared.services.base_skill import BaseSkillService, SkillContext

# ── Constants ─────────────────────────────────────────────────────────────────
_RENDER_PROFILES: dict[str, dict] = {
    "LOW_LOAD": {
        "fps": 24, "resolution": "1280x720",
        "frame_budget": 24, "gpu_tier": "A100",
        "fallback_chain": ["i2v", "static"],
    },
    "MEDIUM_LOAD": {
        "fps": 24, "resolution": "1280x720",
        "frame_budget": 16, "gpu_tier": "A100",
        "fallback_chain": ["i2v", "static"],
    },
    "HIGH_LOAD": {
        "fps": 16, "resolution": "960x540",
        "frame_budget": 8, "gpu_tier": "T4",
        "fallback_chain": ["static", "i2v"],
    },
}

_ACTION_MOTION: dict[str, str] = {
    "battle": "high", "fight": "high", "chase": "high", "action": "high",
    "walk": "medium", "run": "medium", "move": "medium",
    "talk": "low", "stand": "low", "sit": "low", "dialogue": "low",
}


class VisualRenderPlanService(BaseSkillService[Skill09Input, Skill09Output]):
    """SKILL 09 — Visual Render Planner.

    State machine:
      INIT → ANALYZING_AUDIO → PLANNING_SHOTS → APPLYING_BUDGET → READY_FOR_RENDER | FAILED
    """

    skill_id = "skill_09"
    skill_name = "VisualRenderPlanService"

    def __init__(self, db: Session) -> None:
        super().__init__(db)

    def execute(self, input_dto: Skill09Input, ctx: SkillContext) -> Skill09Output:
        self._record_state(ctx, "INIT", "ANALYZING_AUDIO")

        profile_key = (input_dto.compute_budget or {}).get("global_render_profile", "MEDIUM_LOAD")
        if profile_key not in _RENDER_PROFILES:
            profile_key = "MEDIUM_LOAD"
        profile = _RENDER_PROFILES[profile_key]

        # Build audio event index: shot_id → audio density score
        audio_events = (input_dto.audio_timeline or {}).get("events", [])
        audio_density: dict[str, float] = {}
        for ev in audio_events:
            sid = ev.get("shot_id", "")
            audio_density[sid] = audio_density.get(sid, 0.0) + 1.0

        self._record_state(ctx, "ANALYZING_AUDIO", "PLANNING_SHOTS")

        render_plans: list[ShotRenderConfig] = []
        total_frames = 0

        for i, shot in enumerate(input_dto.shots):
            shot_id = shot.get("shot_id", f"shot_{i:03d}")
            action_cues = shot.get("action_cues", [])
            scene_type = shot.get("scene_type", "dialogue")
            duration = float(shot.get("duration_seconds", 3.0))

            # Motion complexity
            motion_level = "low"
            for cue in action_cues:
                cue_lower = str(cue).lower()
                for kw, level in _ACTION_MOTION.items():
                    if kw in cue_lower:
                        if level == "high":
                            motion_level = "high"
                            break
                        elif level == "medium" and motion_level == "low":
                            motion_level = "medium"

            # Audio density bump
            density = audio_density.get(shot_id, 0.0)
            if density > 5 and motion_level == "low":
                motion_level = "medium"

            # Frame budget per shot
            if motion_level == "high":
                frame_budget = profile["frame_budget"]
                render_mode = "i2v"
                fps = profile["fps"]
            elif motion_level == "medium":
                frame_budget = max(8, profile["frame_budget"] // 2)
                render_mode = "i2v"
                fps = profile["fps"]
            else:
                frame_budget = 8
                render_mode = "static"
                fps = 1

            total_frames += int(duration * fps)

            render_plans.append(ShotRenderConfig(
                shot_id=shot_id,
                render_mode=render_mode,
                fps=fps,
                resolution=profile["resolution"],
                priority=i,
                gpu_tier=profile["gpu_tier"],
                fallback_chain=profile["fallback_chain"],
            ))

        self._record_state(ctx, "PLANNING_SHOTS", "APPLYING_BUDGET")

        # GPU hours estimate: rough formula
        fps_avg = profile["fps"]
        gpu_hours = round(total_frames / fps_avg / 3600.0 * 0.5, 4)

        self._record_state(ctx, "APPLYING_BUDGET", "READY_FOR_RENDER")

        logger.info(
            f"[{self.skill_id}] completed | run={ctx.run_id} shots={len(render_plans)} "
            f"gpu_hours={gpu_hours}"
        )

        return Skill09Output(
            render_plans=render_plans,
            total_gpu_hours_estimate=gpu_hours,
            status="ready_for_render_execution",
        )
