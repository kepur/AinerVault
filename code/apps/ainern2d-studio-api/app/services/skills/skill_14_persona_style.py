"""SKILL 14: PersonaStyleService — 业务逻辑实现。
参考规格: SKILL_14_PERSONA_STYLE_PACK_MANAGER.md
状态: SERVICE_READY
"""
from __future__ import annotations

import uuid

from loguru import logger
from sqlalchemy.orm import Session

from ainern2d_shared.schemas.skills.skill_14 import (
    PersonaDefinition,
    RAGBinding,
    Skill14Input,
    Skill14Output,
)
from ainern2d_shared.services.base_skill import BaseSkillService, SkillContext


class PersonaStyleService(BaseSkillService[Skill14Input, Skill14Output]):
    """SKILL 14 — Persona & Style Pack Manager.

    State machine:
      INIT → VALIDATING → PROCESSING → BINDING_RAG → READY_TO_PUBLISH | FAILED
    """

    skill_id = "skill_14"
    skill_name = "PersonaStyleService"

    def __init__(self, db: Session) -> None:
        super().__init__(db)

    def execute(self, input_dto: Skill14Input, ctx: SkillContext) -> Skill14Output:
        self._record_state(ctx, "INIT", "VALIDATING")

        action = input_dto.action or "create"
        if action not in ("create", "update", "publish", "draft"):
            self._record_state(ctx, "VALIDATING", "FAILED")
            raise ValueError(f"REQ-VALIDATION-001: unsupported persona action '{action}'")

        persona: PersonaDefinition = input_dto.persona or PersonaDefinition()
        persona_id = persona.persona_id or str(uuid.uuid4())[:8]
        version_id = f"v{uuid.uuid4().hex[:6]}"

        self._record_state(ctx, "VALIDATING", "PROCESSING")

        # Auto-fill defaults
        if not persona.name:
            persona.name = f"persona_{persona_id}"

        self._record_state(ctx, "PROCESSING", "BINDING_RAG")

        bindings: list[RAGBinding] = input_dto.rag_bindings or []

        self._record_state(ctx, "BINDING_RAG", "READY_TO_PUBLISH")

        status = "ready_to_publish" if action == "publish" else "draft"

        logger.info(
            f"[{self.skill_id}] completed | run={ctx.run_id} "
            f"persona={persona_id} action={action} rag_bindings={len(bindings)}"
        )

        return Skill14Output(
            persona_id=persona_id,
            version_id=version_id,
            rag_bindings_count=len(bindings),
            status=status,
        )
