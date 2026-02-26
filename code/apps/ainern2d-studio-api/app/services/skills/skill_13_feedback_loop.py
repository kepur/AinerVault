"""SKILL 13: FeedbackLoopService — 业务逻辑实现。
参考规格: SKILL_13_FEEDBACK_EVOLUTION_LOOP.md
状态: SERVICE_READY
"""
from __future__ import annotations

import uuid

from loguru import logger
from sqlalchemy.orm import Session

from ainern2d_shared.schemas.skills.skill_13 import (
    FeedbackEntry,
    ImprovementProposal,
    Skill13Input,
    Skill13Output,
)
from ainern2d_shared.services.base_skill import BaseSkillService, SkillContext

# ── Dimension → target skill mapping ─────────────────────────────────────────
_DIM_TO_SKILL: dict[str, str] = {
    "visual": "skill_09",
    "audio": "skill_05",
    "narrative": "skill_03",
    "style": "skill_10",
}


class FeedbackLoopService(BaseSkillService[Skill13Input, Skill13Output]):
    """SKILL 13 — Feedback Evolution Loop.

    State machine:
      INIT → AGGREGATING → ANALYZING → PROPOSING → COMPLETED | FAILED
    """

    skill_id = "skill_13"
    skill_name = "FeedbackLoopService"

    def __init__(self, db: Session) -> None:
        super().__init__(db)

    def execute(self, input_dto: Skill13Input, ctx: SkillContext) -> Skill13Output:
        self._record_state(ctx, "INIT", "AGGREGATING")

        entries: list[FeedbackEntry] = input_dto.feedback_entries or []

        self._record_state(ctx, "AGGREGATING", "ANALYZING")

        # Aggregate by dimension
        dim_scores: dict[str, list[int]] = {}
        for entry in entries:
            dim = entry.dimension or "visual"
            dim_scores.setdefault(dim, []).append(entry.rating or 3)

        dim_avg: dict[str, float] = {
            dim: sum(scores) / len(scores)
            for dim, scores in dim_scores.items()
        }

        self._record_state(ctx, "ANALYZING", "PROPOSING")

        proposals: list[ImprovementProposal] = []
        kb_evolution = False

        for dim, avg in dim_avg.items():
            if avg < 3.0:
                target = _DIM_TO_SKILL.get(dim, "skill_01")
                action = "update_kb" if dim in ("narrative", "style") else "adjust_policy"
                proposals.append(
                    ImprovementProposal(
                        proposal_id=str(uuid.uuid4())[:8],
                        target_skill=target,
                        action=action,
                        description=f"Low {dim} score ({avg:.1f}/5) — trigger {action} for {target}",
                        priority=int((3.0 - avg) * 10),
                    )
                )
                if action == "update_kb":
                    kb_evolution = True

        self._record_state(ctx, "PROPOSING", "COMPLETED")

        logger.info(
            f"[{self.skill_id}] completed | run={ctx.run_id} "
            f"entries={len(entries)} proposals={len(proposals)}"
        )

        return Skill13Output(
            proposals=proposals,
            kb_evolution_triggered=kb_evolution,
            status="completed",
        )
