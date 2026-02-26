"""SKILL 20: DslCompilerService — 业务逻辑实现。
参考规格: SKILL_20_SHOT_DSL_COMPILER_PROMPT_BACKEND.md
状态: PARTIAL — 需要实现 execute() 核心逻辑。
"""
from __future__ import annotations

from loguru import logger
from sqlalchemy.orm import Session

from ainern2d_shared.schemas.skills.skill_20 import Skill20Input, Skill20Output
from ainern2d_shared.services.base_skill import BaseSkillService, SkillContext


class DslCompilerService(BaseSkillService[Skill20Input, Skill20Output]):
    skill_id = "skill_20"
    skill_name = "DslCompilerService"

    def __init__(self, db: Session) -> None:
        super().__init__(db)

    def execute(self, input_dto: Skill20Input, ctx: SkillContext) -> Skill20Output:
        """
        核心执行逻辑 — TODO: 根据 SKILL_20_*.md 规格实现。

        实现要点:
        1. 验证 Shot DSL 输入
        2. 注入 Persona / CreativeControl / ComputeBudget 上下文
        3. 编译为后端特定 prompt（ComfyUI/SDXL/Flux）
        4. 生成 compiler_trace_report
        """
        logger.info(f"[{self.skill_id}] Executing for run={ctx.run_id}")
        return Skill20Output(compiled_shots=[], compiler_traces=[])
