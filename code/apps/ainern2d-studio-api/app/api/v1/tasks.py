from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.enum_models import RenderStage, RunStatus
from ainern2d_shared.ainer_db_models.pipeline_models import RenderRun, WorkflowEvent
from ainern2d_shared.db.repositories.pipeline import RenderRunRepository, WorkflowEventRepository
from ainern2d_shared.queue.topics import SYSTEM_TOPICS
from ainern2d_shared.schemas.events import EventEnvelope
from ainern2d_shared.schemas.task import RunDetailResponse, TaskCreateRequest, TaskResponse

from app.api.deps import get_db, publish

router = APIRouter(prefix="/api/v1", tags=["tasks"])


class TaskSubmitRequest(TaskCreateRequest):
	trace_id: str
	correlation_id: str
	idempotency_key: str


class TaskSubmitAccepted(TaskResponse):
	pass


@router.post("/tasks", response_model=TaskSubmitAccepted, status_code=202)
def create_task(body: TaskSubmitRequest, db: Session = Depends(get_db)) -> TaskSubmitAccepted:
	run_id = f"run_{uuid4().hex}"
	now = datetime.now(timezone.utc)

	run = RenderRun(
		id=run_id,
		tenant_id=body.tenant_id,
		project_id=body.project_id,
		trace_id=body.trace_id,
		correlation_id=body.correlation_id,
		idempotency_key=body.idempotency_key,
		chapter_id=body.chapter_id,
		status=RunStatus.queued,
		stage=RenderStage.ingest,
		progress=0,
	)
	run_repo = RenderRunRepository(db)
	run_repo.create(run)

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

	event_repo = WorkflowEventRepository(db)
	wf_event = WorkflowEvent(
		id=envelope.event_id,
		tenant_id=body.tenant_id,
		project_id=body.project_id,
		trace_id=body.trace_id,
		correlation_id=body.correlation_id,
		idempotency_key=body.idempotency_key,
		run_id=run_id,
		event_type="task.submitted",
		event_version="1.0",
		producer="gateway",
		occurred_at=now,
		payload_json=envelope.model_dump(mode="json"),
	)
	event_repo.create(wf_event)
	db.commit()

	return TaskSubmitAccepted(run_id=run_id, status="queued", message="accepted")


@router.get("/runs/{run_id}", response_model=RunDetailResponse)
def get_run_detail(run_id: str, db: Session = Depends(get_db)) -> RunDetailResponse:
	run_repo = RenderRunRepository(db)
	run = run_repo.get(run_id)
	if run is None:
		raise HTTPException(status_code=404, detail="run not found")

	latest_error = None
	if run.error_code:
		latest_error = {"error_code": run.error_code, "message": run.error_message or ""}

	return RunDetailResponse(
		run_id=run.id,
		status=run.status.value if run.status else "unknown",
		stage=run.stage.value if run.stage else "unknown",
		progress=float(run.progress or 0),
		latest_error=latest_error,
		final_artifact_uri=None,
	)

