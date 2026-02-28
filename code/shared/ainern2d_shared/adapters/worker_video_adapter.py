"""Video worker adapter – format dispatch and parse results for worker-video."""

from __future__ import annotations

from typing import Any

from ainern2d_shared.ainer_db_models.pipeline_models import Job
from ainern2d_shared.ainer_db_models.provider_models import ProviderAdapter
from ainern2d_shared.schemas.worker import WorkerResult
from ainern2d_shared.telemetry.logging import get_logger

from .base_adapter import apply_adapter_mapping

logger = get_logger(__name__)

_VIDEO_DEFAULTS: dict[str, Any] = {
    "resolution": "1280x720",
    "fps": 24,
    "codec": "libx264",
    "format": "mp4",
}


class VideoWorkerAdapter:
    """Thin adapter for worker-video dispatch and result parsing."""

    def format_dispatch(self, job: Job, adapter: ProviderAdapter | None = None) -> dict:
        """Extract video-specific fields from job payload and apply HTTP spec."""
        payload: dict = job.payload_json or {}
        
        canonical = {
            "job_id": str(job.id),
            "run_id": str(job.run_id) if job.run_id else None,
            "prompt": payload.get("prompt", ""),
            "resolution": payload.get("resolution", _VIDEO_DEFAULTS["resolution"]),
            "fps": payload.get("fps", _VIDEO_DEFAULTS["fps"]),
            "codec": payload.get("codec", _VIDEO_DEFAULTS["codec"]),
            "format": payload.get("format", _VIDEO_DEFAULTS["format"]),
            "duration_ms": payload.get("duration_ms", 5000),
            "style_tags": payload.get("style_tags", []),
            "seed": payload.get("seed"),
        }
        
        if adapter:
            http_dispatch = apply_adapter_mapping(canonical, adapter)
            canonical.update(http_dispatch)
            
        logger.debug("video dispatch: job=%s res=%s", job.id, canonical["resolution"])
        return canonical

    def parse_result(self, raw: dict) -> WorkerResult:
        """Parse a video worker response into a WorkerResult."""
        return WorkerResult.model_validate(raw)