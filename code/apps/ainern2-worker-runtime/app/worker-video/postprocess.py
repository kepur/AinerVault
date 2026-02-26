"""Video post-processing utilities – upscale, watermark, format normalisation."""

from __future__ import annotations

from ainern2d_shared.telemetry.logging import get_logger

logger = get_logger(__name__)


class VideoPostProcessor:
    """Collection of video post-processing helpers."""

    async def upscale(self, video_uri: str, scale: int = 2) -> str:
        """Upscale video resolution by *scale* factor.

        Returns:
            URI of the upscaled video.
        """
        # TODO: invoke real upscaling model / ffmpeg pipeline
        logger.info("upscaling %s by %dx", video_uri, scale)
        output_uri = video_uri.replace(".mp4", f"_upscaled_{scale}x.mp4")
        return output_uri

    async def add_watermark(self, video_uri: str, watermark_uri: str) -> str:
        """Overlay a watermark image onto the video.

        Returns:
            URI of the watermarked video.
        """
        # TODO: implement watermark overlay via ffmpeg / PIL
        logger.info("adding watermark %s to %s", watermark_uri, video_uri)
        output_uri = video_uri.replace(".mp4", "_watermarked.mp4")
        return output_uri

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
        # TODO: implement re-encoding via ffmpeg
        logger.info(
            "normalizing %s → %d fps, codec=%s", video_uri, target_fps, target_codec
        )
        output_uri = video_uri.replace(".mp4", f"_{target_fps}fps_{target_codec}.mp4")
        return output_uri
