"""
NLE Timeline Projects — Sprint 1 Implementation
- GET  /api/v1/runs/{run_id}/artifacts-manifest  → 完整素材清单（shots/dialogue/bgm/sfx）
- POST /api/v1/timeline/projects                 → 从 run_id 创建工程
- GET  /api/v1/timeline/projects/{project_id}    → 读取工程
- PUT  /api/v1/timeline/projects/{project_id}    → 保存工程编辑
- POST /api/v1/timeline/projects/{project_id}/assemble → 重新自动装配
- POST /api/v1/runs/{run_id}/regenerate          → 触发 shot 重生成
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.content_models import Artifact, Dialogue, PromptPlan, Shot
from ainern2d_shared.ainer_db_models.enum_models import ArtifactType, JobStatus, JobType, RenderStage, RunStatus
from ainern2d_shared.ainer_db_models.pipeline_models import Job, RenderRun, RunPatchRecord, WorkflowEvent
from ainern2d_shared.queue.topics import SYSTEM_TOPICS
from ainern2d_shared.schemas.events import EventEnvelope

from app.api.deps import get_db, publish
from ainern2d_shared.telemetry.logging import get_logger

router = APIRouter(prefix="/api/v1", tags=["nle-projects"])
logger = get_logger("nle_projects")


# ─── Shared Asset DTOs ────────────────────────────────────────────────────────

class AssetCandidate(BaseModel):
    asset_id: str
    url: str
    duration_sec: float = 0.0
    type: str = "video"


class ShotManifest(BaseModel):
    shot_id: str
    order: int
    duration_sec: float = 5.0
    title: str = ""
    prompt: str = ""
    video_candidates: list[AssetCandidate] = Field(default_factory=list)
    storyboard_image: AssetCandidate | None = None


class DialogueManifest(BaseModel):
    dialogue_id: str
    shot_id: str | None = None
    speaker_persona: str = ""
    text: str = ""
    tts_candidates: list[AssetCandidate] = Field(default_factory=list)
    at_sec_in_shot: float | None = None


class BgmManifest(BaseModel):
    asset_id: str
    url: str
    suggest_range: dict = Field(default_factory=dict)  # {shot_from, shot_to}
    duration_sec: float = 0.0


class SfxManifest(BaseModel):
    asset_id: str
    url: str
    shot_id: str | None = None
    at_sec_in_shot: float = 0.0


class RunArtifactsManifest(BaseModel):
    run_id: str
    fps: int = 24
    resolution: dict = Field(default_factory=lambda: {"w": 1280, "h": 720})
    total_duration_sec: float = 0.0
    shots: list[ShotManifest] = Field(default_factory=list)
    dialogues: list[DialogueManifest] = Field(default_factory=list)
    bgm: list[BgmManifest] = Field(default_factory=list)
    sfx: list[SfxManifest] = Field(default_factory=list)


# ─── TimelineProject DTOs ─────────────────────────────────────────────────────

class TrackDef(BaseModel):
    track_id: str
    type: str  # video | audio | text | overlay | storyboard
    name: str
    order: int


class ClipDef(BaseModel):
    clip_id: str
    track_id: str
    asset_id: str | None = None
    kind: str  # video | audio | text | storyboard
    start: float   # seconds
    end: float     # seconds
    offset_in_asset: float = 0.0
    speed: float = 1.0
    volume: float = 1.0
    fade_in: float = 0.0
    fade_out: float = 0.0
    meta: dict = Field(default_factory=dict)  # shot_id, dialogue_id, prompt, title, etc.


class TimelineProjectPayload(BaseModel):
    run_id: str
    fps: int = 24
    resolution: dict = Field(default_factory=lambda: {"w": 1280, "h": 720})
    tracks: list[TrackDef] = Field(default_factory=list)
    clips: list[ClipDef] = Field(default_factory=list)
    bindings: dict = Field(default_factory=dict)  # {shot_id: [clip_id], dialogue_id: [clip_id]}
    total_duration_sec: float = 0.0


class TimelineProjectResponse(BaseModel):
    project_id: str
    tenant_id: str
    project_scope_id: str
    run_id: str
    created_at: str
    updated_at: str
    payload: TimelineProjectPayload


class CreateProjectRequest(BaseModel):
    tenant_id: str
    project_id: str
    run_id: str
    auto_assemble: bool = True


# ─── Regenerate DTOs ──────────────────────────────────────────────────────────

class RegenerateRequest(BaseModel):
    tenant_id: str
    project_id: str
    shot_id: str
    prompt_patch: str = ""
    quality: str = "standard"
    target_duration_sec: float | None = None


class RegenerateResponse(BaseModel):
    run_id: str
    shot_id: str
    job_id: str
    status: str
    message: str


# ─── Auto Assembler ───────────────────────────────────────────────────────────

def _assemble_project_from_manifest(manifest: RunArtifactsManifest) -> TimelineProjectPayload:
    """
    Auto-assemble timeline project from a run artifacts manifest.
    Sprint 1 logic: sequential shot arrangement, default candidates.
    """
    tracks = [
        TrackDef(track_id="t-storyboard", type="storyboard", name="Storyboard", order=0),
        TrackDef(track_id="t-video",      type="video",      name="Video Clips", order=1),
        TrackDef(track_id="t-dialogue",   type="audio",      name="Dialogue Audio", order=2),
        TrackDef(track_id="t-sfx",        type="audio",      name="SFX", order=3),
        TrackDef(track_id="t-bgm",        type="audio",      name="BGM", order=4),
        TrackDef(track_id="t-subtitle",   type="text",       name="Subtitles", order=5),
    ]

    clips: list[ClipDef] = []
    bindings: dict = {}

    # Sort shots by order
    sorted_shots = sorted(manifest.shots, key=lambda s: s.order)
    
    shot_start_times: dict[str, float] = {}
    cursor = 0.0

    for shot in sorted_shots:
        shot_start_times[shot.shot_id] = cursor
        shot_end = cursor + shot.duration_sec

        # Storyboard clip
        if shot.storyboard_image:
            storyboard_clip_id = f"c-sb-{shot.shot_id}"
            clips.append(ClipDef(
                clip_id=storyboard_clip_id,
                track_id="t-storyboard",
                asset_id=shot.storyboard_image.asset_id,
                kind="storyboard",
                start=cursor,
                end=shot_end,
                meta={"shot_id": shot.shot_id, "title": shot.title, "prompt": shot.prompt},
            ))

        # Video clip — use first candidate
        video_clip_id = f"c-vid-{shot.shot_id}"
        vid_asset_id: str | None = None
        vid_url = ""
        if shot.video_candidates:
            best_cand = shot.video_candidates[0]
            vid_asset_id = best_cand.asset_id
            vid_url = best_cand.url
            # Auto speed adjust if candidate duration doesn't match shot
            cand_dur = best_cand.duration_sec or shot.duration_sec
            speed = cand_dur / shot.duration_sec if shot.duration_sec > 0 else 1.0
            # Clamp speed to [0.5, 2.0]
            speed = max(0.5, min(2.0, speed))
        else:
            speed = 1.0

        clips.append(ClipDef(
            clip_id=video_clip_id,
            track_id="t-video",
            asset_id=vid_asset_id,
            kind="video",
            start=cursor,
            end=shot_end,
            speed=speed,
            meta={"shot_id": shot.shot_id, "title": shot.title, "prompt": shot.prompt, "url": vid_url},
        ))

        bindings[shot.shot_id] = (bindings.get(shot.shot_id) or []) + [video_clip_id]

        cursor = shot_end

    # Dialogue clips — place in dialogue track
    dialogue_cursor_by_shot: dict[str, float] = {}
    for dlg in manifest.dialogues:
        bound_shot_start = shot_start_times.get(dlg.shot_id or "", 0.0) if dlg.shot_id else 0.0
        if dlg.at_sec_in_shot is not None:
            dlg_start = bound_shot_start + dlg.at_sec_in_shot
        else:
            prev_end = dialogue_cursor_by_shot.get(dlg.shot_id or "_", bound_shot_start)
            dlg_start = prev_end

        tts_dur = 2.0
        if dlg.tts_candidates:
            tts_dur = dlg.tts_candidates[0].duration_sec or 2.0
        dlg_end = dlg_start + tts_dur

        dlg_clip_id = f"c-dlg-{dlg.dialogue_id}"
        tts_asset_id = dlg.tts_candidates[0].asset_id if dlg.tts_candidates else None
        clips.append(ClipDef(
            clip_id=dlg_clip_id,
            track_id="t-dialogue",
            asset_id=tts_asset_id,
            kind="audio",
            start=dlg_start,
            end=dlg_end,
            meta={"dialogue_id": dlg.dialogue_id, "text": dlg.text, "speaker": dlg.speaker_persona},
        ))
        bindings[dlg.dialogue_id] = [dlg_clip_id]
        dialogue_cursor_by_shot[dlg.shot_id or "_"] = dlg_end

    # SFX clips
    for sfx in manifest.sfx:
        s_shot_start = shot_start_times.get(sfx.shot_id or "", 0.0) if sfx.shot_id else 0.0
        sfx_start = s_shot_start + sfx.at_sec_in_shot
        sfx_clip_id = f"c-sfx-{sfx.asset_id}"
        clips.append(ClipDef(
            clip_id=sfx_clip_id,
            track_id="t-sfx",
            asset_id=sfx.asset_id,
            kind="audio",
            start=sfx_start,
            end=sfx_start + 2.0,
            meta={"url": sfx.url, "shot_id": sfx.shot_id},
        ))

    # BGM clips — with fade in/out
    for bgm in manifest.bgm:
        suggest = bgm.suggest_range
        bgm_start = shot_start_times.get(suggest.get("shot_from", ""), 0.0)
        bgm_end = cursor if not suggest.get("shot_to") else (
            shot_start_times.get(suggest["shot_to"], cursor) + 5.0
        )
        bgm_clip_id = f"c-bgm-{bgm.asset_id}"
        clips.append(ClipDef(
            clip_id=bgm_clip_id,
            track_id="t-bgm",
            asset_id=bgm.asset_id,
            kind="audio",
            start=bgm_start,
            end=bgm_end,
            fade_in=0.5,
            fade_out=0.5,
            volume=0.7,
            meta={"url": bgm.url},
        ))

    return TimelineProjectPayload(
        run_id=manifest.run_id,
        fps=manifest.fps,
        resolution=manifest.resolution,
        tracks=tracks,
        clips=clips,
        bindings=bindings,
        total_duration_sec=cursor,
    )


# ─── Manifest Builder ─────────────────────────────────────────────────────────

def _build_manifest_from_db(run_id: str, run: RenderRun, db: Session) -> RunArtifactsManifest:
    """Query DB to build a RunArtifactsManifest for auto-assembly."""
    # 1) Load all shots for this run's chapter
    shots_db: list[Shot] = []
    prompt_map: dict[str, PromptPlan] = {}
    if run.chapter_id:
        shots_db = db.execute(
            select(Shot)
            .where(Shot.chapter_id == run.chapter_id, Shot.deleted_at.is_(None))
            .order_by(Shot.shot_no.asc())
        ).scalars().all()

        plans = db.execute(
            select(PromptPlan)
            .where(PromptPlan.run_id == run_id, PromptPlan.deleted_at.is_(None))
        ).scalars().all()
        prompt_map = {p.shot_id: p for p in plans}

    # 2) Load all artifacts for this run
    artifacts = db.execute(
        select(Artifact)
        .where(Artifact.run_id == run_id, Artifact.deleted_at.is_(None))
        .order_by(Artifact.updated_at.desc())
    ).scalars().all()

    video_by_shot: dict[str, list[Artifact]] = {}
    storyboard_by_shot: dict[str, list[Artifact]] = {}
    bgm_artifacts: list[Artifact] = []
    sfx_artifacts: list[Artifact] = []
    dialogue_wavs: list[Artifact] = []

    for art in artifacts:
        if art.type == ArtifactType.shot_video:
            sid = art.shot_id or ""
            video_by_shot.setdefault(sid, []).append(art)
        elif art.type == ArtifactType.keyframe:
            sid = art.shot_id or ""
            storyboard_by_shot.setdefault(sid, []).append(art)
        elif art.type == ArtifactType.mixed_audio:
            bgm_artifacts.append(art)
        elif art.type == ArtifactType.dialogue_wav:
            dialogue_wavs.append(art)

    # 3) Load dialogues for chapter
    dialogues_db: list[Dialogue] = []
    if run.chapter_id:
        dialogues_db = db.execute(
            select(Dialogue)
            .where(Dialogue.chapter_id == run.chapter_id, Dialogue.deleted_at.is_(None))
            .order_by(Dialogue.line_no.asc())
        ).scalars().all()

    # 4) Build shot manifests
    shot_manifests: list[ShotManifest] = []
    for idx, shot in enumerate(shots_db):
        prompt_plan = prompt_map.get(shot.id)
        duration_sec = (shot.duration_ms or 5000) / 1000.0
        video_cands = [
            AssetCandidate(
                asset_id=v.id,
                url=v.uri,
                duration_sec=(v.media_meta_json or {}).get("duration_sec", duration_sec),
                type="video",
            )
            for v in video_by_shot.get(shot.id, [])[:3]  # max 3 candidates
        ]
        sb_list = storyboard_by_shot.get(shot.id, [])
        storyboard = AssetCandidate(
            asset_id=sb_list[0].id,
            url=sb_list[0].uri,
            type="image",
        ) if sb_list else None

        shot_manifests.append(ShotManifest(
            shot_id=shot.id,
            order=idx + 1,
            duration_sec=duration_sec,
            title=(shot.prompt_json or {}).get("title", f"Shot {shot.shot_no}"),
            prompt=prompt_plan.prompt_text if prompt_plan else "",
            video_candidates=video_cands,
            storyboard_image=storyboard,
        ))

    # 5) Build dialogue manifests
    dlg_manifests: list[DialogueManifest] = []
    dlg_wav_map: dict[str, Artifact] = {}
    for wav in dialogue_wavs:
        # Try to match by dialogue ID stored in meta
        dlg_id = (wav.media_meta_json or {}).get("dialogue_id")
        if dlg_id:
            dlg_wav_map[dlg_id] = wav

    for dlg in dialogues_db:
        wav = dlg_wav_map.get(dlg.id)
        tts_candidates = [
            AssetCandidate(
                asset_id=wav.id,
                url=wav.uri,
                duration_sec=(wav.media_meta_json or {}).get("duration_sec", 2.0),
                type="audio",
            )
        ] if wav else []
        dlg_manifests.append(DialogueManifest(
            dialogue_id=dlg.id,
            shot_id=None,  # Dialogue doesn't have direct shot linkage in current schema
            speaker_persona=dlg.speaker or "",
            text=dlg.content,
            tts_candidates=tts_candidates,
        ))

    # 6) BGM
    bgm_manifests = [
        BgmManifest(
            asset_id=a.id,
            url=a.uri,
            duration_sec=(a.media_meta_json or {}).get("duration_sec", 0.0),
        )
        for a in bgm_artifacts[:2]
    ]

    total_sec = sum(m.duration_sec for m in shot_manifests)

    return RunArtifactsManifest(
        run_id=run_id,
        fps=24,
        resolution={"w": 1280, "h": 720},
        total_duration_sec=total_sec,
        shots=shot_manifests,
        dialogues=dlg_manifests,
        bgm=bgm_manifests,
        sfx=sfx_manifests if (sfx_manifests := []) else [],
    )


# ─── Project storage via RunPatchRecord JSONB ─────────────────────────────────
# We reuse RunPatchRecord table with patch_type="nle_project" to avoid creating a new table in Sprint 1.

def _project_patch_type() -> str:
    return "nle_project"


# ─── API Endpoints ────────────────────────────────────────────────────────────

@router.get("/runs/{run_id}/artifacts-manifest", response_model=RunArtifactsManifest)
def get_run_artifacts_manifest(
    run_id: str,
    db: Session = Depends(get_db),
) -> RunArtifactsManifest:
    """Return a complete assembled manifest of all run artifacts (shots/dialogue/bgm/sfx)."""
    run = db.get(RenderRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return _build_manifest_from_db(run_id, run, db)


@router.post("/timeline/projects", response_model=TimelineProjectResponse, status_code=201)
def create_timeline_project(
    body: CreateProjectRequest,
    db: Session = Depends(get_db),
) -> TimelineProjectResponse:
    """Create a TimelineProject from a run_id. Optionally auto-assembles clips."""
    run = db.get(RenderRun, run_id := body.run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")

    project_payload: TimelineProjectPayload
    if body.auto_assemble:
        manifest = _build_manifest_from_db(run_id, run, db)
        project_payload = _assemble_project_from_manifest(manifest)
    else:
        project_payload = TimelineProjectPayload(run_id=run_id)

    project_id = f"nle_proj_{uuid4().hex}"
    now = datetime.now(timezone.utc)

    record = RunPatchRecord(
        id=project_id,
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        trace_id=run.trace_id or f"tr_{uuid4().hex[:12]}",
        correlation_id=run.correlation_id or f"cr_{uuid4().hex[:12]}",
        idempotency_key=f"idem_nle_proj_{run_id}_{uuid4().hex[:8]}",
        run_id=run_id,
        stage=RenderStage.compose,
        patch_type=_project_patch_type(),
        patch_json=project_payload.model_dump(),
    )
    db.add(record)
    db.commit()

    return TimelineProjectResponse(
        project_id=project_id,
        tenant_id=body.tenant_id,
        project_scope_id=body.project_id,
        run_id=run_id,
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
        payload=project_payload,
    )


@router.get("/timeline/projects/{project_id}", response_model=TimelineProjectResponse)
def get_timeline_project(
    project_id: str,
    db: Session = Depends(get_db),
) -> TimelineProjectResponse:
    record = db.get(RunPatchRecord, project_id)
    if record is None or record.patch_type != _project_patch_type() or record.deleted_at is not None:
        raise HTTPException(status_code=404, detail="timeline project not found")

    payload = TimelineProjectPayload.model_validate(record.patch_json or {})
    return TimelineProjectResponse(
        project_id=project_id,
        tenant_id=record.tenant_id,
        project_scope_id=record.project_id,
        run_id=record.run_id or "",
        created_at=record.created_at.isoformat() if record.created_at else "",
        updated_at=record.updated_at.isoformat() if record.updated_at else "",
        payload=payload,
    )


@router.put("/timeline/projects/{project_id}", response_model=TimelineProjectResponse)
def update_timeline_project(
    project_id: str,
    body: TimelineProjectPayload,
    db: Session = Depends(get_db),
) -> TimelineProjectResponse:
    record = db.get(RunPatchRecord, project_id)
    if record is None or record.patch_type != _project_patch_type() or record.deleted_at is not None:
        raise HTTPException(status_code=404, detail="timeline project not found")

    record.patch_json = body.model_dump()
    now = datetime.now(timezone.utc)
    db.commit()

    return TimelineProjectResponse(
        project_id=project_id,
        tenant_id=record.tenant_id,
        project_scope_id=record.project_id,
        run_id=record.run_id or "",
        created_at=record.created_at.isoformat() if record.created_at else "",
        updated_at=now.isoformat(),
        payload=body,
    )


@router.post("/timeline/projects/{project_id}/assemble", response_model=TimelineProjectResponse)
def reassemble_timeline_project(
    project_id: str,
    db: Session = Depends(get_db),
) -> TimelineProjectResponse:
    """Re-run auto-assembly for the project from its run artifacts."""
    record = db.get(RunPatchRecord, project_id)
    if record is None or record.patch_type != _project_patch_type() or record.deleted_at is not None:
        raise HTTPException(status_code=404, detail="timeline project not found")

    run_id = record.run_id or ""
    run = db.get(RenderRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")

    manifest = _build_manifest_from_db(run_id, run, db)
    new_payload = _assemble_project_from_manifest(manifest)
    record.patch_json = new_payload.model_dump()
    now = datetime.now(timezone.utc)
    db.commit()

    return TimelineProjectResponse(
        project_id=project_id,
        tenant_id=record.tenant_id,
        project_scope_id=record.project_id,
        run_id=run_id,
        created_at=record.created_at.isoformat() if record.created_at else "",
        updated_at=now.isoformat(),
        payload=new_payload,
    )


@router.post("/runs/{run_id}/regenerate", response_model=RegenerateResponse)
def regenerate_shot(
    run_id: str,
    body: RegenerateRequest,
    db: Session = Depends(get_db),
) -> RegenerateResponse:
    """Trigger AI regeneration for a specific shot in the timeline."""
    run = db.get(RenderRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")

    job_id = f"job_{uuid4().hex}"
    patch_id = f"patch_{uuid4().hex}"
    now = datetime.now(timezone.utc)

    patch = RunPatchRecord(
        id=patch_id,
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        trace_id=run.trace_id or f"tr_{uuid4().hex[:12]}",
        correlation_id=run.correlation_id or f"cr_{uuid4().hex[:12]}",
        idempotency_key=f"idem_regen_{run_id}_{body.shot_id}_{uuid4().hex[:8]}",
        run_id=run_id,
        stage=RenderStage.execute,
        patch_type="nle_regenerate",
        patch_json={
            "shot_id": body.shot_id,
            "prompt_patch": body.prompt_patch,
            "quality": body.quality,
            "target_duration_sec": body.target_duration_sec,
            "requested_at": now.isoformat(),
        },
    )
    db.add(patch)

    job = Job(
        id=job_id,
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        run_id=run_id,
        chapter_id=run.chapter_id,
        shot_id=body.shot_id,
        trace_id=run.trace_id,
        correlation_id=run.correlation_id,
        idempotency_key=f"idem_regen_job_{run_id}_{body.shot_id}_{uuid4().hex[:8]}",
        job_type=JobType.render_video,
        stage=RenderStage.execute,
        status=JobStatus.queued,
        payload_json={
            "patch_source": "nle_editor",
            "patch_id": patch_id,
            "shot_id": body.shot_id,
            "prompt_patch": body.prompt_patch,
            "quality": body.quality,
            "target_duration_sec": body.target_duration_sec,
            "regenerate": True,
        },
    )
    db.add(job)

    event = EventEnvelope(
        event_type="nle.shot.regenerate.requested",
        producer="studio-api",
        occurred_at=now,
        tenant_id=body.tenant_id,
        project_id=body.project_id,
        idempotency_key=job.idempotency_key or f"idem_{job.id}",
        run_id=run_id,
        job_id=job_id,
        trace_id=run.trace_id or "",
        correlation_id=run.correlation_id or "",
        payload={"shot_id": body.shot_id, "quality": body.quality, "prompt_patch": body.prompt_patch},
    )
    try:
        publish(SYSTEM_TOPICS.JOB_DISPATCH, event.model_dump(mode="json"))
    except Exception as exc:
        logger.warning("NLE regenerate publish failed: %s", exc)

    run.status = RunStatus.running
    db.commit()

    return RegenerateResponse(
        run_id=run_id,
        shot_id=body.shot_id,
        job_id=job_id,
        status="queued",
        message="NLE shot regeneration queued",
    )
