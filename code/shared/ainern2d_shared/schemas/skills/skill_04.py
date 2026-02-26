"""SKILL 04: Entity Extraction & Structuring — Input/Output DTOs."""
from __future__ import annotations
from ainern2d_shared.schemas.base import BaseSchema


class ExtractedEntity(BaseSchema):
    entity_id: str
    canonical_name: str
    entity_type: str  # character | location | prop | clothing | creature
    aliases: list[str] = []
    first_appearance_segment: int = 0
    description: str = ""
    attributes: dict = {}


class EntityRelationship(BaseSchema):
    source_entity_id: str
    target_entity_id: str
    relation_type: str  # knows | owns | located_in | wears


class Skill04Input(BaseSchema):
    segments: list[dict] = []
    language_code: str = "zh-CN"
    existing_entities: list[dict] = []


class Skill04Output(BaseSchema):
    entities: list[ExtractedEntity] = []
    relationships: list[EntityRelationship] = []
    dedup_count: int = 0
    status: str = "ready_for_canonicalization"
