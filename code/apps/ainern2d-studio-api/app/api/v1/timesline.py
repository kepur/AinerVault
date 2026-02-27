from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.content_models import Artifact, PromptPlan, TimelineSegment
from ainern2d_shared.ainer_db_models.enum_models import JobStatus, JobType, RenderStage, RunStatus
from ainern2d_shared.ainer_db_models.governance_models import ShotDslCompilation
from ainern2d_shared.ainer_db_models.pipeline_models import Job, RenderRun, RunPatchRecord, WorkflowEvent
from ainern2d_shared.queue.topics import SYSTEM_TOPICS
from ainern2d_shared.schemas.events import EventEnvelope
from ainern2d_shared.schemas.timeline import (
    TimelineAudioItemDto,
    TimelinePlanDto,
    TimelineVideoItemDto,
)

from app.api.deps import get_db, publish

router = APIRouter(prefix="/api/v1", tags=["timeline"])


class TimelinePatchRequest(BaseModel):
    tenant_id: str
    project_id: str
    shot_id: str
    patch_text: str
    track: str = "prompt"
    patch_scope: str = "rerun-shot"
    requested_by: str | None = None


class TimelinePatchResponse(BaseModel):
    run_id: str
    patch_id: str
    job_id: str
    status: str
    message: str


@router.get("/runs/{run_id}/timeline", response_model=TimelinePlanDto)
def get_timeline(run_id: str, db: Session = Depends(get_db)) -> TimelinePlanDto:
    run = db.get(RenderRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")

    stmt = (
        select(TimelineSegment)
        .filter_by(run_id=run_id, deleted_at=None)
        .order_by(TimelineSegment.start_ms.asc())
    )
    segments = db.execute(stmt).scalars().all()

    artifact_ids = [seg.artifact_id for seg in segments if seg.artifact_id]
    artifact_map: dict[str, Artifact] = {}
    if artifact_ids:
        artifact_rows = db.execute(select(Artifact).where(Artifact.id.in_(artifact_ids))).scalars().all()
        artifact_map = {row.id: row for row in artifact_rows}

    shot_ids = [seg.shot_id for seg in segments if seg.shot_id]
    shot_asset_rows = []
    if shot_ids:
        shot_asset_rows = db.execute(
            select(Artifact)
            .where(
                Artifact.run_id == run_id,
                Artifact.shot_id.in_(shot_ids),
                Artifact.deleted_at.is_(None),
            )
            .order_by(Artifact.updated_at.desc())
        ).scalars().all()

    shot_asset_map: dict[str, Artifact] = {}
    for row in shot_asset_rows:
        if row.shot_id and row.shot_id not in shot_asset_map:
            shot_asset_map[row.shot_id] = row

    video_tracks: list[TimelineVideoItemDto] = []
    audio_tracks: list[TimelineAudioItemDto] = []
    max_end = 0

    for seg in segments:
        if seg.end_ms > max_end:
            max_end = seg.end_ms
        artifact_uri = None
        if seg.artifact_id and seg.artifact_id in artifact_map:
            artifact_uri = artifact_map[seg.artifact_id].uri
        elif seg.shot_id and seg.shot_id in shot_asset_map:
            artifact_uri = shot_asset_map[seg.shot_id].uri

        if seg.track in ("video", "lipsync"):
            video_tracks.append(
                TimelineVideoItemDto(
                    id=seg.id,
                    shot_id=seg.shot_id or "",
                    scene_id=(seg.meta_json or {}).get("scene_id", ""),
                    start_time_ms=seg.start_ms,
                    duration_ms=seg.end_ms - seg.start_ms,
                    artifact_uri=artifact_uri,
                )
            )
        elif seg.track in ("audio", "bgm", "sfx", "dialogue", "ambience"):
            audio_tracks.append(
                TimelineAudioItemDto(
                    id=seg.id,
                    role=seg.track,
                    start_time_ms=seg.start_ms,
                    duration_ms=seg.end_ms - seg.start_ms,
                    artifact_uri=artifact_uri,
                )
            )

    prompt_rows = db.execute(
        select(PromptPlan)
        .where(
            PromptPlan.run_id == run_id,
            PromptPlan.deleted_at.is_(None),
        )
        .order_by(PromptPlan.shot_id.asc())
    ).scalars().all()
    dsl_rows = db.execute(
        select(ShotDslCompilation)
        .where(
            ShotDslCompilation.run_id == run_id,
            ShotDslCompilation.deleted_at.is_(None),
        )
        .order_by(ShotDslCompilation.shot_id.asc())
    ).scalars().all()

    effect_tracks = [
        {
            "track": "prompt",
            "items": [
                {
                    "plan_id": item.id,
                    "shot_id": item.shot_id,
                    "prompt_text": item.prompt_text,
                    "negative_prompt_text": item.negative_prompt_text,
                }
                for item in prompt_rows
            ],
        },
        {
            "track": "dsl_compiled",
            "items": [
                {
                    "compilation_id": item.id,
                    "shot_id": item.shot_id,
                    "backend": item.backend,
                    "compiled_prompt_json": item.compiled_prompt_json,
                }
                for item in dsl_rows
            ],
        },
    ]

    return TimelinePlanDto(
        run_id=run_id,
        total_duration_ms=max_end,
        video_tracks=video_tracks,
        audio_tracks=audio_tracks,
        effect_tracks=effect_tracks,
    )


@router.put("/runs/{run_id}/timeline", response_model=TimelinePlanDto)
def update_timeline(
    run_id: str,
    body: TimelinePlanDto,
    db: Session = Depends(get_db),
) -> TimelinePlanDto:
    run = db.get(RenderRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")

    existing = (
        db.execute(select(TimelineSegment).filter_by(run_id=run_id)).scalars().all()
    )
    for seg in existing:
        db.delete(seg)
    db.flush()

    for v in body.video_tracks:
        seg = TimelineSegment(
            id=f"seg_{uuid4().hex}",
            tenant_id=run.tenant_id,
            project_id=run.project_id,
            run_id=run_id,
            shot_id=v.shot_id or None,
            track="video",
            start_ms=v.start_time_ms,
            end_ms=v.start_time_ms + v.duration_ms,
            meta_json={"scene_id": v.scene_id},
        )
        db.add(seg)

    for a in body.audio_tracks:
        seg = TimelineSegment(
            id=f"seg_{uuid4().hex}",
            tenant_id=run.tenant_id,
            project_id=run.project_id,
            run_id=run_id,
            track=a.role,
            start_ms=a.start_time_ms,
            end_ms=a.start_time_ms + a.duration_ms,
        )
        db.add(seg)

    db.commit()
    return body


@router.post("/runs/{run_id}/timeline/patch", response_model=TimelinePatchResponse)
def patch_timeline(
    run_id: str,
    body: TimelinePatchRequest,
    db: Session = Depends(get_db),
) -> TimelinePatchResponse:
    run = db.get(RenderRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if run.tenant_id != body.tenant_id or run.project_id != body.project_id:
        raise HTTPException(status_code=403, detail="AUTH-FORBIDDEN-002: run scope mismatch")

    patch = RunPatchRecord(
        id=f"patch_{uuid4().hex}",
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        trace_id=run.trace_id,
        correlation_id=run.correlation_id,
        idempotency_key=f"idem_patch_{run_id}_{body.shot_id}_{uuid4().hex[:8]}",
        run_id=run_id,
        stage=RenderStage.plan,
        patch_type=body.patch_scope,
        patch_json={
            "track": body.track,
            "shot_id": body.shot_id,
            "patch_text": body.patch_text,
            "requested_by": body.requested_by,
            "requested_at": datetime.now(timezone.utc).isoformat(),
        },
        applied_by=body.requested_by,
    )
    db.add(patch)

    job = Job(
        id=f"job_{uuid4().hex}",
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        run_id=run_id,
        chapter_id=run.chapter_id,
        shot_id=body.shot_id,
        trace_id=run.trace_id,
        correlation_id=run.correlation_id,
        idempotency_key=f"idem_timeline_patch_job_{run_id}_{body.shot_id}_{uuid4().hex[:8]}",
        job_type=JobType.render_video,
        stage=RenderStage.execute,
        status=JobStatus.queued,
        payload_json={
            "patch_source": "timeline_editor",
            "patch_id": patch.id,
            "patch_scope": body.patch_scope,
            "track": body.track,
            "patch_text": body.patch_text,
            "shot_id": body.shot_id,
            "regenerate": True,
        },
    )
    db.add(job)

    event = EventEnvelope(
        event_type="job.created",
        producer="studio-api",
        occurred_at=datetime.now(timezone.utc),
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        idempotency_key=job.idempotency_key or f"idem_job_{job.id}",
        run_id=run_id,
        job_id=job.id,
        trace_id=run.trace_id or "",
        correlation_id=run.correlation_id or "",
        payload={
            "job_id": job.id,
            "shot_id": body.shot_id,
            "patch_id": patch.id,
            "patch_text": body.patch_text,
            "track": body.track,
            "regenerate": True,
        },
    )
    publish(SYSTEM_TOPICS.JOB_DISPATCH, event.model_dump(mode="json"))

    db.add(
        WorkflowEvent(
            id=event.event_id,
            tenant_id=body.tenant_id,
            project_id=body.project_id,
            trace_id=run.trace_id,
            correlation_id=run.correlation_id,
            idempotency_key=event.idempotency_key,
            run_id=run_id,
            job_id=job.id,
            stage=RenderStage.execute,
            event_type="job.created",
            event_version="1.0",
            producer="studio-api",
            occurred_at=event.occurred_at,
            payload_json=event.payload,
        )
    )

    run.status = RunStatus.running
    run.stage = RenderStage.execute
    db.commit()

    return TimelinePatchResponse(
        run_id=run_id,
        patch_id=patch.id,
        job_id=job.id,
        status="queued",
        message="timeline patch accepted; rerun-shot queued",
    )
