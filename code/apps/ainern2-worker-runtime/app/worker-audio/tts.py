"""Text-to-Speech worker.

Primary backend: OpenAI TTS API (tts-1 / tts-1-hd).
Fallback backend: edge-tts (free Microsoft Edge voices, no API key needed).
"""

from __future__ import annotations

import os
import tempfile
import time

from ainern2d_shared.schemas.worker import WorkerResult
from ainern2d_shared.telemetry.logging import get_logger

from app.common.base_worker import BaseWorker

logger = get_logger(__name__)

# Voice mapping: speaker_id → (openai_voice, edge_voice)
_VOICE_MAP: dict[str, tuple[str, str]] = {
    "male_zh":    ("onyx",   "zh-CN-YunxiNeural"),
    "female_zh":  ("nova",   "zh-CN-XiaoxiaoNeural"),
    "male_en":    ("echo",   "en-US-GuyNeural"),
    "female_en":  ("shimmer","en-US-JennyNeural"),
    "narrator":   ("alloy",  "en-US-AriaNeural"),
}
_DEFAULT_VOICE = ("alloy", "zh-CN-YunxiNeural")

# OpenAI TTS cost: $0.015 per 1K characters (tts-1), $0.030 (tts-1-hd)
_TTS_COST_PER_1K_CHARS = {"tts-1": 0.015, "tts-1-hd": 0.030}


class TTSWorker(BaseWorker):
    """Generate speech audio from text and a voice profile."""

    def __init__(self, **kwargs) -> None:
        super().__init__(worker_type="worker-audio-tts", **kwargs)

    async def execute(self, job_payload: dict) -> WorkerResult:
        job_id: str = job_payload.get("job_id", "")
        run_id: str = job_payload.get("run_id", "")
        try:
            text: str = job_payload["text"]
            voice_id: str = job_payload.get("voice_id", "narrator")
            tts_model: str = job_payload.get("tts_model", "tts-1")
            output_format: str = job_payload.get("output_format", "mp3")

            logger.info(
                "job %s: generating TTS voice=%s len=%d",
                job_id, voice_id, len(text),
            )

            t0 = time.monotonic()
            openai_voice, edge_voice = _VOICE_MAP.get(voice_id, _DEFAULT_VOICE)

            api_key = self.settings.openai_api_key
            if api_key:
                audio_uri = await self._synthesize_openai(
                    job_id, text, openai_voice, tts_model, output_format
                )
                backend = "openai"
            else:
                audio_uri = await self._synthesize_edge_tts(
                    job_id, text, edge_voice, output_format
                )
                backend = "edge-tts"

            latency_ms = int((time.monotonic() - t0) * 1000)
            cost = len(text) / 1000 * _TTS_COST_PER_1K_CHARS.get(tts_model, 0.015) if api_key else 0.0

            logger.info(
                "job %s: TTS done backend=%s latency=%dms cost=$%.6f",
                job_id, backend, latency_ms, cost,
            )

            return WorkerResult(
                job_id=job_id,
                run_id=run_id,
                status="success",
                output={
                    "audio_uri": audio_uri,
                    "voice_id": voice_id,
                    "backend": backend,
                    "latency_ms": latency_ms,
                    "cost_estimate": cost,
                    "char_count": len(text),
                },
            )
        except Exception as exc:
            logger.exception("TTSWorker failed for job %s", job_id)
            return WorkerResult(
                job_id=job_id,
                run_id=run_id,
                status="error",
                error_code="TTS_EXECUTION_ERROR",
                error_message=str(exc),
            )

    async def _synthesize_openai(
        self,
        job_id: str,
        text: str,
        voice: str,
        model: str,
        fmt: str,
    ) -> str:
        """Synthesize via OpenAI TTS API and upload to object storage."""
        try:
            from openai import AsyncOpenAI
        except ImportError:
            raise RuntimeError("openai SDK not installed; run: pip install openai")

        client = AsyncOpenAI(
            api_key=self.settings.openai_api_key,
            base_url=self.settings.openai_base_url,
        )
        response = await client.audio.speech.create(
            model=model,
            voice=voice,
            input=text,
            response_format=fmt,
        )
        # Write to temp file then upload
        with tempfile.NamedTemporaryFile(suffix=f".{fmt}", delete=False) as tmp:
            tmp.write(await response.aread())
            tmp_path = tmp.name

        audio_uri = await self._upload(tmp_path, job_id, fmt)
        os.unlink(tmp_path)
        return audio_uri

    async def _synthesize_edge_tts(
        self,
        job_id: str,
        text: str,
        voice: str,
        fmt: str,
    ) -> str:
        """Synthesize via edge-tts (free Microsoft Neural voices)."""
        try:
            import edge_tts
        except ImportError:
            raise RuntimeError("edge-tts not installed; run: pip install edge-tts")

        ext = "mp3" if fmt in ("mp3", "audio-24khz-48kbitrate-mono-mp3") else fmt
        with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp:
            tmp_path = tmp.name

        communicate = edge_tts.Communicate(text=text, voice=voice)
        await communicate.save(tmp_path)

        audio_uri = await self._upload(tmp_path, job_id, ext)
        os.unlink(tmp_path)
        return audio_uri

    async def _upload(self, local_path: str, job_id: str, ext: str) -> str:
        """Upload local file to object storage and return URI.

        Returns an s3:// URI. The actual upload uses the shared S3 client.
        """
        try:
            from ainern2d_shared.storage.s3 import S3Client
            s3 = S3Client(self.settings)
            key = f"tts/{job_id}.{ext}"
            await s3.upload_file(local_path, key)
            return f"s3://{self.settings.s3_bucket}/{key}"
        except Exception as exc:
            logger.warning("S3 upload failed (%s); returning local path", exc)
            return f"file://{local_path}"
