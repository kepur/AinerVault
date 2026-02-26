"""
Base SKILL Service — 所有 SKILL 实现的统一基类。
AI Agent 实现具体 SKILL 时必须继承此类。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from loguru import logger
from sqlalchemy.orm import Session

from ainern2d_shared.utils.time import utcnow

InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


@dataclass
class SkillContext:
    """每次 SKILL 执行的运行上下文 — 由 Orchestrator 注入。"""

    tenant_id: str
    project_id: str
    run_id: str
    trace_id: str
    correlation_id: str
    idempotency_key: str
    schema_version: str = "1.0"
    extra: dict[str, Any] = field(default_factory=dict)


class BaseSkillService(ABC, Generic[InputT, OutputT]):
    """
    SKILL Service 统一基类。

    每个 SKILL 必须实现:
      - skill_id: str            — "skill_01", "skill_02", ...
      - skill_name: str          — 人类可读名称
      - execute(input, ctx)      — 核心执行逻辑

    基类提供:
      - 幂等性检查（相同 idempotency_key 不重复执行）
      - 状态机转换记录
      - 统一日志格式
      - 错误包装
    """

    skill_id: str = ""
    skill_name: str = ""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ── public entry ──────────────────────────────────────────────

    def run(self, input_dto: InputT, ctx: SkillContext) -> OutputT:
        """统一入口 — 带幂等/日志/异常包装。"""
        logger.info(
            f"[{self.skill_id}] START | run={ctx.run_id} trace={ctx.trace_id} "
            f"idem={ctx.idempotency_key}"
        )

        # 幂等性检查
        existing = self._check_idempotency(ctx)
        if existing is not None:
            logger.info(f"[{self.skill_id}] IDEMPOTENT HIT — returning cached result")
            return existing

        self._record_state(ctx, "INIT", "IN_PROGRESS")

        try:
            result = self.execute(input_dto, ctx)
            self._record_state(ctx, "IN_PROGRESS", "COMPLETED")
            logger.info(f"[{self.skill_id}] COMPLETED | run={ctx.run_id}")
            return result
        except Exception as exc:
            self._record_state(ctx, "IN_PROGRESS", "FAILED", error=str(exc))
            logger.error(f"[{self.skill_id}] FAILED | run={ctx.run_id} error={exc}")
            raise

    # ── abstract — 子类必须实现 ────────────────────────────────────

    @abstractmethod
    def execute(self, input_dto: InputT, ctx: SkillContext) -> OutputT:
        """核心业务逻辑 — 子类在此实现 SKILL 的全部处理。"""
        ...

    # ── 内部工具 ──────────────────────────────────────────────────

    def _check_idempotency(self, ctx: SkillContext) -> OutputT | None:
        """检查是否已有相同 idempotency_key 的成功执行。默认返回 None（不缓存）。"""
        # 子类可覆盖此方法以提供 DB 级幂等
        return None

    def _record_state(
        self,
        ctx: SkillContext,
        from_state: str,
        to_state: str,
        error: str | None = None,
    ) -> None:
        """记录状态转换到 workflow_events 表。"""
        try:
            from ainern2d_shared.ainer_db_models.pipeline_models import WorkflowEvent

            evt = WorkflowEvent(
                tenant_id=ctx.tenant_id,
                project_id=ctx.project_id,
                run_id=ctx.run_id,
                trace_id=ctx.trace_id,
                correlation_id=ctx.correlation_id,
                idempotency_key=f"{ctx.idempotency_key}:{self.skill_id}:{to_state}",
                event_type=f"{self.skill_id}.state.{to_state.lower()}",
                producer=self.skill_id,
                payload_json={
                    "from_state": from_state,
                    "to_state": to_state,
                    "timestamp": utcnow().isoformat(),
                    "error": error,
                },
            )
            self.db.add(evt)
            self.db.commit()
        except Exception as e:
            logger.warning(f"[{self.skill_id}] Failed to record state: {e}")
