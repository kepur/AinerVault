"""SKILL 03: Story → Scene → Shot Planner — Input/Output DTOs."""
from __future__ import annotations

from ainern2d_shared.schemas.base import BaseSchema


# ── Sub-objects ───────────────────────────────────────────────────────────────

class ScenePlan(BaseSchema):
    scene_id: str
    scene_goal: str = ""
    scene_type: str = "generic"  # atmosphere | dialogue | action | transition | atmosphere_dialogue
    scene_location_hint: str = "unknown"
    emotion_tone: str = "neutral"  # tense | calm | joyful | sad | dramatic | neutral
    source_range: dict = {}  # {"segment_start": int, "segment_end": int}


class ShotPlan(BaseSchema):
    shot_id: str
    scene_id: str
    shot_type: str = "medium"  # establishing | wide | medium | close-up | insert | action | transition
    shot_goal: str = ""
    criticality: str = "normal"  # critical | important | normal | background
    provisional_duration_ms: int = 3000
    characters_present: list[str] = []
    entity_hints: list[str] = []
    audio_hints: list[str] = []
    tts_backfill_required: bool = False


class ProvisionalTimeline(BaseSchema):
    total_duration_estimate_ms: int = 0
    is_final: bool = False
    requires_tts_backfill: bool = True


class EntityExtractionHints(BaseSchema):
    focus_entities: list[str] = ["characters", "scene_places", "props", "costumes"]
    culture_hint_from_router: str = ""


class AudioPreHint(BaseSchema):
    scene_id: str
    hint: str  # dialogue_heavy | action_sfx | wind_rain | crowd_ambience | metal_hit_possible


class ParallelTaskGroup(BaseSchema):
    group_id: str
    tasks: list[str] = []


# ── Input / Output ────────────────────────────────────────────────────────────

class Skill03Input(BaseSchema):
    # From SKILL 01
    segments: list[dict] = []
    normalized_text: str = ""
    # From SKILL 02
    language_route: dict = {}
    culture_hint: str = ""
    scene_planner_mode: str = "generic"
    # Creative constraints
    max_shots_per_scene: int = 8
    user_overrides: dict = {}
    project_defaults: dict = {}
    feature_flags: dict = {}


class Skill03Output(BaseSchema):
    scene_plan: list[ScenePlan] = []
    shot_plan: list[ShotPlan] = []
    provisional_timeline: ProvisionalTimeline = ProvisionalTimeline()
    entity_extraction_hints: EntityExtractionHints = EntityExtractionHints()
    audio_pre_hints: list[AudioPreHint] = []
    parallel_task_groups: list[ParallelTaskGroup] = []
    warnings: list[str] = []
    review_required_items: list[str] = []
    status: str = "ready_for_parallel_execution"
