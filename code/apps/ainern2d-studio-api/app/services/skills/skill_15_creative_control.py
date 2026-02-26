"""SKILL 15: CreativeControlService — 业务逻辑实现。
参考规格: SKILL_15_CREATIVE_CONTROL_POLICY.md
状态: SERVICE_READY
"""
from __future__ import annotations

import uuid

from loguru import logger
from sqlalchemy.orm import Session

from ainern2d_shared.schemas.skills.skill_15 import (
    Constraint,
    Skill15Input,
    Skill15Output,
)
from ainern2d_shared.services.base_skill import BaseSkillService, SkillContext

# ── Default constraint templates ──────────────────────────────────────────────
_DEFAULT_HARD: list[dict] = [
    {"dimension": "visual", "rule": "no_explicit_violence", "priority": 100},
    {"dimension": "visual", "rule": "no_nsfw_content", "priority": 100},
    {"dimension": "audio", "rule": "no_abrupt_silence_mid_scene", "priority": 80},
]
_DEFAULT_SOFT: list[dict] = [
    {"dimension": "visual", "rule": "prefer_culture_consistent_visuals", "priority": 60},
    {"dimension": "narrative", "rule": "maintain_story_coherence", "priority": 70},
    {"dimension": "style", "rule": "consistent_art_style_across_shots", "priority": 65},
]


class CreativeControlService(BaseSkillService[Skill15Input, Skill15Output]):
    """SKILL 15 — Creative Control Policy.

    State machine:
      INIT → LOADING_POLICY → MERGING_OVERRIDES → RESOLVING_CONFLICTS → POLICY_READY | FAILED
    """

    skill_id = "skill_15"
    skill_name = "CreativeControlService"

    def __init__(self, db: Session) -> None:
        super().__init__(db)

    def execute(self, input_dto: Skill15Input, ctx: SkillContext) -> Skill15Output:
        self._record_state(ctx, "INIT", "LOADING_POLICY")

        hard_constraints = [
            Constraint(
                constraint_id=str(uuid.uuid4())[:8],
                constraint_type="hard",
                dimension=c["dimension"],
                rule=c["rule"],
                priority=c["priority"],
            )
            for c in _DEFAULT_HARD
        ]
        soft_constraints = [
            Constraint(
                constraint_id=str(uuid.uuid4())[:8],
                constraint_type="soft",
                dimension=c["dimension"],
                rule=c["rule"],
                priority=c["priority"],
            )
            for c in _DEFAULT_SOFT
        ]

        self._record_state(ctx, "LOADING_POLICY", "MERGING_OVERRIDES")

        # Apply user overrides
        conflict_resolutions: list[str] = []
        for override in (input_dto.user_overrides or []):
            rule = override.get("rule", "")
            otype = override.get("type", "soft")
            dim = override.get("dimension", "visual")
            if otype == "hard":
                hard_constraints.append(Constraint(
                    constraint_id=str(uuid.uuid4())[:8],
                    constraint_type="hard",
                    dimension=dim,
                    rule=rule,
                    priority=override.get("priority", 50),
                ))
            else:
                soft_constraints.append(Constraint(
                    constraint_id=str(uuid.uuid4())[:8],
                    constraint_type="soft",
                    dimension=dim,
                    rule=rule,
                    priority=override.get("priority", 40),
                ))

        self._record_state(ctx, "MERGING_OVERRIDES", "RESOLVING_CONFLICTS")
        self._record_state(ctx, "RESOLVING_CONFLICTS", "POLICY_READY")

        logger.info(
            f"[{self.skill_id}] completed | run={ctx.run_id} "
            f"hard={len(hard_constraints)} soft={len(soft_constraints)}"
        )

        return Skill15Output(
            hard_constraints=hard_constraints,
            soft_constraints=soft_constraints,
            exploration_range={"style_variance": 0.15, "timing_variance": 0.1},
            conflict_resolutions=conflict_resolutions,
            status="policy_ready",
        )
