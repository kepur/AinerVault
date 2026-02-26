"""OpenAI LLM provider worker."""

from __future__ import annotations

import time

from ainern2d_shared.schemas.worker import WorkerResult
from ainern2d_shared.telemetry.logging import get_logger

from app.common.base_worker import BaseWorker

logger = get_logger(__name__)

# Token cost table (USD per 1K tokens) — kept outside class for easy updates
_COST_TABLE: dict[str, tuple[float, float]] = {
    "gpt-4o":            (0.005,  0.015),
    "gpt-4o-mini":       (0.00015, 0.0006),
    "gpt-4-turbo":       (0.01,   0.03),
    "gpt-3.5-turbo":     (0.0005, 0.0015),
}
_DEFAULT_COST = (0.005, 0.015)


class OpenAIProvider(BaseWorker):
    """Call OpenAI chat-completion API and return structured result."""

    def __init__(self, **kwargs) -> None:
        super().__init__(worker_type="worker-llm-openai", **kwargs)

    async def execute(self, job_payload: dict) -> WorkerResult:
        job_id: str = job_payload.get("job_id", "")
        run_id: str = job_payload.get("run_id", "")
        try:
            prompt: str = job_payload["prompt"]
            model_id: str = job_payload.get("model_id", "gpt-4o-mini")
            max_tokens: int = job_payload.get("max_tokens", 2048)
            temperature: float = job_payload.get("temperature", 0.7)
            system_prompt: str = job_payload.get("system_prompt", "You are a helpful assistant.")
            rag_fragments: list[str] = job_payload.get("rag_fragments", [])

            # Import lazily so the worker still runs even without the SDK
            try:
                from openai import AsyncOpenAI
            except ImportError:
                raise RuntimeError("openai SDK not installed; run: pip install openai")

            api_key: str = self.settings.openai_api_key
            if not api_key:
                raise RuntimeError("OPENAI_API_KEY environment variable is not set")

            client = AsyncOpenAI(
                api_key=api_key,
                base_url=self.settings.openai_base_url,
            )

            messages: list[dict] = [{"role": "system", "content": system_prompt}]
            if rag_fragments:
                context = "\n---\n".join(rag_fragments)
                messages.append({"role": "user", "content": f"Context:\n{context}\n\nTask:\n{prompt}"})
            else:
                messages.append({"role": "user", "content": prompt})

            logger.info(
                "job %s: calling OpenAI model=%s max_tokens=%d",
                job_id, model_id, max_tokens,
            )

            t0 = time.monotonic()
            response = await client.chat.completions.create(
                model=model_id,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            latency_ms = int((time.monotonic() - t0) * 1000)

            output_text = response.choices[0].message.content or ""
            usage = response.usage
            prompt_tokens = usage.prompt_tokens if usage else 0
            completion_tokens = usage.completion_tokens if usage else 0
            total_tokens = usage.total_tokens if usage else 0

            in_cost, out_cost = _COST_TABLE.get(model_id, _DEFAULT_COST)
            cost_estimate = (prompt_tokens / 1000 * in_cost) + (completion_tokens / 1000 * out_cost)

            logger.info(
                "job %s: OpenAI done tokens=%d latency=%dms cost=$%.6f",
                job_id, total_tokens, latency_ms, cost_estimate,
            )

            return WorkerResult(
                job_id=job_id,
                run_id=run_id,
                status="success",
                output={
                    "output_text": output_text,
                    "token_usage": {
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": total_tokens,
                    },
                    "cost_estimate": cost_estimate,
                    "latency_ms": latency_ms,
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
