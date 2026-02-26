"""LLM worker adapter – format dispatch and parse results for worker-llm."""

from __future__ import annotations

from typing import Any

from ainern2d_shared.ainer_db_models.pipeline_models import Job
from ainern2d_shared.schemas.worker import WorkerResult
from ainern2d_shared.telemetry.logging import get_logger

logger = get_logger(__name__)

_LLM_DEFAULTS: dict[str, Any] = {
    "model_profile": "gpt-4o",
    "max_tokens": 4096,
    "temperature": 0.7,
}


class LLMWorkerAdapter:
    """Thin adapter for worker-llm dispatch and result parsing."""

    def format_dispatch(self, job: Job) -> dict:
        """Extract LLM-specific fields from job payload with defaults."""
        payload: dict = job.payload_json or {}
        dispatch = {
            "job_id": str(job.id),
            "run_id": str(job.run_id) if job.run_id else None,
            "prompt": payload.get("prompt", ""),
            "system_prompt": payload.get("system_prompt"),
            "model_profile": payload.get("model_profile", _LLM_DEFAULTS["model_profile"]),
            "max_tokens": payload.get("max_tokens", _LLM_DEFAULTS["max_tokens"]),
            "temperature": payload.get("temperature", _LLM_DEFAULTS["temperature"]),
            "response_format": payload.get("response_format"),
            "tools": payload.get("tools"),
        }
        logger.debug("llm dispatch: job=%s model=%s", job.id, dispatch["model_profile"])
        return dispatch

    def parse_result(self, raw: dict) -> WorkerResult:
        """Parse an LLM worker response into a WorkerResult."""
        return WorkerResult.model_validate(raw)