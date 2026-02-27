from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.content_models import PromptPlan
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


class PromptPlanReplayItem(BaseModel):
	plan_id: str
	run_id: str
	shot_id: str
	prompt_text: str
	negative_prompt_text: str | None = None
	model_hint_json: dict | None = None


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


@router.get("/runs/{run_id}/prompt-plans", response_model=list[PromptPlanReplayItem])
def get_run_prompt_plans(run_id: str, db: Session = Depends(get_db)) -> list[PromptPlanReplayItem]:
	run_repo = RenderRunRepository(db)
	run = run_repo.get(run_id)
	if run is None:
		raise HTTPException(status_code=404, detail="run not found")

	plans = db.execute(
		select(PromptPlan)
		.where(
			PromptPlan.run_id == run_id,
			PromptPlan.deleted_at.is_(None),
		)
		.order_by(PromptPlan.shot_id.asc()),
	).scalars().all()

	return [
		PromptPlanReplayItem(
			plan_id=plan.id,
			run_id=plan.run_id,
			shot_id=plan.shot_id,
			prompt_text=plan.prompt_text,
			negative_prompt_text=plan.negative_prompt_text,
			model_hint_json=plan.model_hint_json,
		)
		for plan in plans
	]
