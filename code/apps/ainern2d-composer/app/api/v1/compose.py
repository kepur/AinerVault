from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.enum_models import JobStatus, JobType, RenderStage
from ainern2d_shared.ainer_db_models.pipeline_models import Job
from ainern2d_shared.config.setting import settings
from ainern2d_shared.db.session import SessionLocal, get_db
from ainern2d_shared.db.repositories.pipeline import JobRepository
from ainern2d_shared.queue.rabbitmq import RabbitMQConsumer, RabbitMQPublisher
from ainern2d_shared.queue.topics import SYSTEM_TOPICS
from ainern2d_shared.schemas.events import EventEnvelope
from ainern2d_shared.schemas.task import ComposeRequest
from ainern2d_shared.telemetry.logging import get_logger

router = APIRouter(prefix="/internal", tags=["composer"])

_logger = get_logger("composer")


@router.post("/compose", status_code=202)
def compose(request: ComposeRequest, db: Session = Depends(get_db)) -> dict[str, str]:
    compose_job_id = f"compose_{uuid4().hex}"
    now = datetime.now(timezone.utc)

    job = Job(
        id=compose_job_id,
        tenant_id=request.tenant_id,
        project_id=request.project_id,
        trace_id=request.trace_id,
        correlation_id=request.correlation_id,
        idempotency_key=request.idempotency_key,
        run_id=request.run_id,
        job_type=JobType.compose_final,
        stage=RenderStage.compose,
        status=JobStatus.running,
        priority=0,
        payload_json={"timeline_final": request.timeline_final, "artifact_refs": request.artifact_refs},
    )
    job_repo = JobRepository(db)
    job_repo.create(job)

    # Mock: auto-complete for dev
    completed = EventEnvelope(
        event_type="compose.completed",
        producer="composer",
        occurred_at=datetime.now(timezone.utc),
        tenant_id=request.tenant_id,
        project_id=request.project_id,
        idempotency_key=request.idempotency_key,
        run_id=request.run_id,
        trace_id=request.trace_id,
        correlation_id=request.correlation_id,
        payload={
            "compose_job_id": compose_job_id,
            "artifact_uri": f"s3://ainer-artifacts/{request.run_id}/final.mp4",
        },
    )
    try:
        publisher = RabbitMQPublisher(settings.rabbitmq_url)
        publisher.publish(SYSTEM_TOPICS.COMPOSE_STATUS, completed.model_dump(mode="json"))
        publisher.close()
    except Exception as exc:
        _logger.warning("publish compose.status failed reason={}", str(exc))

    job.status = JobStatus.success
    job.result_json = completed.payload
    db.commit()

    return {"compose_job_id": compose_job_id, "status": "started"}


def handle_compose_dispatch(payload: dict) -> None:
    event = EventEnvelope.model_validate(payload)
    if event.event_type != "compose.started":
        return

    compose_request = ComposeRequest(
        run_id=event.run_id or f"run_{uuid4().hex}",
        timeline_final=event.payload.get("timeline_final", {"tracks": []}),
        artifact_refs=[ref for ref in event.payload.get("artifact_refs", []) if ref],
        tenant_id=event.tenant_id,
        project_id=event.project_id,
        trace_id=event.trace_id,
        correlation_id=event.correlation_id,
        idempotency_key=event.idempotency_key,
    )

    db = SessionLocal()
    try:
        compose(compose_request, db=db)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def consume_compose_dispatch() -> None:
    consumer = RabbitMQConsumer(settings.rabbitmq_url)
    consumer.consume(SYSTEM_TOPICS.COMPOSE_DISPATCH, handle_compose_dispatch)
