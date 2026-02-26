"""SKILL 10: PromptPlannerService — 业务逻辑实现。
参考规格: SKILL_10_*.md
状态: PARTIAL — 需要实现 execute() 核心逻辑。
"""
from __future__ import annotations

from loguru import logger
from sqlalchemy.orm import Session

from ainern2d_shared.schemas.skills.skill_10 import Skill10Input, Skill10Output
from ainern2d_shared.services.base_skill import BaseSkillService, SkillContext


class PromptPlannerService(BaseSkillService[Skill10Input, Skill10Output]):
    skill_id = "skill_10"
    skill_name = "PromptPlannerService"

    def __init__(self, db: Session) -> None:
        super().__init__(db)

    def execute(self, input_dto: Skill10Input, ctx: SkillContext) -> Skill10Output:
        """
        核心执行逻辑 — TODO: 根据 SKILL_10_*.md 规格实现。

        实现要点:
        1. 读取 SKILL_10_*.md 的 Branching Logic 和 State Machine
        2. 按状态机逐步推进
        3. 调用 modules/ 下的底层模块
        4. 输出满足 Definition of Done 的 DTO
        """
        logger.info(f"[{self.skill_id}] Executing for run={ctx.run_id}")

        # TODO: 实现核心逻辑 — 当前返回空壳输出
        return Skill10Output()
