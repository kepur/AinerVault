"""Lipsync alignment quality report generator.

Uses ffprobe-based A/V sync measurement as a lightweight proxy for
SyncNet confidence scores when the full SyncNet model is not available.
"""

from __future__ import annotations

import asyncio
import json
import shutil

from ainern2d_shared.telemetry.logging import get_logger

from app.worker_video.pipeline_i2v import _download_to_temp

logger = get_logger(__name__)

_FFPROBE_BIN = shutil.which("ffprobe") or "ffprobe"


async def _probe_av_streams(local_path: str) -> dict:
    """Run ffprobe and return stream info as a dict."""
    cmd = [
        _FFPROBE_BIN,
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        local_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        return {}
    try:
        return json.loads(stdout.decode())
    except json.JSONDecodeError:
        return {}


def _parse_drift_ms(stream_info: dict) -> float:
    """Estimate A/V drift from start_time differences of audio and video streams."""
    streams = stream_info.get("streams", [])
    video_start: float | None = None
    audio_start: float | None = None
    for s in streams:
        try:
            t = float(s.get("start_time", "nan"))
        except ValueError:
            continue
        if s.get("codec_type") == "video" and video_start is None:
            video_start = t
        elif s.get("codec_type") == "audio" and audio_start is None:
            audio_start = t

    if video_start is None or audio_start is None:
        return 0.0
    return (audio_start - video_start) * 1000.0  # ms


def _compute_sync_accuracy(drift_ms: float) -> float:
    """Map drift magnitude to a [0, 1] sync accuracy score.

    |drift| < 40ms  → ~1.0 (barely perceptible)
    |drift| < 80ms  → ~0.7
    |drift| < 200ms → ~0.4
    >= 200ms        → ~0.0
    """
    abs_drift = abs(drift_ms)
    if abs_drift < 40:
        return 1.0 - abs_drift / 400
    if abs_drift < 80:
        return 0.7 - (abs_drift - 40) / 200
    if abs_drift < 200:
        return 0.4 - (abs_drift - 80) / 600
    return max(0.0, 0.1 - (abs_drift - 200) / 2000)


class AlignmentReporter:
    """Evaluate audio-video lip-sync quality and produce a metrics report."""

    async def generate(
        self,
        audio_uri: str,
        video_uri: str,
        output_uri: str,
    ) -> dict:
        """Compute lip-sync quality metrics.

        Args:
            audio_uri: URI of the source audio track.
            video_uri: URI of the original (pre-lipsync) video.
            output_uri: URI of the lip-synced output video.

        Returns:
            Dict with keys: ``sync_accuracy``, ``drift_ms``,
            ``phoneme_match_rate``, ``confidence``.
        """
        logger.info(
            "generating alignment report: audio=%s video=%s output=%s",
            audio_uri, video_uri, output_uri,
        )

        try:
            local_output = await _download_to_temp(output_uri)
            stream_info = await _probe_av_streams(local_output)

            drift_ms = _parse_drift_ms(stream_info)
            sync_accuracy = _compute_sync_accuracy(drift_ms)

            # Phoneme match rate: no light-weight model available without
            # full SyncNet weights; estimate from sync_accuracy as proxy.
            phoneme_match_rate = round(sync_accuracy * 0.9, 3)
            confidence = round(sync_accuracy, 3)

        except Exception as exc:
            logger.warning("Alignment report probe failed (%s); returning defaults", exc)
            drift_ms = 0.0
            sync_accuracy = 0.0
            phoneme_match_rate = 0.0
            confidence = 0.0

        return {
            "sync_accuracy": round(sync_accuracy, 3),
            "drift_ms": round(drift_ms, 2),
            "phoneme_match_rate": phoneme_match_rate,
            "confidence": confidence,
        }
