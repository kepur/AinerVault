from __future__ import annotations

from datetime import datetime, timezone
import time

from fastapi import APIRouter, Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from uuid import uuid4

from ainern2d_shared.ainer_db_models.enum_models import RenderStage, RunStatus
from ainern2d_shared.ainer_db_models.pipeline_models import WorkflowEvent
from ainern2d_shared.db.repositories.pipeline import RenderRunRepository
from ainern2d_shared.queue.topics import SYSTEM_TOPICS
from ainern2d_shared.schemas.events import EventEnvelope
from ainern2d_shared.services.base_skill import SkillContext
from ainern2d_shared.config.setting import settings
from ainern2d_shared.queue.rabbitmq import RabbitMQConsumer

from app.api.deps import get_db, get_db_session, publish
from ainern2d_shared.telemetry.logging import get_logger
from app.services.telegram_notify import notify_telegram_event

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


def _event_exists(db: Session, event_id: str) -> bool:
    """Idempotency guard: whether this event_id is already persisted."""
    return db.get(WorkflowEvent, event_id) is not None


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


def handle_skill_event(payload: dict) -> None:
    """Consume SKILL event stream and execute cross-skill rollback linkage."""
    event = EventEnvelope.model_validate(payload)
    db = get_db_session()
    try:
        if _event_exists(db, event.event_id):
            _logger.info("skip duplicate skill event event_id={}", event.event_id)
            return

        _persist_event(db, event)
        try:
            # Force uniqueness check before side-effects to avoid duplicate rollback
            # under concurrent consumers.
            db.flush()
        except IntegrityError:
            db.rollback()
            _logger.info("skip duplicate skill event on flush event_id={}", event.event_id)
            return

        if event.event_type == "kb.version.rolled_back":
            rollback_payload = event.payload or {}
            # If executor already handled rollback, this consumer is no-op.
            if not rollback_payload.get("executor_triggered"):
                kb_id = str(rollback_payload.get("kb_id") or "").strip()
                target_version_id = str(
                    rollback_payload.get("rollback_target_kb_version_id") or ""
                ).strip()
                if kb_id and target_version_id:
                    from ainern2d_shared.schemas.skills.skill_11 import Skill11Input
                    from app.services.skills.skill_11_rag_kb_manager import RagKBManagerService

                    out11 = RagKBManagerService(db).execute(
                        Skill11Input(
                            kb_id=kb_id,
                            action="rollback",
                            rollback_target_version_id=target_version_id,
                            rollback_reason=str(rollback_payload.get("reason") or "skill_event_consumer"),
                        ),
                        SkillContext(
                            tenant_id=event.tenant_id,
                            project_id=event.project_id,
                            run_id=event.run_id or "",
                            trace_id=event.trace_id,
                            correlation_id=event.correlation_id,
                            idempotency_key=event.idempotency_key,
                            schema_version=event.schema_version,
                        ),
                    )
                    for emitted in out11.event_envelopes:
                        _persist_event(db, emitted)
                else:
                    _logger.warning(
                        "skip rollback consume: missing kb_id/target_version_id event_id={}",
                        event.event_id,
                    )

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def handle_alert_event(payload: dict) -> None:
    """Consume alert.events and execute queued Telegram retries."""
    if payload.get("event_type") != "telegram.notify.retry":
        return
    tenant_id = str(payload.get("tenant_id") or "").strip()
    project_id = str(payload.get("project_id") or "").strip()
    if not tenant_id or not project_id:
        return

    delay_ms = int(payload.get("delay_ms") or 0)
    if delay_ms > 0:
        time.sleep(min(delay_ms / 1000.0, 5.0))

    retry_attempt = int(payload.get("retry_attempt") or 0)
    max_retry_attempts = int(payload.get("max_retry_attempts") or 3)
    db = get_db_session()
    try:
        result = notify_telegram_event(
            db=db,
            tenant_id=tenant_id,
            project_id=project_id,
            event_type=str(payload.get("source_event_type") or "unknown"),
            summary=str(payload.get("summary") or "queued telegram notify"),
            run_id=str(payload.get("run_id") or "") or None,
            job_id=str(payload.get("job_id") or "") or None,
            trace_id=str(payload.get("trace_id") or "") or None,
            correlation_id=str(payload.get("correlation_id") or "") or None,
            extra=dict(payload.get("extra") or {}),
            queue_on_failure=False,
            retry_attempt=retry_attempt,
            max_retry_attempts=max_retry_attempts,
        )
        reason = str(result.get("reason") or "")
        status_code = int(result.get("status_code") or 0)
        retryable = (
            reason.startswith("network_error")
            or reason.startswith("notify_error")
            or reason.startswith("circuit_open")
            or reason.startswith("telegram_not_ok")
            or (reason.startswith("http_error:") and status_code >= 500)
        )
        if (not result.get("delivered")) and retryable and retry_attempt < max_retry_attempts:
            publish(
                SYSTEM_TOPICS.ALERT_EVENTS,
                {
                    **payload,
                    "retry_attempt": retry_attempt + 1,
                    "delay_ms": max(1000, int(payload.get("delay_ms") or 1000) * 2),
                },
            )
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
    elif topic == SYSTEM_TOPICS.SKILL_EVENTS:
        consumer.consume(topic, handle_skill_event)
    elif topic == SYSTEM_TOPICS.ALERT_EVENTS:
        consumer.consume(topic, handle_alert_event)


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
