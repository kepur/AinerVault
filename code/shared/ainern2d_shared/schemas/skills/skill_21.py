"""SKILL 21: Entity Registry & Continuity Manager — Input/Output DTOs.

Spec: SKILL_21_ENTITY_REGISTRY_CONTINUITY_MANAGER.md
"""
from __future__ import annotations

from typing import Any

from ainern2d_shared.schemas.base import BaseSchema


class Skill21FeatureFlags(BaseSchema):
    enable_entity_linking: bool = True
    enable_instance_tracking: bool = True
    enable_continuity_rules: bool = True
    enable_world_model_link: bool = True


class ExistingRegistryEntity(BaseSchema):
    entity_id: str
    entity_type: str = "character"
    canonical_name: str = ""
    aliases: list[str] = []
    world_model_id: str = ""
    continuity_profile: dict[str, Any] = {}


class ShotPlanRef(BaseSchema):
    shot_id: str
    scene_id: str = ""
    entity_refs: list[str] = []
    tags: list[str] = []


class ExtractedEntity(BaseSchema):
    source_entity_uid: str
    entity_type: str = "character"
    label: str = ""
    aliases: list[str] = []
    world_model_id: str = ""
    traits: dict[str, Any] = {}
    shot_ids: list[str] = []
    scene_ids: list[str] = []


class RegistryActions(BaseSchema):
    linked_existing: int = 0
    created_new: int = 0
    review_needed: int = 0


class ResolvedEntity(BaseSchema):
    source_entity_uid: str
    linked_to_existing: bool = False
    matched_entity_id: str = ""
    confidence: float = 0.0
    entity_type: str = "character"
    world_model_id: str = ""


class CreatedEntity(BaseSchema):
    source_entity_uid: str
    new_entity_id: str
    entity_type: str = "character"
    canonical_name: str = ""


class EntityInstanceLinkOut(BaseSchema):
    instance_id: str
    entity_id: str
    shot_id: str = ""
    scene_id: str = ""
    source_entity_uid: str = ""


class ContinuityProfileOut(BaseSchema):
    entity_id: str
    continuity_status: str = "active"
    anchors: dict[str, Any] = {}
    rules: dict[str, Any] = {}
    allowed_variations: list[str] = []


class LinkConflict(BaseSchema):
    source_entity_uid: str
    reason: str = ""
    candidates: list[str] = []
    confidence: float = 0.0


class ContinuityExports(BaseSchema):
    asset_matcher_anchors: list[dict[str, Any]] = []
    prompt_consistency_anchors: list[dict[str, Any]] = []
    critic_rules_baseline: list[dict[str, Any]] = []


class Skill21Input(BaseSchema):
    """SKILL 21 input DTO."""

    entity_extraction_result: dict[str, Any] = {}
    extracted_entities: list[ExtractedEntity] = []
    shot_plan: list[ShotPlanRef] = []
    normalized_story: dict[str, Any] = {}
    language_context_routing: dict[str, Any] = {}
    world_model_context: dict[str, Any] = {}
    existing_entity_registry: list[ExistingRegistryEntity] = []
    user_overrides: dict[str, Any] = {}
    feature_flags: Skill21FeatureFlags = Skill21FeatureFlags()


class Skill21Output(BaseSchema):
    """SKILL 21 output DTO."""

    version: str = "1.0"
    status: str = "continuity_ready"
    registry_actions: RegistryActions = RegistryActions()
    resolved_entities: list[ResolvedEntity] = []
    created_entities: list[CreatedEntity] = []
    entity_instance_links: list[EntityInstanceLinkOut] = []
    continuity_profiles: list[ContinuityProfileOut] = []
    continuity_exports: ContinuityExports = ContinuityExports()
    link_conflicts: list[LinkConflict] = []
    warnings: list[str] = []
    review_required_items: list[str] = []
