"""SKILL 05: Audio Asset Planner — Input/Output DTOs."""
from __future__ import annotations
from ainern2d_shared.schemas.base import BaseSchema


class AudioTask(BaseSchema):
    task_id: str
    shot_id: str
    task_type: str  # tts | bgm | sfx | ambience
    priority: int = 0
    timing_hint_ms: int = 0
    params: dict = {}


class Skill05Input(BaseSchema):
    shots: list[dict] = []
    language_code: str = "zh-CN"
    audio_preferences: dict = {}


class Skill05Output(BaseSchema):
    tts_tasks: list[AudioTask] = []
    bgm_tasks: list[AudioTask] = []
    sfx_tasks: list[AudioTask] = []
    ambience_tasks: list[AudioTask] = []
    status: str = "ready_for_audio_execution"
