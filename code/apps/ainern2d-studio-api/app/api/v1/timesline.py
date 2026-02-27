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
from app.services.telegram_notify import notify_telegram_event

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


class TimelinePatchHistoryItem(BaseModel):
    patch_id: str
    patch_type: str
    track: str | None = None
    shot_id: str | None = None
    patch_text: str | None = None
    parent_patch_id: str | None = None
    rollback_to_patch_id: str | None = None
    requested_by: str | None = None
    requested_at: str | None = None
    created_at: datetime


class TimelinePatchRollbackRequest(BaseModel):
    tenant_id: str
    project_id: str
    requested_by: str | None = None


class TimelinePatchRollbackResponse(BaseModel):
    run_id: str
    rollback_patch_id: str
    job_id: str
    status: str
    message: str


class PatchHistoryTreeNode(BaseModel):
    patch_id: str
    patch_type: str
    shot_id: str | None = None
    track: str | None = None
    parent_patch_id: str | None = None
    children_patch_ids: list[str] = []
    rollback_target_id: str | None = None
    patch_text: str | None = None
    requested_by: str | None = None
    requested_at: str | None = None
    created_at: datetime
    depth: int = 0


class PatchHistoryTreeResponse(BaseModel):
    run_id: str
    root_nodes: list[PatchHistoryTreeNode] = []
    all_nodes: dict[str, PatchHistoryTreeNode] = Field(default_factory=dict)
    total_patches: int = 0
    tree_height: int = 0


class RollbackComparisonDetail(BaseModel):
    field: str
    before_value: str | None = None
    after_value: str | None = None
    change_type: str  # added|removed|modified
    importance: str = "normal"  # critical|high|normal|low


class RollbackComparisonResponse(BaseModel):
    patch_id: str
    rollback_from_patch_id: str | None = None
    shot_id: str | None = None
    track: str | None = None
    before_snapshot: dict = Field(default_factory=dict)
    after_snapshot: dict = Field(default_factory=dict)
    changes: list[RollbackComparisonDetail] = []
    similarity_score: float = 0.0  # 0.0-1.0, how similar before and after are
    change_summary: str = ""
    created_at: datetime


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
    parent_patch = db.execute(
        select(RunPatchRecord)
        .where(
            RunPatchRecord.run_id == run_id,
            RunPatchRecord.deleted_at.is_(None),
            RunPatchRecord.patch_json["shot_id"].astext == body.shot_id,
        )
        .order_by(RunPatchRecord.created_at.desc())
        .limit(1)
    ).scalars().first()

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
            "parent_patch_id": parent_patch.id if parent_patch else None,
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
    notify_telegram_event(
        db=db,
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        event_type="job.created",
        summary="Timeline patch queued",
        run_id=run_id,
        job_id=job.id,
        trace_id=run.trace_id,
        correlation_id=run.correlation_id,
        extra={
            "patch_id": patch.id,
            "patch_scope": body.patch_scope,
            "track": body.track,
            "shot_id": body.shot_id,
        },
    )

    return TimelinePatchResponse(
        run_id=run_id,
        patch_id=patch.id,
        job_id=job.id,
        status="queued",
        message="timeline patch accepted; rerun-shot queued",
    )


@router.get("/runs/{run_id}/timeline/patches", response_model=list[TimelinePatchHistoryItem])
def list_timeline_patches(
    run_id: str,
    limit: int = 50,
    db: Session = Depends(get_db),
) -> list[TimelinePatchHistoryItem]:
    run = db.get(RenderRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    rows = db.execute(
        select(RunPatchRecord)
        .where(
            RunPatchRecord.run_id == run_id,
            RunPatchRecord.deleted_at.is_(None),
        )
        .order_by(RunPatchRecord.created_at.desc())
        .limit(max(1, min(limit, 200)))
    ).scalars().all()
    items: list[TimelinePatchHistoryItem] = []
    for row in rows:
        payload = row.patch_json or {}
        items.append(
            TimelinePatchHistoryItem(
                patch_id=row.id,
                patch_type=row.patch_type,
                track=payload.get("track"),
                shot_id=payload.get("shot_id"),
                patch_text=payload.get("patch_text"),
                parent_patch_id=payload.get("parent_patch_id"),
                rollback_to_patch_id=payload.get("rollback_to_patch_id"),
                requested_by=payload.get("requested_by"),
                requested_at=payload.get("requested_at"),
                created_at=row.created_at or datetime.now(timezone.utc),
            )
        )
    return items


@router.post(
    "/runs/{run_id}/timeline/patches/{patch_id}/rollback",
    response_model=TimelinePatchRollbackResponse,
)
def rollback_timeline_patch(
    run_id: str,
    patch_id: str,
    body: TimelinePatchRollbackRequest,
    db: Session = Depends(get_db),
) -> TimelinePatchRollbackResponse:
    run = db.get(RenderRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if run.tenant_id != body.tenant_id or run.project_id != body.project_id:
        raise HTTPException(status_code=403, detail="AUTH-FORBIDDEN-002: run scope mismatch")

    target = db.execute(
        select(RunPatchRecord).where(
            RunPatchRecord.id == patch_id,
            RunPatchRecord.run_id == run_id,
            RunPatchRecord.deleted_at.is_(None),
        )
    ).scalars().first()
    if target is None:
        raise HTTPException(status_code=404, detail="patch not found")

    source_payload = target.patch_json or {}
    shot_id = str(source_payload.get("shot_id") or "").strip()
    patch_text = str(source_payload.get("patch_text") or "").strip()
    track = str(source_payload.get("track") or "prompt").strip() or "prompt"
    if not shot_id or not patch_text:
        raise HTTPException(status_code=400, detail="REQ-VALIDATION-001: rollback patch payload invalid")

    parent_patch = db.execute(
        select(RunPatchRecord)
        .where(
            RunPatchRecord.run_id == run_id,
            RunPatchRecord.deleted_at.is_(None),
            RunPatchRecord.patch_json["shot_id"].astext == shot_id,
        )
        .order_by(RunPatchRecord.created_at.desc())
        .limit(1)
    ).scalars().first()
    rollback_patch = RunPatchRecord(
        id=f"patch_{uuid4().hex}",
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        trace_id=run.trace_id,
        correlation_id=run.correlation_id,
        idempotency_key=f"idem_patch_rollback_{run_id}_{shot_id}_{uuid4().hex[:8]}",
        run_id=run_id,
        stage=RenderStage.plan,
        patch_type="rollback",
        patch_json={
            "track": track,
            "shot_id": shot_id,
            "patch_text": patch_text,
            "rollback_to_patch_id": patch_id,
            "parent_patch_id": parent_patch.id if parent_patch else None,
            "requested_by": body.requested_by,
            "requested_at": datetime.now(timezone.utc).isoformat(),
        },
        applied_by=body.requested_by,
    )
    db.add(rollback_patch)

    job = Job(
        id=f"job_{uuid4().hex}",
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        run_id=run_id,
        chapter_id=run.chapter_id,
        shot_id=shot_id,
        trace_id=run.trace_id,
        correlation_id=run.correlation_id,
        idempotency_key=f"idem_timeline_rollback_job_{run_id}_{shot_id}_{uuid4().hex[:8]}",
        job_type=JobType.render_video,
        stage=RenderStage.execute,
        status=JobStatus.queued,
        payload_json={
            "patch_source": "timeline_editor_rollback",
            "patch_id": rollback_patch.id,
            "patch_scope": "rollback",
            "track": track,
            "patch_text": patch_text,
            "shot_id": shot_id,
            "regenerate": True,
            "rollback_to_patch_id": patch_id,
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
            "shot_id": shot_id,
            "patch_id": rollback_patch.id,
            "patch_text": patch_text,
            "track": track,
            "regenerate": True,
            "rollback_to_patch_id": patch_id,
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
    notify_telegram_event(
        db=db,
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        event_type="job.created",
        summary="Timeline patch rollback queued",
        run_id=run_id,
        job_id=job.id,
        trace_id=run.trace_id,
        correlation_id=run.correlation_id,
        extra={
            "rollback_patch_id": rollback_patch.id,
            "rollback_to_patch_id": patch_id,
            "track": track,
            "shot_id": shot_id,
        },
    )
    return TimelinePatchRollbackResponse(
        run_id=run_id,
        rollback_patch_id=rollback_patch.id,
        job_id=job.id,
        status="queued",
        message="timeline rollback accepted; rerun-shot queued",
    )


@router.get("/runs/{run_id}/timeline/patch-history-tree", response_model=PatchHistoryTreeResponse)
def get_patch_history_tree(
    run_id: str,
    db: Session = Depends(get_db),
) -> PatchHistoryTreeResponse:
    """Get patch history as a tree structure showing lineage and relationships."""
    run = db.get(RenderRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")

    # Fetch all patches for this run
    all_patches = db.execute(
        select(RunPatchRecord)
        .where(
            RunPatchRecord.run_id == run_id,
            RunPatchRecord.deleted_at.is_(None),
        )
        .order_by(RunPatchRecord.created_at.asc())
    ).scalars().all()

    # Build tree structure
    nodes_dict: dict[str, PatchHistoryTreeNode] = {}
    root_node_ids: list[str] = []

    for patch in all_patches:
        payload = patch.patch_json or {}
        node = PatchHistoryTreeNode(
            patch_id=patch.id,
            patch_type=patch.patch_type,
            shot_id=payload.get("shot_id"),
            track=payload.get("track"),
            parent_patch_id=payload.get("parent_patch_id"),
            rollback_target_id=payload.get("rollback_to_patch_id"),
            patch_text=payload.get("patch_text"),
            requested_by=payload.get("requested_by"),
            requested_at=payload.get("requested_at"),
            created_at=patch.created_at or datetime.now(timezone.utc),
            depth=0,
        )
        nodes_dict[patch.id] = node

    # Calculate depths and build parent-child relationships
    def calculate_depth(node_id: str, visited: set[str] | None = None) -> int:
        if visited is None:
            visited = set()
        if node_id in visited:
            return 0
        visited.add(node_id)

        node = nodes_dict.get(node_id)
        if not node or not node.parent_patch_id:
            return 0

        parent = nodes_dict.get(node.parent_patch_id)
        if not parent:
            return 1

        return 1 + calculate_depth(node.parent_patch_id, visited)

    # Build relationships
    for patch_id, node in nodes_dict.items():
        node.depth = calculate_depth(patch_id)
        if not node.parent_patch_id:
            root_node_ids.append(patch_id)
        else:
            parent_node = nodes_dict.get(node.parent_patch_id)
            if parent_node and patch_id not in parent_node.children_patch_ids:
                parent_node.children_patch_ids.append(patch_id)

    root_nodes = [nodes_dict[rid] for rid in root_node_ids if rid in nodes_dict]
    max_depth = max([node.depth for node in nodes_dict.values()]) if nodes_dict else 0

    return PatchHistoryTreeResponse(
        run_id=run_id,
        root_nodes=root_nodes,
        all_nodes=nodes_dict,
        total_patches=len(all_patches),
        tree_height=max_depth + 1,
    )


@router.get("/runs/{run_id}/timeline/patches/{patch_id}/rollback-comparison", response_model=RollbackComparisonResponse)
def get_rollback_comparison(
    run_id: str,
    patch_id: str,
    db: Session = Depends(get_db),
) -> RollbackComparisonResponse:
    """Get detailed comparison of versions before and after rollback."""
    run = db.get(RenderRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")

    patch = db.get(RunPatchRecord, patch_id)
    if patch is None or patch.run_id != run_id:
        raise HTTPException(status_code=404, detail="patch not found")

    payload = patch.patch_json or {}
    rollback_target_id = payload.get("rollback_to_patch_id")

    # Get the patch being rolled back from (if this is a rollback patch)
    before_snapshot: dict = {}
    after_snapshot: dict = {}
    rollback_from_patch_id: str | None = None

    if rollback_target_id:
        # This is a rollback patch, compare with target
        target_patch = db.get(RunPatchRecord, rollback_target_id)
        if target_patch:
            target_payload = target_patch.patch_json or {}
            before_snapshot = {
                "patch_text": target_payload.get("patch_text"),
                "track": target_payload.get("track"),
                "shot_id": target_payload.get("shot_id"),
            }
            rollback_from_patch_id = rollback_target_id
    else:
        # This is a regular patch, get parent as before
        parent_patch_id = payload.get("parent_patch_id")
        if parent_patch_id:
            parent_patch = db.get(RunPatchRecord, parent_patch_id)
            if parent_patch:
                parent_payload = parent_patch.patch_json or {}
                before_snapshot = {
                    "patch_text": parent_payload.get("patch_text"),
                    "track": parent_payload.get("track"),
                    "shot_id": parent_payload.get("shot_id"),
                }

    after_snapshot = {
        "patch_text": payload.get("patch_text"),
        "track": payload.get("track"),
        "shot_id": payload.get("shot_id"),
    }

    # Calculate changes
    changes: list[RollbackComparisonDetail] = []
    if before_snapshot.get("patch_text") != after_snapshot.get("patch_text"):
        before_text = str(before_snapshot.get("patch_text") or "")
        after_text = str(after_snapshot.get("patch_text") or "")

        changes.append(RollbackComparisonDetail(
            field="patch_text",
            before_value=before_text[:100] if before_text else None,
            after_value=after_text[:100] if after_text else None,
            change_type="modified" if before_text and after_text else ("added" if after_text else "removed"),
            importance="critical",
        ))

    if before_snapshot.get("track") != after_snapshot.get("track"):
        changes.append(RollbackComparisonDetail(
            field="track",
            before_value=before_snapshot.get("track"),
            after_value=after_snapshot.get("track"),
            change_type="modified",
            importance="high",
        ))

    # Calculate similarity score
    similarity_score = 1.0
    if before_text and after_text:
        matching_chars = sum(1 for a, b in zip(before_text, after_text) if a == b)
        similarity_score = matching_chars / max(len(before_text), len(after_text))
    elif before_text or after_text:
        similarity_score = 0.5

    change_summary = f"{len(changes)} change(s): " + ", ".join([c.field for c in changes[:3]])

    return RollbackComparisonResponse(
        patch_id=patch_id,
        rollback_from_patch_id=rollback_from_patch_id,
        shot_id=payload.get("shot_id"),
        track=payload.get("track"),
        before_snapshot=before_snapshot,
        after_snapshot=after_snapshot,
        changes=changes,
        similarity_score=round(similarity_score, 2),
        change_summary=change_summary,
        created_at=patch.created_at or datetime.now(timezone.utc),
    )
