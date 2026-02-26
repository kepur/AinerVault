"""SKILL 06: Audio Timeline Composer — Input/Output DTOs."""
from __future__ import annotations
from ainern2d_shared.schemas.base import BaseSchema


class AudioTrack(BaseSchema):
    track_id: str
    track_type: str  # dialogue | bgm | sfx | ambience
    asset_uri: str = ""
    start_ms: int = 0
    end_ms: int = 0
    volume: float = 1.0
    fade_in_ms: int = 0
    fade_out_ms: int = 0


class TimingAnchor(BaseSchema):
    anchor_id: str
    shot_id: str
    timestamp_ms: int = 0
    anchor_type: str = "shot_boundary"


class Skill06Input(BaseSchema):
    audio_results: list[dict] = []
    shots: list[dict] = []
    timing_constraints: dict = {}


class Skill06Output(BaseSchema):
    tracks: list[AudioTrack] = []
    timing_anchors: list[TimingAnchor] = []
    total_duration_ms: int = 0
    status: str = "ready_for_visual_render_planning"
