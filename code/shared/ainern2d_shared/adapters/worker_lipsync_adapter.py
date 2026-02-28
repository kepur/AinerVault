"""Lipsync worker adapter – format dispatch and parse results for worker-lipsync."""

from __future__ import annotations

from typing import Any

from ainern2d_shared.ainer_db_models.pipeline_models import Job
from ainern2d_shared.schemas.worker import WorkerResult
from ainern2d_shared.telemetry.logging import get_logger

logger = get_logger(__name__)

_LIPSYNC_DEFAULTS: dict[str, Any] = {
    "alignment_mode": "auto",
    "face_detect": True,
    "output_format": "mp4",
}


class LipsyncWorkerAdapter:
    """Thin adapter for worker-lipsync dispatch and result parsing."""

    def format_dispatch(self, job: Job) -> dict:
        """Extract lipsync-specific fields from job payload with defaults."""
        payload: dict = job.payload_json or {}
        dispatch = {
            "job_id": str(job.id),
            "run_id": str(job.run_id) if job.run_id else None,
            "audio_uri": payload.get("audio_uri", ""),
            "video_uri": payload.get("video_uri", ""),
            "alignment_mode": payload.get("alignment_mode", _LIPSYNC_DEFAULTS["alignment_mode"]),
            "face_detect": payload.get("face_detect", _LIPSYNC_DEFAULTS["face_detect"]),
            "output_format": payload.get("output_format", _LIPSYNC_DEFAULTS["output_format"]),
            "face_region": payload.get("face_region"),
        }
        if not dispatch["audio_uri"] or not dispatch["video_uri"]:
            logger.warning("lipsync dispatch missing audio_uri or video_uri: job=%s", job.id)
        logger.debug("lipsync dispatch: job=%s mode=%s", job.id, dispatch["alignment_mode"])
        return dispatch

    def parse_result(self, raw: dict) -> WorkerResult:
        """Parse a lipsync worker response into a WorkerResult."""
        return WorkerResult.model_validate(raw)