from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.content_models import PromptPlan
from ainern2d_shared.ainer_db_models.governance_models import CreativePolicyStack
from ainern2d_shared.ainer_db_models.provider_models import ModelProfile, ModelProvider
from ainern2d_shared.ainer_db_models.rag_models import KbVersion
from ainern2d_shared.ainer_db_models.governance_models import PersonaPackVersion
from ainern2d_shared.ainer_db_models.enum_models import RenderStage, RunStatus
from ainern2d_shared.ainer_db_models.pipeline_models import RenderRun, RunCheckpoint, WorkflowEvent
from ainern2d_shared.db.repositories.pipeline import RenderRunRepository, WorkflowEventRepository
from ainern2d_shared.queue.topics import SYSTEM_TOPICS
from ainern2d_shared.schemas.events import EventEnvelope
from ainern2d_shared.schemas.task import RunDetailResponse, TaskCreateRequest, TaskResponse

from app.api.deps import get_db, publish
from app.services.telegram_notify import notify_telegram_event

router = APIRouter(prefix="/api/v1", tags=["tasks"])
_REPLAY_P95_ALERT_MS = 3000


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


class PolicyStackReplayItem(BaseModel):
	policy_stack_id: str
	run_id: str
	name: str
	status: str
	active_persona_ref: str = ""
	review_items: list[str] = []
	hard_constraints: int = 0
	soft_constraints: int = 0
	guidelines: int = 0
	conflicts: int = 0
	audit_entries: int = 0


class RunSnapshotResponse(BaseModel):
	run_id: str
	snapshot: dict = Field(default_factory=dict)


def _percentile_ms(values: list[int], p: float) -> int:
	if not values:
		return 0
	ordered = sorted(values)
	idx = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * p)))
	return ordered[idx]


def _sanitize_profile_params(params_json: dict | None) -> dict:
	if not params_json:
		return {}
	masked = dict(params_json)
	for key in ("api_key", "token", "secret", "password"):
		if key in masked and masked[key]:
			masked[key] = "***"
	return masked


def _freeze_run_snapshot(
	db: Session,
	tenant_id: str,
	project_id: str,
	payload: dict,
) -> dict:
	providers = db.execute(
		select(ModelProvider).where(
			ModelProvider.tenant_id == tenant_id,
			ModelProvider.project_id == project_id,
			ModelProvider.deleted_at.is_(None),
		)
	).scalars().all()
	profiles = db.execute(
		select(ModelProfile).where(
			ModelProfile.tenant_id == tenant_id,
			ModelProfile.project_id == project_id,
			ModelProfile.deleted_at.is_(None),
		)
	).scalars().all()
	kb_versions = db.execute(
		select(KbVersion).where(
			KbVersion.tenant_id == tenant_id,
			KbVersion.project_id == project_id,
			KbVersion.deleted_at.is_(None),
		)
	).scalars().all()
	persona_versions = db.execute(
		select(PersonaPackVersion).where(
			PersonaPackVersion.tenant_id == tenant_id,
			PersonaPackVersion.project_id == project_id,
			PersonaPackVersion.deleted_at.is_(None),
		).order_by(PersonaPackVersion.created_at.desc())
	).scalars().all()
	router_policy = db.execute(
		select(CreativePolicyStack).where(
			CreativePolicyStack.tenant_id == tenant_id,
			CreativePolicyStack.project_id == project_id,
			CreativePolicyStack.name == "stage_router_policy_default",
			CreativePolicyStack.deleted_at.is_(None),
		)
	).scalars().first()
	language_policy = db.execute(
		select(CreativePolicyStack).where(
			CreativePolicyStack.tenant_id == tenant_id,
			CreativePolicyStack.project_id == project_id,
			CreativePolicyStack.name == "language_policy_default",
			CreativePolicyStack.deleted_at.is_(None),
		)
	).scalars().first()
	telegram_policy = db.execute(
		select(CreativePolicyStack).where(
			CreativePolicyStack.tenant_id == tenant_id,
			CreativePolicyStack.project_id == project_id,
			CreativePolicyStack.name == "telegram_notify_default",
			CreativePolicyStack.deleted_at.is_(None),
		)
	).scalars().first()
	culture_pack_id = str(payload.get("culture_pack_id") or "").strip()
	culture_packs = db.execute(
		select(CreativePolicyStack).where(
			CreativePolicyStack.tenant_id == tenant_id,
			CreativePolicyStack.project_id == project_id,
			CreativePolicyStack.deleted_at.is_(None),
		).order_by(CreativePolicyStack.updated_at.desc())
	).scalars().all()

	selected_culture = None
	for row in culture_packs:
		stack_json = row.stack_json or {}
		if stack_json.get("type") != "culture_pack":
			continue
		if culture_pack_id and stack_json.get("culture_pack_id") != culture_pack_id:
			continue
		selected_culture = stack_json
		break

	return {
		"frozen_at": datetime.now(timezone.utc).isoformat(),
		"providers": [
			{
				"id": item.id,
				"name": item.name,
				"endpoint": item.endpoint,
				"auth_mode": item.auth_mode,
			}
			for item in providers
		],
		"model_profiles": [
			{
				"id": item.id,
				"provider_id": item.provider_id,
				"purpose": item.purpose,
				"name": item.name,
				"params_json": _sanitize_profile_params(item.params_json),
			}
			for item in profiles
		],
		"router_policy": (router_policy.stack_json or {}) if router_policy else {},
		"language_settings": (language_policy.stack_json or {}) if language_policy else {},
		"telegram_settings": (telegram_policy.stack_json or {}) if telegram_policy else {},
		"kb_versions": [
			{
				"id": item.id,
				"collection_id": item.collection_id,
				"version_name": item.version_name,
				"status": item.status,
			}
			for item in kb_versions
		],
		"persona_versions": [
			{
				"id": item.id,
				"persona_pack_id": item.persona_pack_id,
				"version_name": item.version_name,
			}
			for item in persona_versions[:20]
		],
		"selected_culture_pack": selected_culture or {},
		"requested_payload": payload,
	}


@router.post("/tasks", response_model=TaskSubmitAccepted, status_code=202)
def create_task(body: TaskSubmitRequest, db: Session = Depends(get_db)) -> TaskSubmitAccepted:
	run_id = f"run_{uuid4().hex}"
	now = datetime.now(timezone.utc)
	snapshot = _freeze_run_snapshot(
		db=db,
		tenant_id=body.tenant_id,
		project_id=body.project_id,
		payload=body.payload or {},
	)

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
		kb_version_id=(body.payload or {}).get("kb_version_id"),
		config_json=snapshot,
	)
	run_repo = RenderRunRepository(db)
	run_repo.create(run)
	db.add(
		RunCheckpoint(
			id=f"cp_{uuid4().hex}",
			tenant_id=body.tenant_id,
			project_id=body.project_id,
			trace_id=body.trace_id,
			correlation_id=body.correlation_id,
			idempotency_key=f"idem_snapshot_{run_id}",
			run_id=run_id,
			stage=RenderStage.ingest,
			checkpoint_name="run_snapshot_frozen",
			snapshot_json=snapshot,
		)
	)

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
	notify_telegram_event(
		db=db,
		tenant_id=body.tenant_id,
		project_id=body.project_id,
		event_type="task.submitted",
		summary="Task submitted",
		run_id=run_id,
		trace_id=body.trace_id,
		correlation_id=body.correlation_id,
		extra={
			"chapter_id": body.chapter_id,
			"requested_quality": body.requested_quality,
			"language_context": body.language_context,
		},
	)

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


@router.get("/runs/{run_id}/snapshot", response_model=RunSnapshotResponse)
def get_run_snapshot(run_id: str, db: Session = Depends(get_db)) -> RunSnapshotResponse:
	run = RenderRunRepository(db).get(run_id)
	if run is None:
		raise HTTPException(status_code=404, detail="run not found")
	return RunSnapshotResponse(run_id=run_id, snapshot=run.config_json or {})


@router.get("/runs/{run_id}/prompt-plans", response_model=list[PromptPlanReplayItem])
def get_run_prompt_plans(
	run_id: str,
	response: Response,
	limit: int = Query(default=100, ge=1, le=500),
	offset: int = Query(default=0, ge=0),
	db: Session = Depends(get_db),
) -> list[PromptPlanReplayItem]:
	run_repo = RenderRunRepository(db)
	run = run_repo.get(run_id)
	if run is None:
		raise HTTPException(status_code=404, detail="run not found")

	start = perf_counter()
	total = db.execute(
		select(func.count(PromptPlan.id)).where(
			PromptPlan.run_id == run_id,
			PromptPlan.deleted_at.is_(None),
		)
	).scalar_one()
	response.headers["X-Prompt-Plan-Total"] = str(total)

	plans = db.execute(
		select(PromptPlan)
		.where(
			PromptPlan.run_id == run_id,
			PromptPlan.deleted_at.is_(None),
		)
		.order_by(PromptPlan.shot_id.asc())
		.offset(offset)
		.limit(limit)
	).scalars().all()
	elapsed_ms = int((perf_counter() - start) * 1000)
	response.headers["X-Prompt-Plan-Query-Ms"] = str(elapsed_ms)
	history = []
	recent_metrics = db.execute(
		select(WorkflowEvent)
		.where(
			WorkflowEvent.run_id == run_id,
			WorkflowEvent.event_type == "prompt.plan.replay.queried",
			WorkflowEvent.deleted_at.is_(None),
		)
		.order_by(WorkflowEvent.occurred_at.desc())
		.limit(50)
	).scalars().all()
	for evt in recent_metrics:
		query_ms = (evt.payload_json or {}).get("query_ms")
		if isinstance(query_ms, int):
			history.append(query_ms)
	latency_samples = history + [elapsed_ms]
	p50_ms = _percentile_ms(latency_samples, 0.5)
	p95_ms = _percentile_ms(latency_samples, 0.95)
	alert = p95_ms >= _REPLAY_P95_ALERT_MS
	response.headers["X-Prompt-Plan-P50-Ms"] = str(p50_ms)
	response.headers["X-Prompt-Plan-P95-Ms"] = str(p95_ms)
	response.headers["X-Prompt-Plan-Latency-Alert"] = "on" if alert else "off"

	now = datetime.now(timezone.utc)
	replay_metric_event = WorkflowEvent(
		id=f"evt_{uuid4().hex[:24]}",
		tenant_id=run.tenant_id,
		project_id=run.project_id,
		trace_id=run.trace_id,
		correlation_id=run.correlation_id,
		idempotency_key=f"idem_prompt_replay_{uuid4().hex}",
		run_id=run_id,
		stage=run.stage,
		event_type="prompt.plan.replay.queried",
		event_version="1.0",
		producer="studio_api",
		occurred_at=now,
		payload_json={
			"run_id": run_id,
			"total": total,
			"limit": limit,
			"offset": offset,
			"query_ms": elapsed_ms,
			"p50_ms": p50_ms,
			"p95_ms": p95_ms,
			"latency_alert": alert,
			"alert_threshold_ms": _REPLAY_P95_ALERT_MS,
		},
	)
	WorkflowEventRepository(db).create(replay_metric_event)
	db.commit()

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


@router.get("/runs/{run_id}/policy-stacks", response_model=list[PolicyStackReplayItem])
def get_run_policy_stacks(
	run_id: str,
	response: Response,
	db: Session = Depends(get_db),
) -> list[PolicyStackReplayItem]:
	run_repo = RenderRunRepository(db)
	run = run_repo.get(run_id)
	if run is None:
		raise HTTPException(status_code=404, detail="run not found")

	start = perf_counter()
	stack_name = f"run_policy_{run_id}"
	stacks = db.execute(
		select(CreativePolicyStack)
		.where(
			CreativePolicyStack.tenant_id == run.tenant_id,
			CreativePolicyStack.project_id == run.project_id,
			CreativePolicyStack.name == stack_name,
			CreativePolicyStack.deleted_at.is_(None),
		)
		.order_by(CreativePolicyStack.updated_at.desc())
	).scalars().all()
	elapsed_ms = int((perf_counter() - start) * 1000)
	response.headers["X-Policy-Stack-Query-Ms"] = str(elapsed_ms)
	response.headers["X-Policy-Stack-Total"] = str(len(stacks))

	items: list[PolicyStackReplayItem] = []
	for stack in stacks:
		stack_json = stack.stack_json or {}
		summary = stack_json.get("summary") or {}
		policy_output = stack_json.get("policy_output") or {}
		items.append(
			PolicyStackReplayItem(
				policy_stack_id=stack.id,
				run_id=run_id,
				name=stack.name,
				status=stack.status,
				active_persona_ref=str(stack_json.get("active_persona_ref") or ""),
				review_items=list(policy_output.get("review_items") or []),
				hard_constraints=int(summary.get("hard_constraints") or 0),
				soft_constraints=int(summary.get("soft_constraints") or 0),
				guidelines=int(summary.get("guidelines") or 0),
				conflicts=int(summary.get("conflicts") or 0),
				audit_entries=int(summary.get("audit_entries") or len(policy_output.get("audit_trail") or [])),
			)
		)
	return items
