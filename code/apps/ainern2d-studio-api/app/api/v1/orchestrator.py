from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from uuid import uuid4

from ainern2d_shared.queue.topics import SYSTEM_TOPICS
from ainern2d_shared.schemas.events import EventEnvelope
from ainern2d_shared.config.setting import settings
from ainern2d_shared.queue.rabbitmq import RabbitMQConsumer

from app.api.deps import get_store, publish
from ainern2d_shared.telemetry.logging import get_logger

router = APIRouter(prefix="/internal/orchestrator", tags=["orchestrator"])


_logger = get_logger("orchestrator")


def _append_event(run_id: str | None, event_payload: dict) -> None:
    if not run_id:
        return
    store = get_store()
    store.events.setdefault(run_id, []).append(event_payload)


def handle_task_submitted(payload: dict) -> None:
    event = EventEnvelope.model_validate(payload)
    run_id = event.run_id
    if not run_id:
        return

    store = get_store()
    run = store.runs.get(run_id)
    if run is None:
        return

    run["status"] = "running"
    run["stage"] = "dispatched"
    run["updated_at"] = datetime.now(timezone.utc)
    _append_event(run_id, event.model_dump(mode="json"))

    dispatch_event = EventEnvelope(
        event_type="job.created",
        producer="orchestrator",
        occurred_at=datetime.now(timezone.utc),
        tenant_id=event.tenant_id,
        project_id=event.project_id,
        idempotency_key=event.idempotency_key,
        run_id=run_id,
        job_id=f"job_{uuid4().hex}",
        trace_id=event.trace_id,
        correlation_id=event.correlation_id,
        payload={
            "worker_type": "worker-video",
            "timeout_ms": 60000,
            "fallback_chain": ["worker-llm", "worker-audio"],
            "chapter_id": event.payload.get("chapter_id"),
            "requested_quality": event.payload.get("requested_quality"),
            "language_context": event.payload.get("language_context"),
        },
    )
    publish(SYSTEM_TOPICS.JOB_DISPATCH, dispatch_event.model_dump(mode="json"))
    _append_event(run_id, dispatch_event.model_dump(mode="json"))


def handle_job_status(payload: dict) -> None:
    event = EventEnvelope.model_validate(payload)
    run_id = event.run_id
    store = get_store()
    run = store.runs.get(run_id) if run_id else None
    if run is not None:
        run["updated_at"] = datetime.now(timezone.utc)
        if event.event_type == "job.claimed":
            run["status"] = "running"
            run["stage"] = "worker_running"
            run["progress"] = max(run["progress"], 15.0)
        elif event.event_type == "job.succeeded":
            run["status"] = "running"
            run["stage"] = "worker_succeeded"
            run["progress"] = max(run["progress"], 70.0)
            compose_event = EventEnvelope(
                event_type="compose.started",
                producer="orchestrator",
                occurred_at=datetime.now(timezone.utc),
                tenant_id=event.tenant_id,
                project_id=event.project_id,
                idempotency_key=event.idempotency_key,
                run_id=event.run_id,
                trace_id=event.trace_id,
                correlation_id=event.correlation_id,
                payload={
                    "timeline_final": {"tracks": []},
                    "artifact_refs": [event.payload.get("artifact_uri")],
                },
            )
            publish(SYSTEM_TOPICS.COMPOSE_DISPATCH, compose_event.model_dump(mode="json"))
            _append_event(run_id, compose_event.model_dump(mode="json"))
        elif event.event_type == "job.failed":
            run["status"] = "failed"
            run["stage"] = "failed"
            run["latest_error"] = {
                "error_code": event.payload.get("error_code", "WORKER-EXEC-002"),
                "message": event.payload.get("error_message", "job failed"),
                "retryable": bool(event.payload.get("retryable", False)),
            }

    _append_event(run_id, event.model_dump(mode="json"))


def handle_compose_status(payload: dict) -> None:
    event = EventEnvelope.model_validate(payload)
    run_id = event.run_id
    store = get_store()
    run = store.runs.get(run_id) if run_id else None
    if run is not None:
        run["updated_at"] = datetime.now(timezone.utc)
        if event.event_type == "compose.completed":
            run["status"] = "succeeded"
            run["stage"] = "completed"
            run["progress"] = 100.0
            run["final_artifact_uri"] = event.payload.get("artifact_uri")
        elif event.event_type == "compose.failed":
            run["status"] = "failed"
            run["stage"] = "compose_failed"
            run["latest_error"] = {
                "error_code": event.payload.get("error_code", "COMPOSE-FFMPEG-001"),
                "message": event.payload.get("error_message", "compose failed"),
                "retryable": bool(event.payload.get("retryable", False)),
            }

    _append_event(run_id, event.model_dump(mode="json"))


def consume_orchestrator_topic(topic: str) -> None:
    consumer = RabbitMQConsumer(settings.rabbitmq_url)
    if topic == SYSTEM_TOPICS.TASK_SUBMITTED:
        consumer.consume(topic, handle_task_submitted)
    elif topic == SYSTEM_TOPICS.JOB_STATUS:
        consumer.consume(topic, handle_job_status)
    elif topic == SYSTEM_TOPICS.COMPOSE_STATUS:
        consumer.consume(topic, handle_compose_status)
@router.post("/events", status_code=202)
def ingest_event(event: EventEnvelope) -> dict[str, str]:
    store = get_store()
    run_id = event.run_id
    if run_id:
        store.events.setdefault(run_id, []).append(event.model_dump(mode="json"))

    run = store.runs.get(run_id) if run_id else None
    if event.event_type in {"job.claimed", "job.succeeded", "job.failed"}:
        handle_job_status(event.model_dump(mode="json"))
    elif event.event_type in {"compose.completed", "compose.failed"}:
        handle_compose_status(event.model_dump(mode="json"))
    elif event.event_type == "task.submitted":
        handle_task_submitted(event.model_dump(mode="json"))
    else:
        _logger.info("ignore event_type={} in sync endpoint", event.event_type)
    if run_id:
        stage_event = EventEnvelope(
            event_type="run.stage.changed",
            producer="orchestrator",
            occurred_at=datetime.now(timezone.utc),
            tenant_id=event.tenant_id,
            project_id=event.project_id,
            idempotency_key=event.idempotency_key,
            run_id=run_id,
            trace_id=event.trace_id,
            correlation_id=event.correlation_id,
            payload={"from_event": event.event_type},
        )
        store.events.setdefault(run_id, []).append(stage_event.model_dump(mode="json"))
        publish(SYSTEM_TOPICS.JOB_STATUS, stage_event.model_dump(mode="json"))

    return {"status": "accepted"}
