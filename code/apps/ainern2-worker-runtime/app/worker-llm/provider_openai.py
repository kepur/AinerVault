"""OpenAI LLM provider worker."""

from __future__ import annotations

from ainern2d_shared.schemas.worker import WorkerResult
from ainern2d_shared.telemetry.logging import get_logger

from app.common.base_worker import BaseWorker

logger = get_logger(__name__)


class OpenAIProvider(BaseWorker):
    """Call OpenAI chat-completion API and return structured result."""

    def __init__(self, **kwargs) -> None:
        super().__init__(worker_type="worker-llm-openai", **kwargs)

    async def execute(self, job_payload: dict) -> WorkerResult:
        job_id: str = job_payload.get("job_id", "")
        run_id: str = job_payload.get("run_id", "")
        try:
            prompt: str = job_payload["prompt"]
            model_id: str = job_payload.get("model_id", "gpt-4o")
            max_tokens: int = job_payload.get("max_tokens", 2048)
            temperature: float = job_payload.get("temperature", 0.7)
            system_prompt: str = job_payload.get("system_prompt", "")

            # TODO: call real OpenAI API via openai SDK
            logger.info(
                "job %s: calling OpenAI model=%s max_tokens=%d",
                job_id,
                model_id,
                max_tokens,
            )

            # Stub: simulated response
            output_text = f"[OpenAI stub] model={model_id}, prompt_len={len(prompt)}"
            token_usage = {
                "prompt_tokens": len(prompt) // 4,
                "completion_tokens": len(output_text) // 4,
                "total_tokens": (len(prompt) + len(output_text)) // 4,
            }

            return WorkerResult(
                job_id=job_id,
                run_id=run_id,
                status="success",
                output={
                    "output_text": output_text,
                    "token_usage": token_usage,
                    "cost_estimate": 0.0,
                    "model_id": model_id,
                },
            )
        except Exception as exc:
            logger.exception("OpenAIProvider failed for job %s", job_id)
            return WorkerResult(
                job_id=job_id,
                run_id=run_id,
                status="error",
                error_code="OPENAI_EXECUTION_ERROR",
                error_message=str(exc),
            )
