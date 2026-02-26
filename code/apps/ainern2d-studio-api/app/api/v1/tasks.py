from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from ainern2d_shared.queue.topics import SYSTEM_TOPICS
from ainern2d_shared.schemas.events import EventEnvelope
from ainern2d_shared.schemas.task import RunDetailResponse, TaskCreateRequest, TaskResponse

from app.api.deps import get_store, publish

router = APIRouter(prefix="/api/v1", tags=["tasks"])


class TaskSubmitRequest(TaskCreateRequest):
	trace_id: str
	correlation_id: str
	idempotency_key: str


class TaskSubmitAccepted(TaskResponse):
	pass


@router.post("/tasks", response_model=TaskSubmitAccepted, status_code=202)
def create_task(body: TaskSubmitRequest) -> TaskSubmitAccepted:
	run_id = f"run_{uuid4().hex}"
	now = datetime.now(timezone.utc)

	store = get_store()
	store.runs[run_id] = {
		"run_id": run_id,
		"status": "queued",
		"stage": "submitted",
		"progress": 0.0,
		"latest_error": None,
		"final_artifact_uri": None,
		"created_at": now,
		"updated_at": now,
		"tenant_id": body.tenant_id,
		"project_id": body.project_id,
		"trace_id": body.trace_id,
		"correlation_id": body.correlation_id,
		"idempotency_key": body.idempotency_key,
	}

	envelope = EventEnvelope(
		event_type="task.submitted",
		producer="gateway",
		occurred_at=now,
		tenant_id=body.tenant_id,
		project_id=body.project_id,
		idempotency_key=body.idempotency_key,
		run_id=run_id,
		trace_id=body.trace_id,
		correlation_id=body.correlation_id,
		payload={
			"chapter_id": body.chapter_id,
			"requested_quality": body.requested_quality,
			"language_context": body.language_context,
			"payload": body.payload or {},
		},
	)
	publish(SYSTEM_TOPICS.TASK_SUBMITTED, envelope.model_dump(mode="json"))

	store.events.setdefault(run_id, []).append(envelope.model_dump(mode="json"))
	return TaskSubmitAccepted(run_id=run_id, status="queued", message="accepted")


@router.get("/runs/{run_id}", response_model=RunDetailResponse)
def get_run_detail(run_id: str) -> RunDetailResponse:
	store = get_store()
	run = store.runs.get(run_id)
	if run is None:
		raise HTTPException(status_code=404, detail="run not found")

	latest_error = run["latest_error"]
	if isinstance(latest_error, str):
		latest_error = {"message": latest_error}

	return RunDetailResponse(
		run_id=run["run_id"],
		status=run["status"],
		stage=run["stage"],
		progress=run["progress"],
		latest_error=latest_error,
		final_artifact_uri=run["final_artifact_uri"],
	)

