"""Timeline export – convert TimelinePlanDto to ffmpeg spec or JSON."""

from __future__ import annotations

import json

from ainern2d_shared.schemas.timeline import TimelinePlanDto
from ainern2d_shared.telemetry.logging import get_logger

logger = get_logger(__name__)


class TimelineExporter:
    """Exports a validated TimelinePlanDto to downstream formats."""

    def to_ffmpeg_spec(self, timeline: TimelinePlanDto) -> dict:
        """Convert timeline to an ffmpeg concat / filter_complex spec dict.

        The returned dict contains:
        - ``inputs``: ordered list of input file URIs
        - ``filter_complex``: filter graph string for audio mixing
        - ``concat_demuxer``: list of dicts for the concat demuxer file
        - ``total_duration_ms``: overall duration
        """
        inputs: list[str] = []
        concat_entries: list[dict] = []

        for idx, video in enumerate(timeline.video_tracks):
            uri = video.artifact_uri or f"missing_{video.id}"
            inputs.append(uri)
            concat_entries.append({
                "file": uri,
                "duration_ms": video.duration_ms,
                "inpoint_ms": video.start_time_ms,
            })

        # Build audio filter_complex
        audio_filters: list[str] = []
        for idx, audio in enumerate(timeline.audio_tracks):
            uri = audio.artifact_uri or f"missing_{audio.id}"
            if uri not in inputs:
                inputs.append(uri)
            input_idx = inputs.index(uri)
            delay_ms = audio.start_time_ms
            volume = audio.volume
            audio_filters.append(
                f"[{input_idx}:a]adelay={delay_ms}|{delay_ms},volume={volume}[a{idx}]"
            )

        filter_complex = ""
        if audio_filters:
            mix_inputs = "".join(f"[a{i}]" for i in range(len(audio_filters)))
            filter_complex = (
                ";".join(audio_filters)
                + f";{mix_inputs}amix=inputs={len(audio_filters)}:duration=longest[aout]"
            )

        spec = {
            "inputs": inputs,
            "concat_demuxer": concat_entries,
            "filter_complex": filter_complex,
            "total_duration_ms": timeline.total_duration_ms,
        }
        logger.debug("ffmpeg spec: %d inputs, filter_complex length=%d", len(inputs), len(filter_complex))
        return spec

    def to_json(self, timeline: TimelinePlanDto) -> str:
        """Serialize the timeline to a JSON string for storage."""
        return json.dumps(timeline.model_dump(mode="json"), ensure_ascii=False)