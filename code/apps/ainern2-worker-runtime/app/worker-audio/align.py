"""Audio/video alignment and timing utilities using ffprobe."""

from __future__ import annotations

import asyncio
import json
import shutil

from ainern2d_shared.telemetry.logging import get_logger

logger = get_logger(__name__)

_FFPROBE = shutil.which("ffprobe")


async def _probe_duration_ms(uri: str) -> float:
    """Use ffprobe to get the duration of a media file in milliseconds.

    Falls back to 0.0 if ffprobe is unavailable or the file can't be read.
    """
    if not _FFPROBE:
        logger.warning("ffprobe not found on PATH; returning duration=0")
        return 0.0

    cmd = [
        _FFPROBE,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        uri,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        info = json.loads(stdout.decode())
        duration_s = float(info.get("format", {}).get("duration", 0) or 0)
        return duration_s * 1000.0
    except Exception as exc:
        logger.warning("ffprobe failed for %s: %s", uri, exc)
        return 0.0


async def _detect_silence_ffmpeg(audio_uri: str) -> list[tuple[float, float]]:
    """Detect silence regions using ffmpeg silencedetect filter.

    Returns list of (start_ms, end_ms) tuples.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        logger.warning("ffmpeg not found on PATH; skipping silence detection")
        return []

    cmd = [
        ffmpeg,
        "-i", audio_uri,
        "-af", "silencedetect=noise=-40dB:d=0.3",
        "-f", "null", "-",
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        output = stderr.decode()
    except Exception as exc:
        logger.warning("ffmpeg silencedetect failed for %s: %s", audio_uri, exc)
        return []

    regions: list[tuple[float, float]] = []
    start_s: float | None = None
    for line in output.splitlines():
        if "silence_start" in line:
            try:
                start_s = float(line.split("silence_start:")[-1].strip())
            except ValueError:
                pass
        elif "silence_end" in line and start_s is not None:
            try:
                end_s = float(line.split("silence_end:")[-1].split("|")[0].strip())
                regions.append((start_s * 1000.0, end_s * 1000.0))
                start_s = None
            except ValueError:
                pass
    return regions


class AudioAligner:
    """Analyse and align audio to video timing."""

    async def align(self, audio_uri: str, video_uri: str) -> dict:
        """Probe durations and detect silence regions.

        Returns:
            dict with keys:
            ``audio_duration_ms``, ``video_duration_ms``,
            ``drift_ms``, ``silence_regions``.
        """
        logger.info("aligning audio=%s with video=%s", audio_uri, video_uri)

        audio_duration_ms, video_duration_ms, silence_regions = await asyncio.gather(
            _probe_duration_ms(audio_uri),
            _probe_duration_ms(video_uri),
            self.detect_silence(audio_uri),
        )

        drift_ms = audio_duration_ms - video_duration_ms

        logger.info(
            "align done: audio=%.0fms video=%.0fms drift=%.0fms silence_regions=%d",
            audio_duration_ms, video_duration_ms, drift_ms, len(silence_regions),
        )

        return {
            "audio_duration_ms": audio_duration_ms,
            "video_duration_ms": video_duration_ms,
            "drift_ms": drift_ms,
            "silence_regions": silence_regions,
        }

    async def detect_silence(self, audio_uri: str) -> list[tuple[float, float]]:
        """Detect silence regions using ffmpeg silencedetect."""
        logger.info("detecting silence in %s", audio_uri)
        return await _detect_silence_ffmpeg(audio_uri)
