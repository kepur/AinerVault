"""SKILL 17: ExperimentService — 业务逻辑实现。
参考规格: SKILL_17_*.md
状态: PARTIAL — 需要实现 execute() 核心逻辑。
"""
from __future__ import annotations

from loguru import logger
from sqlalchemy.orm import Session

from ainern2d_shared.schemas.skills.skill_17 import Skill17Input, Skill17Output
from ainern2d_shared.services.base_skill import BaseSkillService, SkillContext


class ExperimentService(BaseSkillService[Skill17Input, Skill17Output]):
    skill_id = "skill_17"
    skill_name = "ExperimentService"

    def __init__(self, db: Session) -> None:
        super().__init__(db)

    def execute(self, input_dto: Skill17Input, ctx: SkillContext) -> Skill17Output:
        """
        核心执行逻辑 — TODO: 根据 SKILL_17_*.md 规格实现。

        实现要点:
        1. 读取 SKILL_17_*.md 的 Branching Logic 和 State Machine
        2. 按状态机逐步推进
        3. 调用 modules/ 下的底层模块
        4. 输出满足 Definition of Done 的 DTO
        """
        logger.info(f"[{self.skill_id}] Executing for run={ctx.run_id}")

        # TODO: 实现核心逻辑 — 当前返回空壳输出
        return Skill17Output()
