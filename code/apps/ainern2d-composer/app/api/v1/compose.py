from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter

from ainern2d_shared.config.setting import settings
from ainern2d_shared.queue.rabbitmq import RabbitMQConsumer, RabbitMQPublisher
from ainern2d_shared.queue.topics import SYSTEM_TOPICS
from ainern2d_shared.schemas.events import EventEnvelope
from ainern2d_shared.schemas.task import ComposeRequest
from ainern2d_shared.telemetry.logging import get_logger

router = APIRouter(prefix="/internal", tags=["composer"])

COMPOSE_JOBS: dict[str, dict[str, object]] = {}
_logger = get_logger("composer")


@router.post("/compose", status_code=202)
def compose(request: ComposeRequest) -> dict[str, str]:
    compose_job_id = f"compose_{uuid4().hex}"
    now = datetime.now(timezone.utc)

    started = EventEnvelope(
        event_type="compose.started",
        producer="composer",
        occurred_at=now,
        tenant_id=request.tenant_id,
        project_id=request.project_id,
        idempotency_key=request.idempotency_key,
        run_id=request.run_id,
        trace_id=request.trace_id,
        correlation_id=request.correlation_id,
        payload={"compose_job_id": compose_job_id},
    )

    COMPOSE_JOBS[compose_job_id] = {
        "compose_job_id": compose_job_id,
        "run_id": request.run_id,
        "status": "started",
        "started_event": started.model_dump(mode="json"),
        "created_at": now,
    }

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

    COMPOSE_JOBS[compose_job_id]["status"] = "completed"
    COMPOSE_JOBS[compose_job_id]["completed_event"] = completed.model_dump(mode="json")
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
    compose(compose_request)


def consume_compose_dispatch() -> None:
    consumer = RabbitMQConsumer(settings.rabbitmq_url)
    consumer.consume(SYSTEM_TOPICS.COMPOSE_DISPATCH, handle_compose_dispatch)
