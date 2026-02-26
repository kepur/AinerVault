from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from ainern2d_shared.queue.topics import SYSTEM_TOPICS
from ainern2d_shared.schemas.events import EventEnvelope

from app.api.deps import get_store, publish

router = APIRouter(prefix="/internal/orchestrator", tags=["orchestrator"])


@router.post("/events", status_code=202)
def ingest_event(event: EventEnvelope) -> dict[str, str]:
    store = get_store()
    run_id = event.run_id
    if run_id:
        store.events.setdefault(run_id, []).append(event.model_dump(mode="json"))

    run = store.runs.get(run_id) if run_id else None
    if run is not None:
        run["updated_at"] = datetime.now(timezone.utc)
        if event.event_type == "job.claimed":
            run["status"] = "running"
            run["stage"] = "worker_running"
            run["progress"] = max(run["progress"], 10.0)
        elif event.event_type == "job.succeeded":
            run["status"] = "running"
            run["stage"] = "worker_succeeded"
            run["progress"] = max(run["progress"], 70.0)
        elif event.event_type == "job.failed":
            run["status"] = "failed"
            run["stage"] = "failed"
            run["latest_error"] = {
                "error_code": event.payload.get("error_code", "WORKER-EXEC-002"),
                "message": event.payload.get("error_message", "job failed"),
                "retryable": bool(event.payload.get("retryable", False)),
            }
        elif event.event_type == "compose.completed":
            run["status"] = "succeeded"
            run["stage"] = "completed"
            run["progress"] = 100.0
            run["final_artifact_uri"] = event.payload.get("artifact_uri")

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
