"""SKILL 14: Persona & Style Pack Manager — Input/Output DTOs."""
from __future__ import annotations
from ainern2d_shared.schemas.base import BaseSchema


class PersonaDefinition(BaseSchema):
    persona_id: str = ""
    name: str = ""
    voice_style: dict = {}
    visual_style: dict = {}
    narrative_tone: str = ""
    tags: list[str] = []


class RAGBinding(BaseSchema):
    kb_id: str
    scope: str = "full"  # full | subset
    filter_tags: list[str] = []


class Skill14Input(BaseSchema):
    action: str = "create"  # create | update | publish | draft
    persona: PersonaDefinition = PersonaDefinition()
    rag_bindings: list[RAGBinding] = []


class Skill14Output(BaseSchema):
    persona_id: str = ""
    version_id: str = ""
    rag_bindings_count: int = 0
    status: str = "ready_to_publish"
