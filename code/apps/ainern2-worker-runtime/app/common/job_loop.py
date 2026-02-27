"""Worker job consumption loop – pulls jobs from RabbitMQ and delegates to a BaseWorker."""

from __future__ import annotations

import asyncio
import traceback

from ainern2d_shared.config.setting import settings
from ainern2d_shared.queue.rabbitmq import RabbitMQConsumer
from ainern2d_shared.queue.topics import SYSTEM_TOPICS
from ainern2d_shared.schemas.worker import WorkerResult
from ainern2d_shared.telemetry.logging import get_logger

from .base_worker import BaseWorker

logger = get_logger(__name__)


class JobLoop:
    """Consumes dispatched jobs and delegates execution to a concrete worker."""

    def __init__(self, worker: BaseWorker) -> None:
        self.worker = worker
        self._consumer = RabbitMQConsumer(settings.rabbitmq_url)

    def start(self) -> None:
        """Begin consuming from the JOB_DISPATCH topic, filtering by worker_type."""
        logger.info("JobLoop starting for worker_type=%s", self.worker.worker_type)
        self._consumer.consume(
            topic=SYSTEM_TOPICS.JOB_DISPATCH,
            handler=self._on_message,
        )

    def _on_message(self, payload: dict) -> None:
        asyncio.run(self._handle_message(payload))

    async def _handle_message(self, payload: dict) -> None:
        """Deserialize an incoming job message, execute, and report the outcome."""
        job_id: str = payload.get("job_id", "unknown")
        run_id: str | None = payload.get("run_id")

        # Only process jobs targeted at this worker type
        if payload.get("worker_type") != self.worker.worker_type:
            return

        try:
            result: WorkerResult = await self.worker.execute(payload)
            await self.worker.report_result(result)
            logger.info("job %s succeeded", job_id)
        except Exception as exc:
            logger.error("job %s failed: %s", job_id, exc)
            error_result = WorkerResult(
                job_id=job_id,
                run_id=run_id,
                status="failed",
                error_code=type(exc).__name__,
                error_message=str(exc),
                retryable=self._is_retryable(exc),
                traceback=traceback.format_exc(),
            )
            await self.worker.report_result(error_result)

    # ------------------------------------------------------------------
    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        """Heuristic: transient errors are retryable, value/type errors are not."""
        non_retryable = (ValueError, TypeError, KeyError, NotImplementedError)
        return not isinstance(exc, non_retryable)
