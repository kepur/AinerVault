"""Background music generation worker."""

from __future__ import annotations

from ainern2d_shared.schemas.worker import WorkerResult
from ainern2d_shared.telemetry.logging import get_logger

from app.common.base_worker import BaseWorker

logger = get_logger(__name__)


class BGMWorker(BaseWorker):
    """Generate background music from mood / genre / duration parameters."""

    def __init__(self, **kwargs) -> None:
        super().__init__(worker_type="worker-audio-bgm", **kwargs)

    async def execute(self, job_payload: dict) -> WorkerResult:
        job_id: str = job_payload.get("job_id", "")
        run_id: str = job_payload.get("run_id", "")
        try:
            mood: str = job_payload.get("mood", "neutral")
            genre: str = job_payload.get("genre", "ambient")
            duration_s: float = job_payload.get("duration_s", 30.0)

            # TODO: call real music generation API (e.g. MusicGen, Suno)
            logger.info(
                "job %s: generating BGM mood=%s genre=%s duration=%.1fs",
                job_id,
                mood,
                genre,
                duration_s,
            )

            # Stub: return placeholder audio URI
            audio_uri = f"s3://ainer-assets/bgm/{job_id}.mp3"

            return WorkerResult(
                job_id=job_id,
                run_id=run_id,
                status="success",
                output={
                    "audio_uri": audio_uri,
                    "mood": mood,
                    "genre": genre,
                    "duration_s": duration_s,
                },
            )
        except Exception as exc:
            logger.exception("BGMWorker failed for job %s", job_id)
            return WorkerResult(
                job_id=job_id,
                run_id=run_id,
                status="error",
                error_code="BGM_EXECUTION_ERROR",
                error_message=str(exc),
            )
