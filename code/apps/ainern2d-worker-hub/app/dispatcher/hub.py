"""Central dispatch hub – routes jobs to worker nodes and handles callbacks."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.enum_models import JobStatus
from ainern2d_shared.ainer_db_models.pipeline_models import Job
from ainern2d_shared.db.repositories.pipeline import JobRepository
from ainern2d_shared.queue.rabbitmq import RabbitMQPublisher
from ainern2d_shared.queue.topics import SYSTEM_TOPICS
from ainern2d_shared.schemas.events import EventEnvelope
from ainern2d_shared.schemas.worker import WorkerResult
from ainern2d_shared.config.setting import settings
from ainern2d_shared.telemetry.logging import get_logger

from .node_registry import NodeRegistry
from .routing_table import RoutingTable

logger = get_logger(__name__)


class DispatchHub:
    """Orchestrates job dispatch and worker callback handling."""

    def __init__(
        self,
        db: Session,
        node_registry: NodeRegistry,
        routing_table: RoutingTable,
    ) -> None:
        self.db = db
        self.node_registry = node_registry
        self.routing_table = routing_table
        self._publisher = RabbitMQPublisher(settings.rabbitmq_url)
        self._job_repo = JobRepository(db)

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------
    async def dispatch(self, job: Job) -> str:
        """Resolve a worker, claim the job, publish the dispatch event.

        Returns the *node_id* that was assigned.  If no node is available the
        job is set back to ``queued`` and a ``ValueError`` is raised.
        """
        worker_type = self.routing_table.resolve(job.job_type)
        available = self.node_registry.get_available(worker_type)

        if not available:
            self._job_repo.update_status(job.id, JobStatus.queued)
            logger.warning("no available node for %s – job %s re-queued", worker_type, job.id)
            raise ValueError(f"no available node for worker_type={worker_type}")

        # Pick the node with the lowest current load
        node = min(available, key=lambda n: n["current_load"])
        node_id: str = node["node_id"]

        self._job_repo.update_status(job.id, JobStatus.claimed)

        envelope = EventEnvelope(
            event_id=str(uuid.uuid4()),
            event_type="job.claimed",
            producer="worker-hub",
            occurred_at=datetime.now(timezone.utc),
            tenant_id=job.tenant_id or "t_unknown",
            project_id=job.project_id or "p_unknown",
            idempotency_key=job.idempotency_key or f"idem_{job.id}",
            run_id=str(job.run_id) if job.run_id else None,
            job_id=str(job.id),
            trace_id=(getattr(job, "trace_id", "") or f"tr_{job.id}"),
            correlation_id=(getattr(job, "correlation_id", "") or f"cr_{job.id}"),
            payload={"node_id": node_id, "worker_type": worker_type},
        )
        self._publisher.publish(SYSTEM_TOPICS.JOB_STATUS, envelope.model_dump(mode="json"))
        logger.info("dispatched job %s to node %s", job.id, node_id)
        return node_id

    # ------------------------------------------------------------------
    # Callback handling
    # ------------------------------------------------------------------
    async def handle_callback(self, result: WorkerResult) -> None:
        """Process a worker result – update DB status and publish event."""
        job = self._job_repo.get(result.job_id)
        if job is None:
            logger.warning("callback ignored: job %s not found", result.job_id)
            return

        if result.status == "succeeded":
            self._job_repo.update_status(result.job_id, JobStatus.succeeded)
            event_type = "job.succeeded"
        else:
            self._job_repo.update_status(result.job_id, JobStatus.failed)
            event_type = "job.failed"

        envelope = EventEnvelope(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            producer="worker-hub",
            occurred_at=datetime.now(timezone.utc),
            tenant_id=job.tenant_id or "t_unknown",
            project_id=job.project_id or "p_unknown",
            idempotency_key=job.idempotency_key or f"idem_{job.id}:{event_type}",
            trace_id=(getattr(job, "trace_id", "") or f"tr_{job.id}"),
            correlation_id=(getattr(job, "correlation_id", "") or f"cr_{job.id}"),
            job_id=result.job_id,
            run_id=result.run_id,
            payload=result.model_dump(mode="json"),
        )
        self._publisher.publish(SYSTEM_TOPICS.JOB_STATUS, envelope.model_dump(mode="json"))
        logger.info("handled callback for job %s: %s", result.job_id, event_type)
