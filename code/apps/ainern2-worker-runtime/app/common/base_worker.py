"""Abstract base worker for all worker-runtime implementations."""

from __future__ import annotations

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
        self._publisher = RabbitMQPublisher(settings.rabbitmq_url)

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
        """Publish a worker result payload to the hub callback stream."""
        self._publisher.publish(
            SYSTEM_TOPICS.WORKER_DETAIL,
            result.model_dump(mode="json"),
        )
        logger.info("reported result for job %s", result.job_id)

    async def report_heartbeat(self, job_id: str) -> None:
        """Publish a lightweight job heartbeat event."""
        now = datetime.now(timezone.utc)
        envelope = EventEnvelope(
            event_type="job.heartbeat",
            producer=self.worker_type,
            occurred_at=now,
            tenant_id="t_unknown",
            project_id="p_unknown",
            idempotency_key=f"idem_hb_{job_id}",
            run_id=None,
            job_id=job_id,
            trace_id=f"tr_{job_id}",
            correlation_id=f"cr_{job_id}",
            payload={"worker_type": self.worker_type},
        )
        self._publisher.publish(SYSTEM_TOPICS.JOB_STATUS, envelope.model_dump(mode="json"))
