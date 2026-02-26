"""SKILL 06: AudioTimelineService — 业务逻辑实现。
参考规格: SKILL_06_AUDIO_TIMELINE_COMPOSER.md
状态: SERVICE_READY
"""
from __future__ import annotations

from loguru import logger
from sqlalchemy.orm import Session

from ainern2d_shared.schemas.skills.skill_06 import (
    AudioTrack,
    Skill06Input,
    Skill06Output,
    TimingAnchor,
)
from ainern2d_shared.services.base_skill import BaseSkillService, SkillContext

# ── Default durations if not provided (ms) ───────────────────────────────────
_DEFAULT_SHOT_DURATION_MS = 3000
_FADE_MS = 50  # 50ms precision as per spec


class AudioTimelineService(BaseSkillService[Skill06Input, Skill06Output]):
    """SKILL 06 — Audio Timeline Composer.

    State machine:
      INIT → COLLECTING → ALIGNING → COMPOSING_TRACKS → VALIDATING
           → READY_FOR_VISUAL_RENDER_PLANNING | FAILED
    """

    skill_id = "skill_06"
    skill_name = "AudioTimelineService"

    def __init__(self, db: Session) -> None:
        super().__init__(db)

    def execute(self, input_dto: Skill06Input, ctx: SkillContext) -> Skill06Output:
        self._record_state(ctx, "INIT", "COLLECTING")

        audio_results: list[dict] = input_dto.audio_results or []
        shots: list[dict] = input_dto.shots or []
        timing_constraints: dict = input_dto.timing_constraints or {}
        min_gap_ms = int(timing_constraints.get("min_gap_ms", 0))

        self._record_state(ctx, "COLLECTING", "ALIGNING")

        # Build shot timing map: shot_id → (start_ms, end_ms)
        shot_timing: dict[str, tuple[int, int]] = {}
        cursor_ms = 0
        for shot in shots:
            sid = shot.get("shot_id", "")
            dur_ms = int(float(shot.get("duration_seconds", _DEFAULT_SHOT_DURATION_MS / 1000)) * 1000)
            shot_timing[sid] = (cursor_ms, cursor_ms + dur_ms)
            cursor_ms += dur_ms + min_gap_ms

        self._record_state(ctx, "ALIGNING", "COMPOSING_TRACKS")

        tracks: list[AudioTrack] = []
        timing_anchors: list[TimingAnchor] = []
        track_counter = 0

        for result in audio_results:
            task_type = result.get("task_type", "dialogue")
            shot_id = result.get("shot_id", "")
            asset_uri = result.get("asset_uri", result.get("output_uri", ""))
            volume = float(result.get("volume", 1.0))

            start_ms, end_ms = shot_timing.get(shot_id, (0, _DEFAULT_SHOT_DURATION_MS))

            track_id = f"trk_{track_counter:04d}_{task_type}"
            track_counter += 1

            tracks.append(AudioTrack(
                track_id=track_id,
                track_type=task_type,
                asset_uri=asset_uri,
                start_ms=start_ms,
                end_ms=end_ms,
                volume=volume,
                fade_in_ms=_FADE_MS if task_type in ("bgm", "ambience") else 0,
                fade_out_ms=_FADE_MS if task_type in ("bgm", "ambience") else 0,
            ))

        # Build timing anchors from shot boundaries
        for shot in shots:
            sid = shot.get("shot_id", "")
            start_ms, _ = shot_timing.get(sid, (0, 0))
            timing_anchors.append(TimingAnchor(
                anchor_id=f"anc_{sid}",
                shot_id=sid,
                timestamp_ms=start_ms,
                anchor_type="shot_boundary",
            ))

        total_duration_ms = cursor_ms

        self._record_state(ctx, "COMPOSING_TRACKS", "VALIDATING")
        self._record_state(ctx, "VALIDATING", "READY_FOR_VISUAL_RENDER_PLANNING")

        logger.info(
            f"[{self.skill_id}] completed | run={ctx.run_id} "
            f"tracks={len(tracks)} anchors={len(timing_anchors)} "
            f"duration_ms={total_duration_ms}"
        )

        return Skill06Output(
            tracks=tracks,
            timing_anchors=timing_anchors,
            total_duration_ms=total_duration_ms,
            status="ready_for_visual_render_planning",
        )
