from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.content_models import Shot
from ainern2d_shared.ainer_db_models.enum_models import JobStatus, JobType, RenderStage, RunStatus
from ainern2d_shared.ainer_db_models.pipeline_models import Job, RenderRun
from ainern2d_shared.queue.topics import SYSTEM_TOPICS
from ainern2d_shared.schemas.events import EventEnvelope

from app.api.deps import get_db, publish

router = APIRouter(prefix="/api/v1", tags=["regenerate"])


class RegenerateRunRequest(BaseModel):
    shot_ids: Optional[list[str]] = Field(None, description="Specific shots to regenerate; if None regenerate all")


class RegenerateResponse(BaseModel):
    run_id: str
    jobs_created: int
    message: str = "regeneration queued"


@router.post("/runs/{run_id}/regenerate", response_model=RegenerateResponse)
def regenerate_run(
    run_id: str,
    body: RegenerateRunRequest | None = None,
    db: Session = Depends(get_db),
) -> RegenerateResponse:
    run = db.get(RenderRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")

    if body and body.shot_ids:
        stmt = select(Shot).where(Shot.id.in_(body.shot_ids))
    else:
        stmt = select(Shot).filter_by(chapter_id=run.chapter_id)
    shots = db.execute(stmt).scalars().all()

    jobs_created = 0
    now = datetime.now(timezone.utc)
    for shot in shots:
        job = Job(
            id=f"job_{uuid4().hex}",
            tenant_id=run.tenant_id,
            project_id=run.project_id,
            run_id=run_id,
            chapter_id=run.chapter_id,
            shot_id=shot.id,
            job_type=JobType.render_video,
            stage=RenderStage.execute,
            status=JobStatus.queued,
            payload_json={"regenerate": True, "shot_id": shot.id},
            idempotency_key=f"regen_{run_id}_{shot.id}_{uuid4().hex[:8]}",
        )
        db.add(job)
        jobs_created += 1

        envelope = EventEnvelope(
            event_type="job.dispatch",
            producer="studio-api",
            occurred_at=now,
            tenant_id=run.tenant_id,
            project_id=run.project_id,
            idempotency_key=job.idempotency_key or "",
            run_id=run_id,
            job_id=job.id,
            trace_id=run.trace_id or "",
            correlation_id=run.correlation_id or "",
            payload={"job_id": job.id, "shot_id": shot.id, "regenerate": True},
        )
        publish(SYSTEM_TOPICS.JOB_DISPATCH, envelope.model_dump(mode="json"))

    # Reset run status
    run.status = RunStatus.running
    run.stage = RenderStage.execute
    db.commit()

    return RegenerateResponse(run_id=run_id, jobs_created=jobs_created)


@router.post("/shots/{shot_id}/regenerate", response_model=RegenerateResponse)
def regenerate_shot(
    shot_id: str,
    db: Session = Depends(get_db),
) -> RegenerateResponse:
    shot = db.get(Shot, shot_id)
    if shot is None:
        raise HTTPException(status_code=404, detail="shot not found")

    # Find the latest run for this chapter
    stmt = (
        select(RenderRun)
        .filter_by(chapter_id=shot.chapter_id, deleted_at=None)
        .order_by(RenderRun.created_at.desc())
        .limit(1)
    )
    run = db.execute(stmt).scalars().first()
    if run is None:
        raise HTTPException(status_code=404, detail="no run found for this shot's chapter")

    now = datetime.now(timezone.utc)
    job = Job(
        id=f"job_{uuid4().hex}",
        tenant_id=run.tenant_id,
        project_id=run.project_id,
        run_id=run.id,
        chapter_id=run.chapter_id,
        shot_id=shot_id,
        job_type=JobType.render_video,
        stage=RenderStage.execute,
        status=JobStatus.queued,
        payload_json={"regenerate": True, "shot_id": shot_id},
        idempotency_key=f"regen_{run.id}_{shot_id}_{uuid4().hex[:8]}",
    )
    db.add(job)

    envelope = EventEnvelope(
        event_type="job.dispatch",
        producer="studio-api",
        occurred_at=now,
        tenant_id=run.tenant_id,
        project_id=run.project_id,
        idempotency_key=job.idempotency_key or "",
        run_id=run.id,
        job_id=job.id,
        trace_id=run.trace_id or "",
        correlation_id=run.correlation_id or "",
        payload={"job_id": job.id, "shot_id": shot_id, "regenerate": True},
    )
    publish(SYSTEM_TOPICS.JOB_DISPATCH, envelope.model_dump(mode="json"))
    db.commit()

    return RegenerateResponse(run_id=run.id, jobs_created=1)
