"""Versioned contracts shared by asset and directing canvases."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "ainer.production/v0.1"


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Scope(Contract):
    kind: Literal["chapter", "scene", "shots", "custom"] = "custom"
    chapter_ids: list[str] = Field(default_factory=list, max_length=200)
    scene_ids: list[str] = Field(default_factory=list, max_length=200)
    shot_ids: list[str] = Field(default_factory=list, max_length=2000)


class ReturnTo(Contract):
    board_id: str = Field(min_length=1, max_length=32)
    node_id: str | None = Field(default=None, max_length=128)
    panel: Literal["assets", "directing", "finishing", "general"] | None = None


class ProductionContext(Contract):
    schema_version: Literal["ainer.production/v0.1"] = SCHEMA_VERSION
    board_id: str = Field(min_length=1, max_length=32)
    project_id: str | None = None
    novel_id: str | None = None
    chapter_id: str | None = None
    plan_id: str | None = None
    script_doc_id: str | None = None
    source_revision: str | None = None
    transform_id: str | None = None
    world_profile_id: str | None = None
    production_language: str | None = None
    purpose: Literal["assets", "directing", "finishing", "general"] = "general"
    scope: Scope = Field(default_factory=Scope)
    selection: dict = Field(default_factory=dict)
    return_to: ReturnTo | None = None


class Binding(Contract):
    entity_id: str | None = None
    world_profile_id: str | None = None
    epoch_id: str | None = None
    view_key: str | None = None
    instance_id: str | None = None


class ResourceRef(Contract):
    kind: Literal["entity", "variant", "canonical_pack", "canonical_view", "asset",
                  "event", "stage", "coverage", "audio", "run_output"]
    id: str = Field(min_length=1, max_length=160)
    # None means discovery only. The resolver always supplies the selected revision.
    revision: str | None = Field(default=None, min_length=1, max_length=80)
    binding: Binding = Field(default_factory=Binding)
    mode: Literal["reference", "snapshot", "derived"] = "reference"


class ResolveIn(Contract):
    context: ProductionContext
    refs: list[ResourceRef] = Field(max_length=200)


class ContextPatch(Contract):
    base_version: int = Field(ge=0)
    purpose: Literal["assets", "directing", "finishing", "general"]
    world_profile_id: str | None = None
    return_to: ReturnTo | None = None


class PackBinding(Contract):
    epoch_id: str = Field(min_length=1, max_length=32)
    base_revision: str = Field(min_length=1, max_length=80)
    # Individual assets, never URLs or a contact sheet in place of every panel.
    views: dict[str, str] = Field(min_length=1, max_length=16)
    sheet_asset_id: str | None = None


class ReturnSlot(Contract):
    board_id: str = Field(min_length=1, max_length=32)
    node_id: str = Field(min_length=1, max_length=128)
    slot: str = Field(min_length=1, max_length=64)


class PrepareIn(ResolveIn):
    return_slot: ReturnSlot | None = None
    submit: bool = False


class AddReferenceIn(Contract):
    base_version: int = Field(ge=0)
    ref: ResourceRef
    title: str | None = Field(None, max_length=200)
