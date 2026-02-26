"""Timeline validation – checks structural integrity before compose."""

from __future__ import annotations

from ainern2d_shared.schemas.timeline import TimelinePlanDto
from ainern2d_shared.telemetry.logging import get_logger

logger = get_logger(__name__)


class TimelineValidator:
    """Validates a TimelinePlanDto for structural correctness."""

    def validate(self, timeline: TimelinePlanDto) -> tuple[bool, list[str]]:
        """Check timeline integrity.

        Returns ``(is_valid, error_messages)``.
        """
        errors: list[str] = []

        # 1. total_duration_ms must be positive
        if timeline.total_duration_ms <= 0:
            errors.append(f"total_duration_ms must be > 0, got {timeline.total_duration_ms}")

        # 2. No overlapping video tracks
        sorted_videos = sorted(timeline.video_tracks, key=lambda v: v.start_time_ms)
        for i in range(1, len(sorted_videos)):
            prev = sorted_videos[i - 1]
            curr = sorted_videos[i]
            prev_end = prev.start_time_ms + prev.duration_ms
            if prev_end > curr.start_time_ms:
                errors.append(
                    f"video overlap: '{prev.id}' ends at {prev_end}ms "
                    f"but '{curr.id}' starts at {curr.start_time_ms}ms"
                )

        # 3. Audio aligned to video (each audio item must fall within total duration)
        for audio in timeline.audio_tracks:
            audio_end = audio.start_time_ms + audio.duration_ms
            if audio_end > timeline.total_duration_ms:
                errors.append(
                    f"audio '{audio.id}' ends at {audio_end}ms "
                    f"which exceeds total_duration_ms={timeline.total_duration_ms}"
                )

        # 4. All shot_ids in video tracks must be non-empty
        video_shot_ids = {v.shot_id for v in timeline.video_tracks}
        for shot_id in video_shot_ids:
            if not shot_id:
                errors.append("video track contains an empty shot_id")

        is_valid = len(errors) == 0
        if not is_valid:
            logger.warning("timeline validation failed: %d error(s)", len(errors))
        return is_valid, errors