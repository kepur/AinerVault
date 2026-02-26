from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ainern2d_shared.schemas.events import EventEnvelope

router = APIRouter(prefix="/internal", tags=["worker-hub"])

DISPATCH_JOBS: dict[str, dict[str, object]] = {}


class DispatchRequest(BaseModel):
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


class DispatchResponse(BaseModel):
	job_id: str
	status: str


@router.post("/dispatch", response_model=DispatchResponse, status_code=202)
def dispatch(body: DispatchRequest) -> DispatchResponse:
	now = datetime.now(timezone.utc)
	DISPATCH_JOBS[body.job_id] = {
		"job_id": body.job_id,
		"run_id": body.run_id,
		"worker_type": body.worker_type,
		"tenant_id": body.tenant_id,
		"project_id": body.project_id,
		"trace_id": body.trace_id,
		"correlation_id": body.correlation_id,
		"idempotency_key": body.idempotency_key,
		"status": "enqueued",
		"updated_at": now,
	}

	claimed_event = EventEnvelope(
		event_type="job.claimed",
		producer="worker-hub",
		occurred_at=now,
		tenant_id=body.tenant_id,
		project_id=body.project_id,
		idempotency_key=body.idempotency_key,
		run_id=body.run_id,
		job_id=body.job_id,
		trace_id=body.trace_id,
		correlation_id=body.correlation_id,
		payload={"worker_type": body.worker_type, "queue_status": "claimed"},
	)
	DISPATCH_JOBS[body.job_id]["claimed_event"] = claimed_event.model_dump(mode="json")
	return DispatchResponse(job_id=body.job_id, status="enqueued")

