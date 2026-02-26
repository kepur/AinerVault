"""Sound effects generation worker."""

from __future__ import annotations

from ainern2d_shared.schemas.worker import WorkerResult
from ainern2d_shared.telemetry.logging import get_logger

from app.common.base_worker import BaseWorker

logger = get_logger(__name__)


class SFXWorker(BaseWorker):
    """Generate sound effect audio from a textual description + timing info."""

    def __init__(self, **kwargs) -> None:
        super().__init__(worker_type="worker-audio-sfx", **kwargs)

    async def execute(self, job_payload: dict) -> WorkerResult:
        job_id: str = job_payload.get("job_id", "")
        run_id: str = job_payload.get("run_id", "")
        try:
            description: str = job_payload["description"]
            start_ms: float = job_payload.get("start_ms", 0.0)
            duration_ms: float = job_payload.get("duration_ms", 2000.0)

            # TODO: call real SFX generation model (e.g. AudioLDM)
            logger.info(
                "job %s: generating SFX '%s' at %.0fms for %.0fms",
                job_id,
                description,
                start_ms,
                duration_ms,
            )

            # Stub: return placeholder audio URI
            audio_uri = f"s3://ainer-assets/sfx/{job_id}.wav"

            return WorkerResult(
                job_id=job_id,
                run_id=run_id,
                status="success",
                output={
                    "audio_uri": audio_uri,
                    "description": description,
                    "start_ms": start_ms,
                    "duration_ms": duration_ms,
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
