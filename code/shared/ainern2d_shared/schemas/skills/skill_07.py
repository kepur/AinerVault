"""SKILL 07: Entity Canonicalization & Cultural Binding — Input/Output DTOs."""
from __future__ import annotations
from ainern2d_shared.schemas.base import BaseSchema


class CultureVariant(BaseSchema):
    culture_code: str
    variant_name: str
    visual_tags: list[str] = []
    style_hints: dict = {}


class CanonicalEntity(BaseSchema):
    entity_id: str
    canonical_form: str
    entity_type: str
    culture_variants: list[CultureVariant] = []
    visual_tags: list[str] = []
    consistency_hash: str = ""


class Skill07Input(BaseSchema):
    entities: list[dict] = []
    shots: list[dict] = []
    culture_candidates: list[dict] = []


class Skill07Output(BaseSchema):
    canonical_entities: list[CanonicalEntity] = []
    conflict_warnings: list[str] = []
    status: str = "ready_for_asset_match"
