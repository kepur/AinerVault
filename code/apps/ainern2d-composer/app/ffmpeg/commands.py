"""FFmpeg command builder – constructs CLI argument lists for ffmpeg."""

from __future__ import annotations

from ainern2d_shared.telemetry.logging import get_logger

logger = get_logger(__name__)


class FFmpegCommandBuilder:
    """Builds ffmpeg command-line argument lists for common operations."""

    def concat_videos(self, input_uris: list[str], output_uri: str) -> list[str]:
        """Return ffmpeg args to concatenate video files via the concat demuxer."""
        if not input_uris:
            raise ValueError("input_uris must not be empty")

        # Build concat filter for multiple inputs
        inputs: list[str] = []
        for uri in input_uris:
            inputs.extend(["-i", uri])

        n = len(input_uris)
        filter_str = "".join(f"[{i}:v:0][{i}:a:0]" for i in range(n))
        filter_str += f"concat=n={n}:v=1:a=1[outv][outa]"

        cmd = (
            ["ffmpeg", "-y"]
            + inputs
            + ["-filter_complex", filter_str, "-map", "[outv]", "-map", "[outa]", output_uri]
        )
        logger.debug("concat_videos: %d inputs -> %s", n, output_uri)
        return cmd

    def mix_audio(
        self, video_uri: str, audio_uris: list[str], output_uri: str
    ) -> list[str]:
        """Return ffmpeg args to mix one or more audio tracks onto a video."""
        inputs = ["-i", video_uri]
        for uri in audio_uris:
            inputs.extend(["-i", uri])

        n_audio = len(audio_uris)
        # Mix all audio inputs together, keep video from first input
        audio_inputs = "".join(f"[{i + 1}:a]" for i in range(n_audio))
        filter_str = f"{audio_inputs}amix=inputs={n_audio}:duration=longest[aout]"

        cmd = (
            ["ffmpeg", "-y"]
            + inputs
            + ["-filter_complex", filter_str, "-map", "0:v", "-map", "[aout]",
               "-c:v", "copy", output_uri]
        )
        logger.debug("mix_audio: video + %d audio -> %s", n_audio, output_uri)
        return cmd

    def add_subtitles(
        self, video_uri: str, subtitle_uri: str, output_uri: str
    ) -> list[str]:
        """Return ffmpeg args to burn subtitles into a video."""
        cmd = [
            "ffmpeg", "-y",
            "-i", video_uri,
            "-vf", f"subtitles={subtitle_uri}",
            "-c:a", "copy",
            output_uri,
        ]
        logger.debug("add_subtitles: %s + %s -> %s", video_uri, subtitle_uri, output_uri)
        return cmd

    def transcode(
        self,
        input_uri: str,
        output_uri: str,
        codec: str = "libx264",
        quality: str = "medium",
    ) -> list[str]:
        """Return ffmpeg args to transcode a media file."""
        cmd = [
            "ffmpeg", "-y",
            "-i", input_uri,
            "-c:v", codec,
            "-preset", quality,
            "-c:a", "aac",
            output_uri,
        ]
        logger.debug("transcode: %s -> %s (codec=%s, quality=%s)", input_uri, output_uri, codec, quality)
        return cmd

    def trim_media(
        self,
        input_uri: str,
        output_uri: str,
        start_sec: float,
        end_sec: float
    ) -> list[str]:
        """Return ffmpeg args to trim a media file."""
        duration = end_sec - start_sec
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start_sec),
            "-i", input_uri,
            "-t", str(duration),
            "-c", "copy",
            output_uri
        ]
        logger.debug("trim_media: %s -> %s (start=%s, duration=%s)", input_uri, output_uri, start_sec, duration)
        return cmd

    def change_speed(
        self,
        input_uri: str,
        output_uri: str,
        speed_factor: float,
        has_video: bool = True,
        has_audio: bool = True
    ) -> list[str]:
        """Return ffmpeg args to change the speed of a media file."""
        cmd = ["ffmpeg", "-y", "-i", input_uri]
        
        filter_complex = []
        if has_video:
            # setpts = 1/speed_factor * PTS
            video_pts = 1.0 / speed_factor
            filter_complex.append(f"[0:v]setpts={video_pts}*PTS[v]")
            
        if has_audio:
            # atempo max is 2.0, min 0.5. For simpler implementation we just use one atempo.
            # A robust implementation might chain atempos if speed > 2.0
            filter_complex.append(f"[0:a]atempo={speed_factor}[a]")
            
        if filter_complex:
            cmd.extend(["-filter_complex", ";".join(filter_complex)])
            if has_video:
                cmd.extend(["-map", "[v]"])
            if has_audio:
                cmd.extend(["-map", "[a]"])
                
        cmd.append(output_uri)
        logger.debug("change_speed: %s -> %s (speed_factor=%s)", input_uri, output_uri, speed_factor)
        return cmd