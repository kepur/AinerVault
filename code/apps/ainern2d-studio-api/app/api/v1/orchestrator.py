from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from uuid import uuid4

from ainern2d_shared.ainer_db_models.enum_models import RenderStage, RunStatus
from ainern2d_shared.ainer_db_models.pipeline_models import WorkflowEvent
from ainern2d_shared.db.repositories.pipeline import RenderRunRepository
from ainern2d_shared.queue.topics import SYSTEM_TOPICS
from ainern2d_shared.schemas.events import EventEnvelope
from ainern2d_shared.config.setting import settings
from ainern2d_shared.queue.rabbitmq import RabbitMQConsumer

from app.api.deps import get_db, get_db_session, publish
from ainern2d_shared.telemetry.logging import get_logger

router = APIRouter(prefix="/internal/orchestrator", tags=["orchestrator"])

_logger = get_logger("orchestrator")


def _persist_event(db: Session, event: EventEnvelope) -> None:
    """Save an EventEnvelope as a WorkflowEvent row."""
    wf = WorkflowEvent(
        id=event.event_id,
        tenant_id=event.tenant_id,
        project_id=event.project_id,
        trace_id=event.trace_id,
        correlation_id=event.correlation_id,
        idempotency_key=event.idempotency_key,
        run_id=event.run_id,
        event_type=event.event_type,
        event_version=event.event_version,
        producer=event.producer,
        occurred_at=event.occurred_at,
        payload_json=event.payload,
    )
    db.add(wf)


def handle_task_submitted(payload: dict) -> None:
    event = EventEnvelope.model_validate(payload)
    run_id = event.run_id
    if not run_id:
        return

    db = get_db_session()
    try:
        run_repo = RenderRunRepository(db)
        run = run_repo.get(run_id)
        if run is None:
            return

        run.status = RunStatus.running
        run.stage = RenderStage.route
        _persist_event(db, event)

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
        _persist_event(db, dispatch_event)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def handle_job_status(payload: dict) -> None:
    event = EventEnvelope.model_validate(payload)
    run_id = event.run_id

    db = get_db_session()
    try:
        run_repo = RenderRunRepository(db)
        run = run_repo.get(run_id) if run_id else None

        if run is not None:
            if event.event_type == "job.claimed":
                run.status = RunStatus.running
                run.stage = RenderStage.execute
                run.progress = max(run.progress, 15)
            elif event.event_type == "job.succeeded":
                run.status = RunStatus.running
                run.stage = RenderStage.compose
                run.progress = max(run.progress, 70)
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
                _persist_event(db, compose_event)
            elif event.event_type == "job.failed":
                run.status = RunStatus.failed
                run.stage = RenderStage.execute
                run.error_code = event.payload.get("error_code", "WORKER-EXEC-002")
                run.error_message = event.payload.get("error_message", "job failed")

        _persist_event(db, event)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def handle_compose_status(payload: dict) -> None:
    event = EventEnvelope.model_validate(payload)
    run_id = event.run_id

    db = get_db_session()
    try:
        run_repo = RenderRunRepository(db)
        run = run_repo.get(run_id) if run_id else None

        if run is not None:
            if event.event_type == "compose.completed":
                run.status = RunStatus.success
                run.stage = RenderStage.observe
                run.progress = 100
            elif event.event_type == "compose.failed":
                run.status = RunStatus.failed
                run.stage = RenderStage.compose
                run.error_code = event.payload.get("error_code", "COMPOSE-FFMPEG-001")
                run.error_message = event.payload.get("error_message", "compose failed")

        _persist_event(db, event)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def consume_orchestrator_topic(topic: str) -> None:
    consumer = RabbitMQConsumer(settings.rabbitmq_url)
    if topic == SYSTEM_TOPICS.TASK_SUBMITTED:
        consumer.consume(topic, handle_task_submitted)
    elif topic == SYSTEM_TOPICS.JOB_STATUS:
        consumer.consume(topic, handle_job_status)
    elif topic == SYSTEM_TOPICS.COMPOSE_STATUS:
        consumer.consume(topic, handle_compose_status)


@router.post("/events", status_code=202)
def ingest_event(event: EventEnvelope, db: Session = Depends(get_db)) -> dict[str, str]:
    _persist_event(db, event)

    if event.event_type in {"job.claimed", "job.succeeded", "job.failed"}:
        handle_job_status(event.model_dump(mode="json"))
    elif event.event_type in {"compose.completed", "compose.failed"}:
        handle_compose_status(event.model_dump(mode="json"))
    elif event.event_type == "task.submitted":
        handle_task_submitted(event.model_dump(mode="json"))
    else:
        _logger.info("ignore event_type={} in sync endpoint", event.event_type)

    run_id = event.run_id
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
        _persist_event(db, stage_event)
        publish(SYSTEM_TOPICS.JOB_STATUS, stage_event.model_dump(mode="json"))

    db.commit()
    return {"status": "accepted"}
