"""SKILL 11: RagKBManagerService — 业务逻辑实现。
参考规格: SKILL_11_RAG_KB_MANAGER.md
状态: SERVICE_READY
"""
from __future__ import annotations

import uuid

from loguru import logger
from sqlalchemy.orm import Session

from ainern2d_shared.schemas.skills.skill_11 import KBEntry, Skill11Input, Skill11Output
from ainern2d_shared.services.base_skill import BaseSkillService, SkillContext


class RagKBManagerService(BaseSkillService[Skill11Input, Skill11Output]):
    """SKILL 11 — RAG Knowledge Base Manager (CRUD operations).

    State machine:
      INIT → VALIDATING → PROCESSING → INDEXING → READY_TO_RELEASE | FAILED
    """

    skill_id = "skill_11"
    skill_name = "RagKBManagerService"

    def __init__(self, db: Session) -> None:
        super().__init__(db)

    def execute(self, input_dto: Skill11Input, ctx: SkillContext) -> Skill11Output:
        self._record_state(ctx, "INIT", "VALIDATING")

        action = input_dto.action or "create"
        if action not in ("create", "update", "publish", "rollback"):
            self._record_state(ctx, "VALIDATING", "FAILED")
            raise ValueError(f"REQ-VALIDATION-001: unsupported KB action '{action}'")

        kb_id = input_dto.kb_id or str(uuid.uuid4())
        version_id = input_dto.version_label or f"v{uuid.uuid4().hex[:8]}"

        self._record_state(ctx, "VALIDATING", "PROCESSING")

        entries: list[KBEntry] = input_dto.entries or []
        entry_count = len(entries)

        # Tag normalization
        for entry in entries:
            if not entry.tags:
                entry.tags = [entry.entry_type, "auto_tagged"]

        self._record_state(ctx, "PROCESSING", "INDEXING")
        self._record_state(ctx, "INDEXING", "READY_TO_RELEASE")

        status = "ready_to_release" if action in ("create", "update", "publish") else "rolled_back"

        logger.info(
            f"[{self.skill_id}] completed | run={ctx.run_id} kb={kb_id} "
            f"action={action} entries={entry_count}"
        )

        return Skill11Output(
            kb_id=kb_id,
            version_id=version_id,
            entry_count=entry_count,
            status=status,
        )
