"""Video post-processing utilities – upscale, watermark, format normalisation."""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile

from ainern2d_shared.telemetry.logging import get_logger

logger = get_logger(__name__)

_FFMPEG_BIN = shutil.which("ffmpeg") or "ffmpeg"
_FFPROBE_BIN = shutil.which("ffprobe") or "ffprobe"


async def _run_ffmpeg(*args: str) -> None:
    """Run ffmpeg with the given arguments; raise on non-zero exit."""
    cmd = [_FFMPEG_BIN, "-y", *args]
    logger.debug("ffmpeg: %s", " ".join(cmd))
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed (rc={proc.returncode}): {stderr.decode()[-500:]}")


def _local_path(uri: str) -> str:
    """Strip file:// scheme; return as-is for real paths."""
    return uri[7:] if uri.startswith("file://") else uri


def _derive_output(input_uri: str, suffix: str) -> str:
    """Derive an output URI by inserting suffix before the extension."""
    base, ext = os.path.splitext(_local_path(input_uri))
    out = f"{base}{suffix}{ext or '.mp4'}"
    return f"file://{out}" if input_uri.startswith("file://") else out


class VideoPostProcessor:
    """Collection of video post-processing helpers using ffmpeg."""

    async def upscale(self, video_uri: str, scale: int = 2) -> str:
        """Upscale video resolution by *scale* factor using lanczos filter.

        Returns:
            URI of the upscaled video.
        """
        logger.info("upscaling %s by %dx", video_uri, scale)
        src = _local_path(video_uri)
        dst = _local_path(_derive_output(video_uri, f"_upscaled_{scale}x"))

        await _run_ffmpeg(
            "-i", src,
            "-vf", f"scale=iw*{scale}:ih*{scale}:flags=lanczos",
            "-c:v", "libx264",
            "-crf", "18",
            "-preset", "slow",
            "-c:a", "copy",
            dst,
        )
        return f"file://{dst}" if not video_uri.startswith("file://") else f"file://{dst}"

    async def add_watermark(self, video_uri: str, watermark_uri: str) -> str:
        """Overlay a watermark image onto the bottom-right of the video.

        Returns:
            URI of the watermarked video.
        """
        logger.info("adding watermark %s to %s", watermark_uri, video_uri)
        src = _local_path(video_uri)
        wm = _local_path(watermark_uri)
        dst = _local_path(_derive_output(video_uri, "_watermarked"))

        await _run_ffmpeg(
            "-i", src,
            "-i", wm,
            "-filter_complex",
            "[1:v]scale=iw/8:-1[wm];[0:v][wm]overlay=W-w-10:H-h-10",
            "-c:v", "libx264",
            "-crf", "18",
            "-preset", "fast",
            "-c:a", "copy",
            dst,
        )
        return f"file://{dst}"

    async def normalize_format(
        self,
        video_uri: str,
        target_fps: int = 24,
        target_codec: str = "h264",
    ) -> str:
        """Re-encode video to target FPS / codec.

        Returns:
            URI of the normalised video.
        """
        logger.info(
            "normalizing %s → %d fps, codec=%s", video_uri, target_fps, target_codec
        )
        src = _local_path(video_uri)
        dst = _local_path(_derive_output(video_uri, f"_{target_fps}fps"))

        vcodec = "libx264" if target_codec in ("h264", "avc") else target_codec
        await _run_ffmpeg(
            "-i", src,
            "-r", str(target_fps),
            "-c:v", vcodec,
            "-crf", "23",
            "-preset", "medium",
            "-c:a", "aac",
            "-b:a", "128k",
            dst,
        )
        return f"file://{dst}"

    async def extract_frames(
        self,
        video_uri: str,
        fps: float = 1.0,
        output_dir: str | None = None,
    ) -> list[str]:
        """Extract frames from a video at the given rate.

        Returns:
            List of local file paths to extracted PNG frames.
        """
        src = _local_path(video_uri)
        if output_dir is None:
            output_dir = tempfile.mkdtemp(prefix="frames_")
        os.makedirs(output_dir, exist_ok=True)
        pattern = os.path.join(output_dir, "frame_%06d.png")

        await _run_ffmpeg(
            "-i", src,
            "-vf", f"fps={fps}",
            "-q:v", "2",
            pattern,
        )
        frames = sorted(
            os.path.join(output_dir, f)
            for f in os.listdir(output_dir)
            if f.startswith("frame_") and f.endswith(".png")
        )
        logger.info("extracted %d frames from %s", len(frames), video_uri)
        return frames
