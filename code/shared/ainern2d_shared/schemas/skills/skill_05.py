"""SKILL 05: Audio Asset Planner — Input/Output DTOs."""
from __future__ import annotations

from typing import Optional

from ainern2d_shared.schemas.base import BaseSchema


# ── Sub-objects ───────────────────────────────────────────────────────────────

class TTSTask(BaseSchema):
    tts_task_id: str
    scene_id: str
    shot_id: str
    speaker_id: str = "speaker_unknown"
    text: str = ""
    emotion_hint: str = "neutral"
    speed_hint: str = "normal"  # slow | normal | fast
    must_complete_before_final_timeline: bool = True


class BGMTask(BaseSchema):
    bgm_task_id: str
    scene_id: str
    mood: str = "neutral"
    intensity: str = "medium"  # low | medium | high
    provisional_start_ref: str = ""
    provisional_end_ref: str = ""


class SFXTask(BaseSchema):
    sfx_task_id: str
    shot_id: str
    event_type: str
    density_hint: str = "medium"  # low | medium | high
    timing_mode: str = "provisional_anchor_then_refine"


class AmbienceTask(BaseSchema):
    amb_task_id: str
    scene_id: str
    ambience_type: str
    layering_hint: str = "low_medium"


class AudioTaskDAG(BaseSchema):
    nodes: list[str] = []
    edges: list[list[str]] = []


class ParallelAudioGroup(BaseSchema):
    group_id: str
    tasks: list[str] = []


class ProvisionalAudioTimeline(BaseSchema):
    is_final: bool = False
    requires_tts_duration_backfill: bool = True


class BackendAudioCapability(BaseSchema):
    """Describes what the audio backend supports for validation."""
    supported_tts_speakers: list[str] = []
    supported_bgm_moods: list[str] = []
    supported_sfx_event_types: list[str] = []
    max_parallel_tasks: int = 10
    supported_output_formats: list[str] = ["wav", "mp3"]


# ── Input / Output ────────────────────────────────────────────────────────────

class Skill05Input(BaseSchema):
    # From SKILL 03
    shot_plan: list[dict] = []
    scene_plan: list[dict] = []
    # From SKILL 04 (optional)
    audio_event_candidates: list[dict] = []
    # Config
    language_code: str = "zh-CN"
    global_audio_profile: str = "standard"  # preview | standard | final
    voice_cast_profile: dict = {}
    music_style_profile: dict = {}
    backend_audio_capability: Optional[BackendAudioCapability] = None
    user_overrides: dict = {}
    feature_flags: dict = {}


class Skill05Output(BaseSchema):
    tts_plan: list[TTSTask] = []
    bgm_plan: list[BGMTask] = []
    sfx_plan: list[SFXTask] = []
    ambience_plan: list[AmbienceTask] = []
    audio_task_dag: AudioTaskDAG = AudioTaskDAG()
    provisional_audio_timeline: ProvisionalAudioTimeline = ProvisionalAudioTimeline()
    parallel_audio_groups: list[ParallelAudioGroup] = []
    warnings: list[str] = []
    status: str = "ready_for_audio_execution"
