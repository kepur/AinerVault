"""SKILL 08: Asset Matcher — Input/Output DTOs."""
from __future__ import annotations
from ainern2d_shared.schemas.base import BaseSchema


class AssetCandidate(BaseSchema):
    asset_id: str
    entity_id: str
    source: str = ""  # rag | lora | generated | user_upload
    score: float = 0.0
    confidence: float = 0.0
    preview_uri: str = ""


class Skill08Input(BaseSchema):
    canonical_entities: list[dict] = []
    kb_suggestions: list[dict] = []
    search_config: dict = {}


class Skill08Output(BaseSchema):
    asset_manifest: list[AssetCandidate] = []
    unmatched_entities: list[str] = []
    status: str = "ready_for_prompt_planner"
