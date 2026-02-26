"""SKILL 06: Audio Timeline Composer — Input/Output DTOs.

Spec: SKILL_06_AUDIO_TIMELINE_COMPOSER.md
Outputs: timeline_final.json + audio_event_manifest.json
"""
from __future__ import annotations

from typing import Any, Literal

from ainern2d_shared.schemas.base import BaseSchema

# ---------------------------------------------------------------------------
# Track-level primitives
# ---------------------------------------------------------------------------

TrackType = Literal["dialogue", "bgm", "sfx", "ambience", "aux"]
AnchorType = Literal[
    "shot_boundary", "beat", "peak", "dialogue_start", "dialogue_end",
]
MixHintType = Literal["duck", "emphasis", "crossfade"]


class AudioEvent(BaseSchema):
    """Single audio clip placed on a track."""

    event_id: str
    shot_id: str = ""
    scene_id: str = ""
    start_ms: int = 0
    end_ms: int = 0
    asset_ref: str = ""
    source_type: str = ""  # tts / bgm_file / sfx_file / ambience_file
    fade_in_ms: int = 0
    fade_out_ms: int = 0
    speaker_id: str = ""
    emotion_hint: str = ""
    event_type: str = ""  # dialogue / metal_hit / ambience_loop / …
    intensity: float = 0.5
    transient_peak: bool = False
    task_id: str = ""  # back-ref to worker task


class AudioTrack(BaseSchema):
    """One logical audio track (dialogue / bgm / sfx / ambience / aux)."""

    track_id: str
    track_type: TrackType = "dialogue"
    events: list[AudioEvent] = []
    priority: int = 0  # lower = higher priority (dialogue=0)
    volume_db: float = 0.0


# ---------------------------------------------------------------------------
# Timing / alignment
# ---------------------------------------------------------------------------


class TimingAnchor(BaseSchema):
    anchor_id: str
    shot_id: str = ""
    time_ms: int = 0
    anchor_type: AnchorType = "shot_boundary"


# ---------------------------------------------------------------------------
# Mix hints
# ---------------------------------------------------------------------------


class MixHintParams(BaseSchema):
    gain_reduction_db: float = -6.0
    attack_ms: int = 50
    release_ms: int = 200
    hint: str = ""


class MixHint(BaseSchema):
    type: MixHintType = "duck"
    trigger_track: str = ""  # track_type that triggers
    target_track: str = ""   # track_type that is affected
    params: MixHintParams = MixHintParams()


# ---------------------------------------------------------------------------
# Scene / shot timelines
# ---------------------------------------------------------------------------


class ShotTimeline(BaseSchema):
    shot_id: str
    scene_id: str = ""
    start_ms: int = 0
    end_ms: int = 0
    dialogue_start_ms: int | None = None
    dialogue_end_ms: int | None = None
    duration_ms: int = 0


class SceneTimeline(BaseSchema):
    scene_id: str
    start_ms: int = 0
    end_ms: int = 0
    shot_ids: list[str] = []
    duration_ms: int = 0


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class ConflictEntry(BaseSchema):
    conflict_id: str = ""
    description: str = ""
    severity: str = "warning"  # warning | error
    shot_id: str = ""


class ValidationReport(BaseSchema):
    alignment_precision_ms: float = 0.0
    conflicts: list[ConflictEntry] = []
    warnings: list[str] = []
    passed: bool = True


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


class ManifestSummary(BaseSchema):
    dialogue_events: int = 0
    sfx_events: int = 0
    bgm_segments: int = 0
    ambience_segments: int = 0
    high_intensity_windows: int = 0


class AnalysisHintsForVisualRender(BaseSchema):
    high_motion_candidate_shots: list[str] = []
    low_motion_ambience_shots: list[str] = []
    dialogue_heavy_shots: list[str] = []


class AudioEventManifest(BaseSchema):
    """audio_event_manifest.json contract (§7.2)."""

    version: str = "1.0"
    events: list[AudioEvent] = []
    summary: ManifestSummary = ManifestSummary()
    analysis_hints_for_visual_render: AnalysisHintsForVisualRender = (
        AnalysisHintsForVisualRender()
    )


# ---------------------------------------------------------------------------
# Backfill report
# ---------------------------------------------------------------------------


class BackfillEntry(BaseSchema):
    shot_id: str
    original_ms: int = 0
    backfilled_ms: int = 0
    delta_ms: int = 0


class BackfillReport(BaseSchema):
    entries: list[BackfillEntry] = []
    total_shift_ms: int = 0


# ---------------------------------------------------------------------------
# Skill 06 Input / Output
# ---------------------------------------------------------------------------


class Skill06Input(BaseSchema):
    """§2 — all inputs consumed by Audio Timeline Composer."""

    # Required
    audio_results: list[dict[str, Any]] = []   # worker results (TTS/BGM/SFX/Ambience)
    audio_plan: dict[str, Any] = {}            # from SKILL 05
    shot_plan: list[dict[str, Any]] = []       # from SKILL 03

    # Optional
    entity_extraction_result: dict[str, Any] = {}
    mix_profile: dict[str, Any] = {}
    feature_flags: dict[str, Any] = {}
    user_overrides: dict[str, Any] = {}


class Skill06Output(BaseSchema):
    """§3 + §7 — combined timeline_final + audio_event_manifest output."""

    # ── timeline_final fields (§7.1) ──
    version: str = "1.0"
    status: str = "ready_for_visual_render_planning"
    final_duration_ms: int = 0
    tracks: list[AudioTrack] = []
    scene_timeline: list[SceneTimeline] = []
    shot_timeline: list[ShotTimeline] = []
    mix_hints: list[MixHint] = []
    warnings: list[str] = []

    # ── audio_event_manifest (§7.2) ──
    audio_event_manifest: AudioEventManifest = AudioEventManifest()

    # ── validation & backfill reports ──
    validation_report: ValidationReport = ValidationReport()
    backfill_report: BackfillReport = BackfillReport()
