"""SKILL 02: Language Context Router — Input/Output DTOs."""
from __future__ import annotations
from ainern2d_shared.schemas.base import BaseSchema


class CultureCandidate(BaseSchema):
    culture_code: str  # e.g. "zh-CN-ancient", "ja-JP-modern"
    confidence: float = 0.0
    description: str = ""


class KBSuggestion(BaseSchema):
    kb_id: str
    kb_name: str
    relevance_score: float = 0.0


class Skill02Input(BaseSchema):
    document_meta: dict
    language_detection: dict
    segments: list[dict] = []


class Skill02Output(BaseSchema):
    language_code: str
    culture_candidates: list[CultureCandidate] = []
    kb_suggestions: list[KBSuggestion] = []
    routing_decision: str = ""
    status: str = "ready_for_planning"
