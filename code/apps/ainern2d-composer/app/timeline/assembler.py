"""Timeline assembly – lay out video/audio items into a TimelinePlanDto."""

from __future__ import annotations

from ainern2d_shared.schemas.timeline import (
    ShotPlan,
    TimelineAudioItemDto,
    TimelinePlanDto,
    TimelineVideoItemDto,
)
from ainern2d_shared.telemetry.logging import get_logger

logger = get_logger(__name__)


class TimelineAssembler:
    """Builds a TimelinePlanDto from a ShotPlan and rendered media items."""

    def assemble(
        self,
        shot_plan: ShotPlan,
        audio_items: list[TimelineAudioItemDto],
        video_items: list[TimelineVideoItemDto],
    ) -> TimelinePlanDto:
        """Lay out video tracks sequentially by shot order and align audio.

        *video_items* are matched to shots by ``shot_id`` and placed
        sequentially.  *audio_items* are aligned to the video timing of
        their corresponding shot (matched by ``id`` prefix convention or
        insertion order).
        """
        video_by_shot: dict[str, TimelineVideoItemDto] = {v.shot_id: v for v in video_items}

        ordered_videos: list[TimelineVideoItemDto] = []
        cursor_ms = 0

        for shot in shot_plan.shots:
            video = video_by_shot.get(shot.shot_id)
            if video is None:
                logger.warning("no video item for shot %s – skipped", shot.shot_id)
                continue

            video = video.model_copy(
                update={"start_time_ms": cursor_ms, "duration_ms": shot.duration_ms},
            )
            ordered_videos.append(video)
            cursor_ms += shot.duration_ms

        # Align audio items to their corresponding video start time
        aligned_audio: list[TimelineAudioItemDto] = []
        video_start_by_shot: dict[str, int] = {v.shot_id: v.start_time_ms for v in ordered_videos}

        for audio in audio_items:
            # Try to match audio to a shot via id convention "<shot_id>_*"
            matched_start: int | None = None
            for shot_id, start in video_start_by_shot.items():
                if audio.id.startswith(shot_id):
                    matched_start = start
                    break

            if matched_start is not None:
                audio = audio.model_copy(update={"start_time_ms": matched_start})
            aligned_audio.append(audio)

        total_duration_ms = cursor_ms

        timeline = TimelinePlanDto(
            run_id=shot_plan.run_id,
            total_duration_ms=total_duration_ms,
            video_tracks=ordered_videos,
            audio_tracks=aligned_audio,
        )
        logger.info(
            "assembled timeline: %d video, %d audio, duration=%dms",
            len(ordered_videos),
            len(aligned_audio),
            total_duration_ms,
        )
        return timeline