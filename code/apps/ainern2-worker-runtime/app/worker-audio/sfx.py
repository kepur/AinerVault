"""Sound effects generation worker.

Backend priority:
1. ElevenLabs Sound Generation API (text-to-SFX, high quality)
2. AudioLDM-2 via Replicate
3. Library fallback (deterministic S3 key based on description hash)
"""

from __future__ import annotations

import time

from ainern2d_shared.schemas.worker import WorkerResult
from ainern2d_shared.telemetry.logging import get_logger

from app.common.base_worker import BaseWorker

logger = get_logger(__name__)

# ElevenLabs cost: ~$0.002 per generation (rough estimate)
_ELEVENLABS_COST = 0.002
# Replicate AudioLDM-2 cost: ~$0.0023 per second
_AUDIOLDM_COST_PER_SEC = 0.0023


class SFXWorker(BaseWorker):
    """Generate sound effect audio from a textual description + timing info."""

    def __init__(self, **kwargs) -> None:
        super().__init__(worker_type="worker-audio-sfx", **kwargs)

    async def execute(self, job_payload: dict) -> WorkerResult:
        job_id: str = job_payload.get("job_id", "")
        run_id: str = job_payload.get("run_id", "")
        t0 = time.monotonic()
        try:
            description: str = job_payload["description"]
            start_ms: float = float(job_payload.get("start_ms", 0.0))
            duration_ms: float = float(job_payload.get("duration_ms", 2000.0))
            duration_s = duration_ms / 1000.0

            logger.info(
                "job %s: generating SFX '%s' at %.0fms for %.0fms",
                job_id, description, start_ms, duration_ms,
            )

            eleven_key = getattr(self.settings, "elevenlabs_api_key", "") or ""
            replicate_token = getattr(self.settings, "replicate_api_token", "") or ""

            if eleven_key:
                audio_uri, backend, cost = await self._generate_elevenlabs(
                    job_id, description, duration_s, eleven_key
                )
            elif replicate_token:
                audio_uri, backend, cost = await self._generate_audioldm(
                    job_id, description, duration_s, replicate_token
                )
            else:
                audio_uri, backend, cost = self._library_fallback(job_id, description)

            latency_ms = int((time.monotonic() - t0) * 1000)
            logger.info("job %s: SFX done backend=%s latency=%dms", job_id, backend, latency_ms)

            return WorkerResult(
                job_id=job_id,
                run_id=run_id,
                status="success",
                output={
                    "audio_uri": audio_uri,
                    "description": description,
                    "start_ms": start_ms,
                    "duration_ms": duration_ms,
                    "backend": backend,
                    "latency_ms": latency_ms,
                    "cost_estimate": cost,
                },
            )
        except Exception as exc:
            logger.exception("SFXWorker failed for job %s", job_id)
            return WorkerResult(
                job_id=job_id,
                run_id=run_id,
                status="error",
                error_code="SFX_EXECUTION_ERROR",
                error_message=str(exc),
            )

    async def _generate_elevenlabs(
        self,
        job_id: str,
        description: str,
        duration_s: float,
        api_key: str,
    ) -> tuple[str, str, float]:
        """Generate SFX via ElevenLabs Sound Generation API."""
        import httpx
        import tempfile
        import os

        url = "https://api.elevenlabs.io/v1/sound-generation"
        headers = {"xi-api-key": api_key, "Content-Type": "application/json"}
        body = {
            "text": description,
            "duration_seconds": min(duration_s, 22.0),  # API max
            "prompt_influence": 0.3,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, headers=headers, json=body)
            resp.raise_for_status()
            audio_bytes = resp.content

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        audio_uri = await self._upload(tmp_path, job_id, "mp3")
        os.unlink(tmp_path)
        return audio_uri, "elevenlabs", _ELEVENLABS_COST

    async def _generate_audioldm(
        self,
        job_id: str,
        description: str,
        duration_s: float,
        token: str,
    ) -> tuple[str, str, float]:
        """Generate SFX via AudioLDM-2 on Replicate."""
        try:
            import replicate
        except ImportError:
            raise RuntimeError("replicate SDK not installed")

        client = replicate.Client(api_token=token)
        output = await client.async_run(
            "cjwbw/audioldm2:9c80e5c6e8cb3e25f8c76f97cda7bc9a2a6bf1b6c9d9d7c5e7c9a7bb15a3de5",
            input={
                "text": description,
                "duration": int(duration_s),
                "guidance_scale": 3.5,
                "ddim_steps": 200,
            },
        )
        audio_uri = str(output) if output else f"s3://ainer-assets/sfx/{job_id}.wav"
        cost = duration_s * _AUDIOLDM_COST_PER_SEC
        return audio_uri, "audioldm2-replicate", cost

    def _library_fallback(
        self, job_id: str, description: str
    ) -> tuple[str, str, float]:
        """Return a deterministic library SFX URI based on description hash."""
        sfx_hash = abs(hash(description)) % 500
        category = "ambient"
        for keyword, cat in [
            ("gun", "weapon"), ("explosion", "explosion"),
            ("footstep", "foley"), ("wind", "nature"),
            ("rain", "nature"), ("crowd", "crowd"),
            ("car", "vehicle"), ("door", "foley"),
        ]:
            if keyword in description.lower():
                category = cat
                break
        audio_uri = f"s3://ainer-assets/sfx/library/{category}/{sfx_hash:05d}.wav"
        logger.info("SFX library fallback → %s", audio_uri)
        return audio_uri, "library-fallback", 0.0

    async def _upload(self, local_path: str, job_id: str, ext: str) -> str:
        try:
            from ainern2d_shared.storage.s3 import S3Client
            s3 = S3Client(self.settings)
            key = f"sfx/{job_id}.{ext}"
            await s3.upload_file(local_path, key)
            return f"s3://{self.settings.s3_bucket}/{key}"
        except Exception as exc:
            logger.warning("S3 upload failed (%s); returning local URI", exc)
            import os
            return f"file://{local_path}"
