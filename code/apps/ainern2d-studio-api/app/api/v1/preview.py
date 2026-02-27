from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.content_models import Artifact, Scene, Shot
from ainern2d_shared.ainer_db_models.enum_models import JobStatus, JobType, RenderStage
from ainern2d_shared.ainer_db_models.knowledge_models import Entity
from ainern2d_shared.ainer_db_models.pipeline_models import Job, RenderRun
from ainern2d_shared.ainer_db_models.preview_models import (
	CharacterVoiceBinding,
	EntityContinuityProfile,
	EntityInstanceLink,
	EntityPreviewVariant,
)
from ainern2d_shared.queue.topics import SYSTEM_TOPICS
from ainern2d_shared.schemas.events import EventEnvelope

from app.api.deps import get_db, publish

router = APIRouter(prefix="/api/v1", tags=["preview"])


class PreviewEntityResponse(BaseModel):
	entity_id: str
	label: str
	entity_type: str
	continuity_status: str = "draft"
	locked_variant_id: Optional[str] = None
	latest_variant_id: Optional[str] = None
	latest_variant_status: Optional[str] = None
	voice_binding_id: Optional[str] = None
	voice_id: Optional[str] = None


class PreviewVariantResponse(BaseModel):
	variant_id: str
	run_id: str
	entity_id: str
	entity_label: str
	view_angle: str
	generation_backend: str
	status: str
	dispatch_job_id: Optional[str] = None
	artifact_id: Optional[str] = None
	artifact_uri: Optional[str] = None
	prompt_text: Optional[str] = None
	negative_prompt_text: Optional[str] = None
	review_note: Optional[str] = None
	created_at: datetime


class GeneratePreviewRequest(BaseModel):
	shot_id: Optional[str] = None
	scene_id: Optional[str] = None
	view_angles: list[str] = Field(default_factory=lambda: ["front", "three_quarter", "side", "back"])
	prompt_text: Optional[str] = None
	negative_prompt_text: Optional[str] = None
	generation_backend: str = "comfyui"


class GeneratePreviewResponse(BaseModel):
	run_id: str
	entity_id: str
	created_variants: list[str]
	created_jobs: list[str]
	message: str = "preview generation queued"


class ReviewPreviewVariantRequest(BaseModel):
	decision: Literal["approve", "reject", "regenerate"]
	note: Optional[str] = None


class ReviewPreviewVariantResponse(BaseModel):
	variant_id: str
	status: str
	continuity_profile_id: Optional[str] = None
	regenerated_variant_id: Optional[str] = None
	regenerated_job_id: Optional[str] = None


class VoiceBindingRequest(BaseModel):
	language_code: str = "zh-CN"
	voice_id: str
	tts_model: str = "tts-1"
	provider: str = "openai"
	locked: bool = True
	notes: Optional[str] = None


class VoiceBindingResponse(BaseModel):
	id: str
	entity_id: str
	project_id: str
	language_code: str
	voice_id: str
	tts_model: str
	provider: str
	locked: bool
	notes: Optional[str] = None


class ContinuityProfileResponse(BaseModel):
	id: str
	entity_id: str
	project_id: str
	continuity_status: str
	locked_preview_variant_id: Optional[str] = None
	anchors_json: dict
	rules_json: Optional[dict] = None


def _build_event(run: RenderRun, job: Job, payload: dict, now: datetime) -> EventEnvelope:
	return EventEnvelope(
		event_type="job.created",
		producer="studio-api",
		occurred_at=now,
		tenant_id=run.tenant_id,
		project_id=run.project_id,
		idempotency_key=job.idempotency_key or "",
		run_id=run.id,
		job_id=job.id,
		trace_id=run.trace_id or "",
		correlation_id=run.correlation_id or "",
		payload=payload,
	)


def _to_variant_response(v: EntityPreviewVariant, entity_label: str, artifact_uri: Optional[str]) -> PreviewVariantResponse:
	return PreviewVariantResponse(
		variant_id=v.id,
		run_id=v.run_id,
		entity_id=v.entity_id,
		entity_label=entity_label,
		view_angle=v.view_angle,
		generation_backend=v.generation_backend,
		status=v.status,
		dispatch_job_id=v.dispatch_job_id,
		artifact_id=v.artifact_id,
		artifact_uri=artifact_uri,
		prompt_text=v.prompt_text,
		negative_prompt_text=v.negative_prompt_text,
		review_note=v.review_note,
		created_at=v.created_at,
	)


@router.get("/runs/{run_id}/preview/entities", response_model=list[PreviewEntityResponse])
def list_preview_entities(run_id: str, db: Session = Depends(get_db)) -> list[PreviewEntityResponse]:
	run = db.get(RenderRun, run_id)
	if run is None:
		raise HTTPException(status_code=404, detail="run not found")

	entity_ids = [
		row[0]
		for row in db.execute(
			select(EntityInstanceLink.entity_id)
			.where(
				EntityInstanceLink.run_id == run_id,
				EntityInstanceLink.deleted_at.is_(None),
			)
			.distinct()
		).all()
	]
	if not entity_ids:
		entity_ids = [
			row[0]
			for row in db.execute(
				select(EntityPreviewVariant.entity_id)
				.where(
					EntityPreviewVariant.run_id == run_id,
					EntityPreviewVariant.deleted_at.is_(None),
				)
				.distinct()
			).all()
		]
	if not entity_ids:
		return []

	entities = db.execute(
		select(Entity).where(
			Entity.id.in_(entity_ids),
			Entity.project_id == run.project_id,
			Entity.deleted_at.is_(None),
		)
	).scalars().all()
	entity_map = {e.id: e for e in entities}

	profiles = db.execute(
		select(EntityContinuityProfile).where(
			EntityContinuityProfile.entity_id.in_(entity_ids),
			EntityContinuityProfile.project_id == run.project_id,
			EntityContinuityProfile.deleted_at.is_(None),
		)
	).scalars().all()
	profile_map = {p.entity_id: p for p in profiles}

	variants = db.execute(
		select(EntityPreviewVariant).where(
			EntityPreviewVariant.entity_id.in_(entity_ids),
			EntityPreviewVariant.run_id == run_id,
			EntityPreviewVariant.deleted_at.is_(None),
		).order_by(EntityPreviewVariant.created_at.desc())
	).scalars().all()
	latest_variant_map: dict[str, EntityPreviewVariant] = {}
	for v in variants:
		latest_variant_map.setdefault(v.entity_id, v)

	bindings = db.execute(
		select(CharacterVoiceBinding).where(
			CharacterVoiceBinding.entity_id.in_(entity_ids),
			CharacterVoiceBinding.project_id == run.project_id,
			CharacterVoiceBinding.deleted_at.is_(None),
		).order_by(CharacterVoiceBinding.updated_at.desc())
	).scalars().all()
	voice_map: dict[str, CharacterVoiceBinding] = {}
	for b in bindings:
		voice_map.setdefault(b.entity_id, b)

	resp: list[PreviewEntityResponse] = []
	for entity_id in entity_ids:
		entity = entity_map.get(entity_id)
		if entity is None:
			continue
		profile = profile_map.get(entity_id)
		latest = latest_variant_map.get(entity_id)
		voice = voice_map.get(entity_id)
		resp.append(PreviewEntityResponse(
			entity_id=entity.id,
			label=entity.label,
			entity_type=entity.type.value if hasattr(entity.type, "value") else str(entity.type),
			continuity_status=(profile.continuity_status if profile else "draft"),
			locked_variant_id=(profile.locked_preview_variant_id if profile else None),
			latest_variant_id=(latest.id if latest else None),
			latest_variant_status=(latest.status if latest else None),
			voice_binding_id=(voice.id if voice else None),
			voice_id=(voice.voice_id if voice else None),
		))
	return resp


@router.get("/runs/{run_id}/preview/variants", response_model=list[PreviewVariantResponse])
def list_preview_variants(
	run_id: str,
	entity_id: Optional[str] = Query(default=None),
	db: Session = Depends(get_db),
) -> list[PreviewVariantResponse]:
	run = db.get(RenderRun, run_id)
	if run is None:
		raise HTTPException(status_code=404, detail="run not found")

	stmt = select(EntityPreviewVariant).where(
		EntityPreviewVariant.run_id == run_id,
		EntityPreviewVariant.deleted_at.is_(None),
	).order_by(EntityPreviewVariant.created_at.desc())
	if entity_id:
		stmt = stmt.where(EntityPreviewVariant.entity_id == entity_id)
	variants = db.execute(stmt).scalars().all()
	if not variants:
		return []

	entity_ids = sorted({v.entity_id for v in variants})
	entities = db.execute(select(Entity).where(Entity.id.in_(entity_ids))).scalars().all()
	entity_map = {e.id: e for e in entities}

	artifact_ids = [v.artifact_id for v in variants if v.artifact_id]
	artifact_map: dict[str, Artifact] = {}
	if artifact_ids:
		artifacts = db.execute(select(Artifact).where(Artifact.id.in_(artifact_ids))).scalars().all()
		artifact_map = {a.id: a for a in artifacts}

	resp: list[PreviewVariantResponse] = []
	for v in variants:
		entity = entity_map.get(v.entity_id)
		artifact_uri = artifact_map[v.artifact_id].uri if v.artifact_id in artifact_map else None
		resp.append(_to_variant_response(v, entity.label if entity else v.entity_id, artifact_uri))
	return resp


@router.post("/runs/{run_id}/preview/entities/{entity_id}/generate", response_model=GeneratePreviewResponse)
def generate_preview_variants(
	run_id: str,
	entity_id: str,
	body: GeneratePreviewRequest,
	db: Session = Depends(get_db),
) -> GeneratePreviewResponse:
	run = db.get(RenderRun, run_id)
	if run is None:
		raise HTTPException(status_code=404, detail="run not found")
	entity = db.get(Entity, entity_id)
	if entity is None or entity.project_id != run.project_id:
		raise HTTPException(status_code=404, detail="entity not found in this run scope")

	if body.shot_id and db.get(Shot, body.shot_id) is None:
		raise HTTPException(status_code=404, detail="shot not found")
	if body.scene_id and db.get(Scene, body.scene_id) is None:
		raise HTTPException(status_code=404, detail="scene not found")
	if not body.view_angles:
		raise HTTPException(status_code=422, detail="view_angles cannot be empty")

	now = datetime.now(timezone.utc)
	created_jobs: list[str] = []
	created_variants: list[str] = []
	for angle in body.view_angles:
		job_id = f"job_{uuid4().hex}"
		variant_id = f"epv_{uuid4().hex[:16]}"
		idem = f"preview_{run_id}_{entity_id}_{angle}_{uuid4().hex[:8]}"
		payload = {
			"preview_mode": True,
			"entity_id": entity_id,
			"view_angle": angle,
			"shot_id": body.shot_id,
			"scene_id": body.scene_id,
			"prompt_text": body.prompt_text,
			"negative_prompt_text": body.negative_prompt_text,
			"preview_variant_id": variant_id,
		}

		job = Job(
			id=job_id,
			tenant_id=run.tenant_id,
			project_id=run.project_id,
			run_id=run_id,
			chapter_id=run.chapter_id,
			shot_id=body.shot_id,
			job_type=JobType.render_video,
			stage=RenderStage.execute,
			status=JobStatus.queued,
			payload_json=payload,
			idempotency_key=idem,
		)
		db.add(job)

		variant = EntityPreviewVariant(
			id=variant_id,
			tenant_id=run.tenant_id,
			project_id=run.project_id,
			trace_id=run.trace_id,
			correlation_id=run.correlation_id,
			idempotency_key=idem,
			run_id=run_id,
			entity_id=entity_id,
			shot_id=body.shot_id,
			scene_id=body.scene_id,
			view_angle=angle,
			generation_backend=body.generation_backend,
			status="queued",
			dispatch_job_id=job_id,
			prompt_text=body.prompt_text,
			negative_prompt_text=body.negative_prompt_text,
		)
		db.add(variant)

		envelope = _build_event(
			run=run,
			job=job,
			payload={"job_id": job_id, "run_id": run_id, "preview_mode": True, "preview_variant_id": variant_id},
			now=now,
		)
		publish(SYSTEM_TOPICS.JOB_DISPATCH, envelope.model_dump(mode="json"))
		created_jobs.append(job_id)
		created_variants.append(variant_id)

	db.commit()
	return GeneratePreviewResponse(
		run_id=run_id,
		entity_id=entity_id,
		created_variants=created_variants,
		created_jobs=created_jobs,
	)


@router.post("/preview/variants/{variant_id}/review", response_model=ReviewPreviewVariantResponse)
def review_preview_variant(
	variant_id: str,
	body: ReviewPreviewVariantRequest,
	db: Session = Depends(get_db),
) -> ReviewPreviewVariantResponse:
	variant = db.get(EntityPreviewVariant, variant_id)
	if variant is None:
		raise HTTPException(status_code=404, detail="preview variant not found")
	run = db.get(RenderRun, variant.run_id)
	if run is None:
		raise HTTPException(status_code=404, detail="run not found")

	now = datetime.now(timezone.utc)
	continuity_profile_id: str | None = None
	regenerated_variant_id: str | None = None
	regenerated_job_id: str | None = None

	if body.decision == "approve":
		variant.status = "approved"
		variant.review_note = body.note
		stmt = select(EntityContinuityProfile).where(
			EntityContinuityProfile.entity_id == variant.entity_id,
			EntityContinuityProfile.project_id == variant.project_id,
			EntityContinuityProfile.deleted_at.is_(None),
		)
		profile = db.execute(stmt).scalars().first()
		if profile is None:
			profile = EntityContinuityProfile(
				id=f"ecp_{uuid4().hex[:16]}",
				tenant_id=variant.tenant_id,
				project_id=variant.project_id,
				trace_id=variant.trace_id,
				correlation_id=variant.correlation_id,
				idempotency_key=f"profile_lock_{variant.id}",
				entity_id=variant.entity_id,
				continuity_status="locked",
				anchors_json={
					"approved_variant_id": variant.id,
					"view_angle": variant.view_angle,
					"generation_backend": variant.generation_backend,
				},
				locked_preview_variant_id=variant.id,
				last_reviewed_at=now,
			)
			db.add(profile)
		else:
			anchors = dict(profile.anchors_json or {})
			anchors["approved_variant_id"] = variant.id
			anchors["view_angle"] = variant.view_angle
			anchors["generation_backend"] = variant.generation_backend
			profile.anchors_json = anchors
			profile.continuity_status = "locked"
			profile.locked_preview_variant_id = variant.id
			profile.last_reviewed_at = now
		continuity_profile_id = profile.id
	elif body.decision == "reject":
		variant.status = "rejected"
		variant.review_note = body.note
	else:
		variant.status = "regenerate_requested"
		variant.review_note = body.note
		regenerated_job_id = f"job_{uuid4().hex}"
		regenerated_variant_id = f"epv_{uuid4().hex[:16]}"
		idem = f"preview_regen_{variant.id}_{uuid4().hex[:8]}"
		payload = {
			"preview_mode": True,
			"entity_id": variant.entity_id,
			"view_angle": variant.view_angle,
			"shot_id": variant.shot_id,
			"scene_id": variant.scene_id,
			"prompt_text": variant.prompt_text,
			"negative_prompt_text": variant.negative_prompt_text,
			"preview_variant_id": regenerated_variant_id,
			"regenerate_from_variant_id": variant.id,
		}
		job = Job(
			id=regenerated_job_id,
			tenant_id=run.tenant_id,
			project_id=run.project_id,
			run_id=run.id,
			chapter_id=run.chapter_id,
			shot_id=variant.shot_id,
			job_type=JobType.render_video,
			stage=RenderStage.execute,
			status=JobStatus.queued,
			payload_json=payload,
			idempotency_key=idem,
		)
		db.add(job)
		new_variant = EntityPreviewVariant(
			id=regenerated_variant_id,
			tenant_id=variant.tenant_id,
			project_id=variant.project_id,
			trace_id=variant.trace_id,
			correlation_id=variant.correlation_id,
			idempotency_key=idem,
			run_id=variant.run_id,
			entity_id=variant.entity_id,
			shot_id=variant.shot_id,
			scene_id=variant.scene_id,
			view_angle=variant.view_angle,
			generation_backend=variant.generation_backend,
			status="queued",
			dispatch_job_id=regenerated_job_id,
			prompt_text=variant.prompt_text,
			negative_prompt_text=variant.negative_prompt_text,
			regenerate_from_variant_id=variant.id,
		)
		db.add(new_variant)
		envelope = _build_event(
			run=run,
			job=job,
			payload={
				"job_id": regenerated_job_id,
				"run_id": run.id,
				"preview_mode": True,
				"preview_variant_id": regenerated_variant_id,
				"regenerate_from_variant_id": variant.id,
			},
			now=now,
		)
		publish(SYSTEM_TOPICS.JOB_DISPATCH, envelope.model_dump(mode="json"))

	db.commit()
	return ReviewPreviewVariantResponse(
		variant_id=variant.id,
		status=variant.status,
		continuity_profile_id=continuity_profile_id,
		regenerated_variant_id=regenerated_variant_id,
		regenerated_job_id=regenerated_job_id,
	)


@router.get("/projects/{project_id}/entities/{entity_id}/continuity-profile", response_model=ContinuityProfileResponse)
def get_continuity_profile(project_id: str, entity_id: str, db: Session = Depends(get_db)) -> ContinuityProfileResponse:
	stmt = select(EntityContinuityProfile).where(
		EntityContinuityProfile.project_id == project_id,
		EntityContinuityProfile.entity_id == entity_id,
		EntityContinuityProfile.deleted_at.is_(None),
	)
	profile = db.execute(stmt).scalars().first()
	if profile is None:
		raise HTTPException(status_code=404, detail="continuity profile not found")
	return ContinuityProfileResponse(
		id=profile.id,
		entity_id=profile.entity_id,
		project_id=profile.project_id,
		continuity_status=profile.continuity_status,
		locked_preview_variant_id=profile.locked_preview_variant_id,
		anchors_json=profile.anchors_json,
		rules_json=profile.rules_json,
	)


@router.get("/projects/{project_id}/entities/{entity_id}/voice-binding", response_model=VoiceBindingResponse)
def get_voice_binding(
	project_id: str,
	entity_id: str,
	language_code: str = Query(default="zh-CN"),
	db: Session = Depends(get_db),
) -> VoiceBindingResponse:
	stmt = select(CharacterVoiceBinding).where(
		CharacterVoiceBinding.project_id == project_id,
		CharacterVoiceBinding.entity_id == entity_id,
		CharacterVoiceBinding.language_code == language_code,
		CharacterVoiceBinding.deleted_at.is_(None),
	)
	binding = db.execute(stmt).scalars().first()
	if binding is None:
		raise HTTPException(status_code=404, detail="voice binding not found")
	return VoiceBindingResponse(
		id=binding.id,
		entity_id=binding.entity_id,
		project_id=binding.project_id,
		language_code=binding.language_code,
		voice_id=binding.voice_id,
		tts_model=binding.tts_model,
		provider=binding.provider,
		locked=binding.locked,
		notes=binding.notes,
	)


@router.put("/projects/{project_id}/entities/{entity_id}/voice-binding", response_model=VoiceBindingResponse)
def upsert_voice_binding(
	project_id: str,
	entity_id: str,
	body: VoiceBindingRequest,
	db: Session = Depends(get_db),
) -> VoiceBindingResponse:
	entity = db.get(Entity, entity_id)
	if entity is None or entity.project_id != project_id:
		raise HTTPException(status_code=404, detail="entity not found")

	stmt = select(CharacterVoiceBinding).where(
		CharacterVoiceBinding.project_id == project_id,
		CharacterVoiceBinding.entity_id == entity_id,
		CharacterVoiceBinding.language_code == body.language_code,
		CharacterVoiceBinding.deleted_at.is_(None),
	)
	binding = db.execute(stmt).scalars().first()
	if binding is None:
		binding = CharacterVoiceBinding(
			id=f"cvb_{uuid4().hex[:16]}",
			tenant_id=entity.tenant_id,
			project_id=project_id,
			trace_id=entity.trace_id,
			correlation_id=entity.correlation_id,
			idempotency_key=f"voice_binding_{entity_id}_{body.language_code}",
			entity_id=entity_id,
			language_code=body.language_code,
			voice_id=body.voice_id,
			tts_model=body.tts_model,
			provider=body.provider,
			locked=body.locked,
			notes=body.notes,
		)
		db.add(binding)
	else:
		binding.voice_id = body.voice_id
		binding.tts_model = body.tts_model
		binding.provider = body.provider
		binding.locked = body.locked
		binding.notes = body.notes
	db.commit()
	return VoiceBindingResponse(
		id=binding.id,
		entity_id=binding.entity_id,
		project_id=binding.project_id,
		language_code=binding.language_code,
		voice_id=binding.voice_id,
		tts_model=binding.tts_model,
		provider=binding.provider,
		locked=binding.locked,
		notes=binding.notes,
	)
