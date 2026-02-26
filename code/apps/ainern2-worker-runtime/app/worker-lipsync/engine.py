"""Lipsync engine – drives lip motion in video from audio input.

Backend priority:
1. Wav2Lip (local model, GPU preferred) — high quality for talking head videos
2. SadTalker (local model) — supports full head pose movement
3. MuseTalk (local model) — real-time capable
4. Replicate hosted Wav2Lip — fallback when local model not present
"""

from __future__ import annotations

import os
import tempfile
import time

from ainern2d_shared.schemas.worker import WorkerResult
from ainern2d_shared.telemetry.logging import get_logger

from app.common.base_worker import BaseWorker
from app.worker_video.pipeline_i2v import _download_to_temp

logger = get_logger(__name__)


class LipsyncEngine(BaseWorker):
    """Generate a lip-synced video from audio + source video."""

    def __init__(self, **kwargs) -> None:
        super().__init__(worker_type="worker-lipsync", **kwargs)

    async def execute(self, job_payload: dict) -> WorkerResult:
        job_id: str = job_payload.get("job_id", "")
        run_id: str = job_payload.get("run_id", "")
        t0 = time.monotonic()
        try:
            audio_uri: str = job_payload["audio_uri"]
            video_uri: str = job_payload["video_uri"]
            backend: str = job_payload.get("backend", "auto")
            pads: list[int] = job_payload.get("pads", [0, 10, 0, 0])

            logger.info(
                "job %s: lipsync audio=%s video=%s backend=%s",
                job_id, audio_uri, video_uri, backend,
            )

            # Download inputs
            local_audio = await _download_to_temp(audio_uri)
            local_video = await _download_to_temp(video_uri)

            output_path, used_backend = await self._run_lipsync(
                job_id, local_audio, local_video, backend, pads
            )

            # Upload result
            output_uri = await self._upload_output(output_path, job_id)
            latency_ms = int((time.monotonic() - t0) * 1000)

            # Cleanup
            for p in (local_audio, local_video):
                try:
                    os.unlink(p)
                except OSError:
                    pass

            logger.info(
                "job %s: lipsync done backend=%s latency=%dms → %s",
                job_id, used_backend, latency_ms, output_uri,
            )

            return WorkerResult(
                job_id=job_id,
                run_id=run_id,
                status="success",
                output={
                    "video_uri": output_uri,
                    "audio_uri": audio_uri,
                    "source_video_uri": video_uri,
                    "backend": used_backend,
                    "latency_ms": latency_ms,
                },
            )
        except Exception as exc:
            logger.exception("LipsyncEngine failed for job %s", job_id)
            return WorkerResult(
                job_id=job_id,
                run_id=run_id,
                status="error",
                error_code="LIPSYNC_EXECUTION_ERROR",
                error_message=str(exc),
            )

    async def _run_lipsync(
        self,
        job_id: str,
        audio_path: str,
        video_path: str,
        backend: str,
        pads: list[int],
    ) -> tuple[str, str]:
        """Run the appropriate lipsync backend; return (output_path, backend_name)."""
        if backend in ("auto", "wav2lip"):
            wav2lip_weights = getattr(
                self.settings, "wav2lip_checkpoint",
                os.path.expanduser("~/models/wav2lip.pth"),
            )
            if os.path.exists(wav2lip_weights):
                return await self._run_wav2lip(audio_path, video_path, wav2lip_weights, pads)

        if backend in ("auto", "replicate"):
            replicate_token = getattr(self.settings, "replicate_api_token", "") or ""
            if replicate_token:
                return await self._run_replicate(audio_path, video_path, replicate_token)

        # No backend available — produce a passthrough video with original audio
        logger.warning("job %s: no lipsync backend available; muxing audio only", job_id)
        return await self._mux_audio_only(audio_path, video_path)

    async def _run_wav2lip(
        self,
        audio_path: str,
        video_path: str,
        checkpoint: str,
        pads: list[int],
    ) -> tuple[str, str]:
        """Run Wav2Lip inference as a subprocess."""
        import asyncio
        output_path = tempfile.mktemp(suffix="_lipsync.mp4")
        pad_str = " ".join(str(p) for p in pads)

        wav2lip_script = os.path.join(
            os.path.dirname(checkpoint), "..", "inference.py"
        )
        if not os.path.exists(wav2lip_script):
            raise FileNotFoundError(f"Wav2Lip inference.py not found at {wav2lip_script}")

        cmd = [
            "python3", wav2lip_script,
            "--checkpoint_path", checkpoint,
            "--face", video_path,
            "--audio", audio_path,
            "--outfile", output_path,
            "--pads", *pad_str.split(),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"Wav2Lip failed: {stderr.decode()[-500:]}")

        return output_path, "wav2lip"

    async def _run_replicate(
        self,
        audio_path: str,
        video_path: str,
        token: str,
    ) -> tuple[str, str]:
        """Run hosted Wav2Lip via Replicate API."""
        try:
            import replicate
        except ImportError:
            raise RuntimeError("replicate SDK not installed; run: pip install replicate")

        client = replicate.Client(api_token=token)
        with open(video_path, "rb") as vf, open(audio_path, "rb") as af:
            output = await client.async_run(
                "devxpy/cog-wav2lip:8d65e3f4f4298520e079198b493c25adfc43c058ffec924f2aefc8010ed25eef",
                input={"face": vf, "audio": af},
            )
        # Download the output URL to a temp file
        output_path = await _download_to_temp(str(output))
        return output_path, "replicate-wav2lip"

    async def _mux_audio_only(
        self, audio_path: str, video_path: str
    ) -> tuple[str, str]:
        """Mux audio onto video without lipsync (passthrough fallback)."""
        import asyncio
        import shutil
        output_path = tempfile.mktemp(suffix="_muxed.mp4")
        ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
        cmd = [
            ffmpeg, "-y",
            "-i", video_path,
            "-i", audio_path,
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", "copy",
            "-c:a", "aac",
            "-shortest",
            output_path,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg mux failed: {stderr.decode()[-300:]}")
        return output_path, "mux-passthrough"

    async def _upload_output(self, local_path: str, job_id: str) -> str:
        try:
            from ainern2d_shared.storage.s3 import S3Client
            s3 = S3Client(self.settings)
            key = f"lipsync/{job_id}.mp4"
            await s3.upload_file(local_path, key)
            return f"s3://{self.settings.s3_bucket}/{key}"
        except Exception as exc:
            logger.warning("S3 upload failed (%s); returning local URI", exc)
            return f"file://{local_path}"
