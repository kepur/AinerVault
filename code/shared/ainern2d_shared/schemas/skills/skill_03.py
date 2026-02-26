"""SKILL 03: Story → Scene → Shot Planner — Input/Output DTOs."""
from __future__ import annotations
from ainern2d_shared.schemas.base import BaseSchema


class Scene(BaseSchema):
    scene_id: str
    chapter_id: str
    description: str = ""
    start_segment: int = 0
    end_segment: int = 0


class Shot(BaseSchema):
    shot_id: str
    scene_id: str
    description: str = ""
    duration_hint_ms: int = 3000
    entity_refs: list[str] = []
    camera_hint: str = ""  # close-up | medium | wide | panoramic


class Skill03Input(BaseSchema):
    language_route: dict
    segments: list[dict] = []
    creative_constraints: dict = {}


class Skill03Output(BaseSchema):
    scenes: list[Scene] = []
    shots: list[Shot] = []
    total_duration_hint_ms: int = 0
    entity_hints: list[str] = []
    status: str = "ready_for_parallel_execution"
