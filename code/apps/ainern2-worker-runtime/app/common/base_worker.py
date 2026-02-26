"""Abstract base worker for all worker-runtime implementations."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone

from ainern2d_shared.config.setting import settings
from ainern2d_shared.queue.rabbitmq import RabbitMQPublisher
from ainern2d_shared.queue.topics import SYSTEM_TOPICS
from ainern2d_shared.schemas.events import EventEnvelope
from ainern2d_shared.schemas.worker import WorkerResult
from ainern2d_shared.telemetry.logging import get_logger

logger = get_logger(__name__)


class BaseWorker(ABC):
    """Abstract base class every concrete worker must extend."""

    def __init__(self, worker_type: str, settings=settings) -> None:
        self.worker_type = worker_type
        self.settings = settings
        self._publisher = RabbitMQPublisher(settings)

    # ------------------------------------------------------------------
    # Abstract – each worker implements its own execution logic
    # ------------------------------------------------------------------
    @abstractmethod
    async def execute(self, job_payload: dict) -> WorkerResult:
        """Run the worker-specific task and return a result."""
        ...

    # ------------------------------------------------------------------
    # Result / heartbeat reporting
    # ------------------------------------------------------------------
    async def report_result(self, result: WorkerResult) -> None:
        """Publish a worker callback result to the hub."""
        envelope = self._build_envelope(
            event_type="worker.callback",
            job_id=result.job_id,
            run_id=result.run_id,
            result_payload=result.model_dump(),
        )
        await self._publisher.publish(SYSTEM_TOPICS.WORKER_CALLBACK, envelope.model_dump())
        logger.info("reported result for job %s", result.job_id)

    async def report_heartbeat(self, job_id: str) -> None:
        """Publish a lightweight heartbeat event for the running job."""
        envelope = self._build_envelope(
            event_type="worker.heartbeat",
            job_id=job_id,
            run_id=None,
            result_payload={"worker_type": self.worker_type},
        )
        await self._publisher.publish(SYSTEM_TOPICS.WORKER_CALLBACK, envelope.model_dump())

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _build_envelope(
        self,
        event_type: str,
        job_id: str,
        run_id: str | None,
        result_payload: dict,
    ) -> EventEnvelope:
        return EventEnvelope(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            job_id=job_id,
            run_id=run_id,
            payload=result_payload,
            timestamp=datetime.now(timezone.utc).isoformat(),
            source=self.worker_type,
        )