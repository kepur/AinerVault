"""Audio worker adapter – format dispatch and parse results for worker-audio."""

from __future__ import annotations

from typing import Any

from ainern2d_shared.ainer_db_models.pipeline_models import Job
from ainern2d_shared.ainer_db_models.provider_models import ProviderAdapter
from ainern2d_shared.schemas.worker import WorkerResult
from ainern2d_shared.telemetry.logging import get_logger

from .base_adapter import apply_adapter_mapping

logger = get_logger(__name__)

_AUDIO_DEFAULTS: dict[str, Any] = {
    "voice_id": "default",
    "language": "zh-CN",
    "format": "wav",
    "sample_rate": 44100,
}


class AudioWorkerAdapter:
    """Thin adapter for worker-audio dispatch and result parsing."""

    def format_dispatch(self, job: Job, adapter: ProviderAdapter | None = None) -> dict:
        """Extract audio-specific fields from job payload and apply HTTP spec."""
        payload: dict = job.payload_json or {}
        
        canonical = {
            "job_id": str(job.id),
            "run_id": str(job.run_id) if job.run_id else None,
            "voice_id": payload.get("voice_id", _AUDIO_DEFAULTS["voice_id"]),
            "text": payload.get("text", ""),
            "language": payload.get("language", _AUDIO_DEFAULTS["language"]),
            "format": payload.get("format", _AUDIO_DEFAULTS["format"]),
            "sample_rate": payload.get("sample_rate", _AUDIO_DEFAULTS["sample_rate"]),
            "speed": payload.get("speed", 1.0),
            "emotion": payload.get("emotion"),
        }
        
        if adapter:
            http_dispatch = apply_adapter_mapping(canonical, adapter)
            canonical.update(http_dispatch)
            
        logger.debug("audio dispatch: job=%s voice=%s", job.id, canonical["voice_id"])
        return canonical

    def parse_result(self, raw: dict) -> WorkerResult:
        """Parse an audio worker response into a WorkerResult."""
        return WorkerResult.model_validate(raw)