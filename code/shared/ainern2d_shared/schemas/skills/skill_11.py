"""SKILL 11: RAG KB Manager — Input/Output DTOs."""
from __future__ import annotations
from ainern2d_shared.schemas.base import BaseSchema


class KBEntry(BaseSchema):
    entry_id: str
    content: str
    entry_type: str = "text"  # text | image_ref | style_ref
    tags: list[str] = []
    metadata: dict = {}


class Skill11Input(BaseSchema):
    kb_id: str = ""
    action: str = "create"  # create | update | publish | rollback
    entries: list[KBEntry] = []
    version_label: str = ""


class Skill11Output(BaseSchema):
    kb_id: str
    version_id: str
    entry_count: int = 0
    status: str = "ready_to_release"
