"""SKILL 18: FailureRecoveryService — 业务逻辑实现。
参考规格: SKILL_18_FAILURE_RECOVERY_DEGRADATION_POLICY.md
状态: SERVICE_READY
"""
from __future__ import annotations

from loguru import logger
from sqlalchemy.orm import Session

from ainern2d_shared.schemas.skills.skill_18 import (
    RecoveryAction,
    Skill18Input,
    Skill18Output,
)
from ainern2d_shared.services.base_skill import BaseSkillService, SkillContext

_MAX_RETRIES = 3
_ABORT_THRESHOLD = 5

# ── Recovery decision table ───────────────────────────────────────────────────
# (error_code_prefix, retry_count_threshold, action_type, degrade_level)
_RECOVERY_RULES: list[tuple[str, int, str, bool]] = [
    ("WORKER-GPU", 0, "retry", False),
    ("WORKER-GPU", 2, "degrade", True),
    ("WORKER-GPU", _MAX_RETRIES, "skip", True),
    ("SKILL-", 0, "retry", False),
    ("SKILL-", _MAX_RETRIES, "abort", False),
    ("INFRA-", 0, "degrade", True),
    ("INFRA-", _ABORT_THRESHOLD, "abort", False),
]


class FailureRecoveryService(BaseSkillService[Skill18Input, Skill18Output]):
    """SKILL 18 — Failure Recovery & Degradation Policy.

    State machine:
      INIT → ANALYZING → DECIDING → COMPLETED | FAILED
    """

    skill_id = "skill_18"
    skill_name = "FailureRecoveryService"

    def __init__(self, db: Session) -> None:
        super().__init__(db)

    def execute(self, input_dto: Skill18Input, ctx: SkillContext) -> Skill18Output:
        self._record_state(ctx, "INIT", "ANALYZING")

        error_code = input_dto.error_code or "UNKNOWN"
        failed_skill = input_dto.failed_skill or ""
        retry_count = input_dto.retry_count or 0

        self._record_state(ctx, "ANALYZING", "DECIDING")

        # Match rule
        action_type = "retry"
        degradation = False
        circuit_breaker = False

        for prefix, threshold, action, degrade in _RECOVERY_RULES:
            if error_code.startswith(prefix) and retry_count >= threshold:
                action_type = action
                degradation = degrade

        if retry_count >= _ABORT_THRESHOLD:
            action_type = "abort"
            circuit_breaker = True

        decision = RecoveryAction(
            action_type=action_type,
            target_skill=failed_skill,
            params={"retry_count": retry_count},
            reason=f"error_code={error_code} retry_count={retry_count}",
        )

        self._record_state(ctx, "DECIDING", "COMPLETED")

        logger.info(
            f"[{self.skill_id}] completed | run={ctx.run_id} "
            f"action={action_type} degradation={degradation}"
        )

        return Skill18Output(
            decision=decision,
            degradation_applied=degradation,
            circuit_breaker_triggered=circuit_breaker,
            status="completed",
        )
