from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.content_models import Artifact, TimelineSegment
from ainern2d_shared.ainer_db_models.pipeline_models import RenderRun
from ainern2d_shared.schemas.timeline import (
    TimelineAudioItemDto,
    TimelinePlanDto,
    TimelineVideoItemDto,
)

from app.api.deps import get_db

router = APIRouter(prefix="/api/v1", tags=["timeline"])


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

    video_tracks: list[TimelineVideoItemDto] = []
    audio_tracks: list[TimelineAudioItemDto] = []
    max_end = 0

    for seg in segments:
        if seg.end_ms > max_end:
            max_end = seg.end_ms
        if seg.track in ("video", "lipsync"):
            video_tracks.append(
                TimelineVideoItemDto(
                    id=seg.id,
                    shot_id=seg.shot_id or "",
                    scene_id=(seg.meta_json or {}).get("scene_id", ""),
                    start_time_ms=seg.start_ms,
                    duration_ms=seg.end_ms - seg.start_ms,
                    artifact_uri=None,
                )
            )
        elif seg.track in ("audio", "bgm", "sfx", "dialogue"):
            audio_tracks.append(
                TimelineAudioItemDto(
                    id=seg.id,
                    role=seg.track,
                    start_time_ms=seg.start_ms,
                    duration_ms=seg.end_ms - seg.start_ms,
                )
            )

    return TimelinePlanDto(
        run_id=run_id,
        total_duration_ms=max_end,
        video_tracks=video_tracks,
        audio_tracks=audio_tracks,
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

    # Delete existing segments for this run
    existing = (
        db.execute(select(TimelineSegment).filter_by(run_id=run_id)).scalars().all()
    )
    for seg in existing:
        db.delete(seg)
    db.flush()

    # Re-create from provided plan
    from uuid import uuid4

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
