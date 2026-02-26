"""Text-to-Speech worker – converts text + voice_id into an audio file."""

from __future__ import annotations

from ainern2d_shared.schemas.worker import WorkerResult
from ainern2d_shared.telemetry.logging import get_logger

from app.common.base_worker import BaseWorker

logger = get_logger(__name__)


class TTSWorker(BaseWorker):
    """Generate speech audio from text and a voice profile."""

    def __init__(self, **kwargs) -> None:
        super().__init__(worker_type="worker-audio-tts", **kwargs)

    async def execute(self, job_payload: dict) -> WorkerResult:
        job_id: str = job_payload.get("job_id", "")
        run_id: str = job_payload.get("run_id", "")
        try:
            text: str = job_payload["text"]
            voice_id: str = job_payload.get("voice_id", "default")

            # TODO: call real TTS engine (e.g. edge-tts, Azure, Bark)
            logger.info(
                "job %s: generating TTS for voice=%s, text_len=%d",
                job_id,
                voice_id,
                len(text),
            )

            # Stub: return placeholder audio URI
            audio_uri = f"s3://ainer-assets/tts/{job_id}.wav"

            return WorkerResult(
                job_id=job_id,
                run_id=run_id,
                status="success",
                output={"audio_uri": audio_uri, "voice_id": voice_id},
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
