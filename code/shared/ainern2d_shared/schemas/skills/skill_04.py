"""SKILL 04: Entity Extraction & Structuring — Input/Output DTOs."""
from __future__ import annotations

from ainern2d_shared.schemas.base import BaseSchema


# ── Sub-objects ───────────────────────────────────────────────────────────────

class EntitySummary(BaseSchema):
    total_entities: int = 0
    characters: int = 0
    scene_places: int = 0
    props: int = 0
    costumes: int = 0
    vehicles: int = 0
    creatures: int = 0
    symbol_signages: int = 0
    audio_event_candidates: int = 0


class RawEntity(BaseSchema):
    entity_uid: str
    surface_form: str
    entity_type: str  # character | scene_place | prop | costume | vehicle | creature | symbol_signage | audio_event_candidate
    attributes: dict = {}
    source_refs: list[dict] = []  # [{"segment_id": str}]
    confidence: float = 0.8


class AliasGroup(BaseSchema):
    alias_group_id: str
    canonical_hint: str
    members: list[str] = []
    cross_language_aliases: list[str] = []


class EntitySceneShotLink(BaseSchema):
    entity_uid: str
    scene_ids: list[str] = []
    shot_ids: list[str] = []
    first_appearance_shot_id: str = ""
    criticality: str = "normal"  # critical | important | normal | background


class AudioEventCandidate(BaseSchema):
    event_type: str  # metal_hit | wind_rain | crowd | explosion | footsteps | nature
    source_shot_id: str = ""
    confidence: float = 0.5


class ContinuityExtractedEntity(BaseSchema):
    source_entity_uid: str
    entity_type: str = "character"
    label: str = ""
    aliases: list[str] = []
    world_model_id: str = ""
    traits: dict = {}
    shot_ids: list[str] = []
    scene_ids: list[str] = []


class ContinuityShotPlanRef(BaseSchema):
    shot_id: str
    scene_id: str = ""
    entity_refs: list[str] = []


class ContinuityHandoff(BaseSchema):
    extracted_entities: list[ContinuityExtractedEntity] = []
    shot_plan_refs: list[ContinuityShotPlanRef] = []


# ── Input / Output ────────────────────────────────────────────────────────────

class Skill04Input(BaseSchema):
    # From SKILL 01
    segments: list[dict] = []
    primary_language: str = "zh-CN"
    # From SKILL 03
    scene_plan: list[dict] = []
    shot_plan: list[dict] = []
    # From SKILL 02
    culture_hint: str = ""
    # Options
    existing_entities: list[dict] = []
    feature_flags: dict = {}
    confidence_threshold: float = 0.0


class Skill04Output(BaseSchema):
    entity_summary: EntitySummary = EntitySummary()
    entities: list[RawEntity] = []
    entity_aliases: list[AliasGroup] = []
    entity_scene_shot_links: list[EntitySceneShotLink] = []
    audio_event_candidates: list[AudioEventCandidate] = []
    continuity_handoff: ContinuityHandoff = ContinuityHandoff()
    warnings: list[str] = []
    review_required_items: list[str] = []
    status: str = "ready_for_canonicalization"
