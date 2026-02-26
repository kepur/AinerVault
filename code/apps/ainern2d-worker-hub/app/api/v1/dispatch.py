from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends
from pydantic import Field
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.enum_models import JobStatus, JobType, RenderStage
from ainern2d_shared.ainer_db_models.pipeline_models import Job
from ainern2d_shared.config.setting import settings
from ainern2d_shared.db.session import SessionLocal, get_db
from ainern2d_shared.db.repositories.pipeline import JobRepository
from ainern2d_shared.queue.rabbitmq import RabbitMQConsumer, RabbitMQPublisher
from ainern2d_shared.queue.topics import SYSTEM_TOPICS
from ainern2d_shared.schemas.base import BaseSchema
from ainern2d_shared.schemas.events import EventEnvelope
from ainern2d_shared.telemetry.logging import get_logger

router = APIRouter(prefix="/internal", tags=["worker-hub"])

_logger = get_logger("worker-hub")


class DispatchRequest(BaseSchema):
    tenant_id: str
    project_id: str
    trace_id: str
    correlation_id: str
    idempotency_key: str
    run_id: str
    job_id: str
    worker_type: str
    payload: dict[str, object] = Field(default_factory=dict)
    timeout_ms: int = 60000
    fallback_chain: list[str] = Field(default_factory=list)


class DispatchResponse(BaseSchema):
    job_id: str
    status: str


def _publish_status(event: EventEnvelope) -> None:
    try:
        publisher = RabbitMQPublisher(settings.rabbitmq_url)
        publisher.publish(SYSTEM_TOPICS.JOB_STATUS, event.model_dump(mode="json"))
        publisher.close()
    except Exception as exc:
        _logger.warning("publish job.status failed reason={}", str(exc))


def handle_job_dispatch(payload: dict) -> None:
    event = EventEnvelope.model_validate(payload)
    if event.event_type != "job.created":
        return

    job_id = event.job_id or f"job_{uuid4().hex}"
    now = datetime.now(timezone.utc)
    worker_type = str(event.payload.get("worker_type", "worker-video"))

    db = SessionLocal()
    try:
        job = Job(
            id=job_id,
            tenant_id=event.tenant_id,
            project_id=event.project_id,
            trace_id=event.trace_id,
            correlation_id=event.correlation_id,
            idempotency_key=event.idempotency_key,
            run_id=event.run_id,
            job_type=JobType.render_video,
            stage=RenderStage.execute,
            status=JobStatus.running,
            priority=0,
            payload_json=event.payload,
            locked_by=f"hub-{uuid4().hex[:8]}",
            locked_at=now,
        )
        job_repo = JobRepository(db)
        job_repo.create(job)

        claimed_event = EventEnvelope(
            event_type="job.claimed",
            producer="worker-hub",
            occurred_at=now,
            tenant_id=event.tenant_id,
            project_id=event.project_id,
            idempotency_key=event.idempotency_key,
            run_id=event.run_id,
            job_id=job_id,
            trace_id=event.trace_id,
            correlation_id=event.correlation_id,
            payload={"worker_type": worker_type, "queue_status": "claimed"},
        )
        _publish_status(claimed_event)

        # Mock: auto-succeed for dev
        succeeded_event = EventEnvelope(
            event_type="job.succeeded",
            producer="worker-hub",
            occurred_at=datetime.now(timezone.utc),
            tenant_id=event.tenant_id,
            project_id=event.project_id,
            idempotency_key=event.idempotency_key,
            run_id=event.run_id,
            job_id=job_id,
            trace_id=event.trace_id,
            correlation_id=event.correlation_id,
            payload={
                "worker_type": worker_type,
                "artifact_uri": f"s3://ainer-artifacts/{event.run_id}/{job_id}.mp4",
            },
        )
        _publish_status(succeeded_event)

        job.status = JobStatus.success
        job.result_json = succeeded_event.payload
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def consume_dispatch_topic() -> None:
    consumer = RabbitMQConsumer(settings.rabbitmq_url)
    consumer.consume(SYSTEM_TOPICS.JOB_DISPATCH, handle_job_dispatch)


@router.post("/dispatch", response_model=DispatchResponse, status_code=202)
def dispatch(body: DispatchRequest, db: Session = Depends(get_db)) -> DispatchResponse:
    now = datetime.now(timezone.utc)
    job = Job(
        id=body.job_id,
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        trace_id=body.trace_id,
        correlation_id=body.correlation_id,
        idempotency_key=body.idempotency_key,
        run_id=body.run_id,
        job_type=JobType.render_video,
        stage=RenderStage.execute,
        status=JobStatus.enqueued,
        priority=0,
        payload_json=body.payload,
    )
    job_repo = JobRepository(db)
    job_repo.create(job)
    db.commit()

    return DispatchResponse(job_id=body.job_id, status="enqueued")
