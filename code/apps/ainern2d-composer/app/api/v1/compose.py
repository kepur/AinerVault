from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter

from ainern2d_shared.schemas.events import EventEnvelope
from ainern2d_shared.schemas.task import ComposeRequest

router = APIRouter(prefix="/internal", tags=["composer"])

COMPOSE_JOBS: dict[str, dict[str, object]] = {}


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
    return {"compose_job_id": compose_job_id, "status": "started"}
