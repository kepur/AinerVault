"""LLM worker adapter – format dispatch and parse results for worker-llm."""

from __future__ import annotations

from typing import Any

from ainern2d_shared.ainer_db_models.pipeline_models import Job
from ainern2d_shared.ainer_db_models.provider_models import ProviderAdapter
from ainern2d_shared.schemas.worker import WorkerResult
from ainern2d_shared.telemetry.logging import get_logger

from .base_adapter import apply_adapter_mapping

logger = get_logger(__name__)

_LLM_DEFAULTS: dict[str, Any] = {
    "model_profile": "gpt-4o",
    "max_tokens": 4096,
    "temperature": 0.7,
}


class LLMWorkerAdapter:
    """Thin adapter for worker-llm dispatch mapping."""

    def format_dispatch(self, job: Job, adapter: ProviderAdapter | None = None) -> dict:
        """Extract LLM-specific fields from job payload and apply HTTP spec."""
        payload: dict = job.payload_json or {}
        
        # 1. Base canonical inputs
        canonical = {
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
        
        if adapter:
            # 2. If provider adapter spec is present, compile HTTP dispatch
            http_dispatch = apply_adapter_mapping(canonical, adapter)
            # Combine canonical with generic runner instructions
            canonical.update(http_dispatch)
            
        logger.debug("llm dispatch: job=%s model=%s adapter=%s", job.id, canonical["model_profile"], bool(adapter))
        return canonical

    def parse_result(self, raw: dict) -> WorkerResult:
        """Parse an LLM worker response into a WorkerResult."""
        return WorkerResult.model_validate(raw)