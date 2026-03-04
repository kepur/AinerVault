from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.content_models import Artifact, Chapter, Dialogue, Shot, TimelineSegment
from ainern2d_shared.ainer_db_models.enum_models import JobStatus, JobType, RenderStage, RunStatus
from ainern2d_shared.ainer_db_models.pipeline_models import Job, RenderRun, TrackRun, TrackUnit, TrackUnitAttempt
from ainern2d_shared.queue.topics import SYSTEM_TOPICS
from ainern2d_shared.schemas.events import EventEnvelope
from app.modules.model_router.provider_registry import ProviderRegistry

from app.api.deps import get_db, publish

router = APIRouter(prefix="/api/v1", tags=["run-tracks"])

_TRACK_TO_WORKER: dict[str, str] = {
    "video": "worker-video",
    "storyboard": "worker-video",
    "tts": "worker-audio-tts",
    "dialogue": "worker-audio-tts",
    "narration": "worker-audio-tts",
    "sfx": "worker-audio-sfx",
    "ambience": "worker-audio-sfx",
    "aux": "worker-audio-sfx",
    "bgm": "worker-audio-bgm",
    "subtitle": "worker-llm",
    "lipsync": "worker-lipsync",
}

_TRACK_TO_JOB_TYPE: dict[str, JobType] = {
    "video": JobType.render_video,
    "storyboard": JobType.render_video,
    "tts": JobType.synth_audio,
    "dialogue": JobType.synth_audio,
    "narration": JobType.synth_audio,
    "sfx": JobType.synth_audio,
    "ambience": JobType.synth_audio,
    "aux": JobType.synth_audio,
    "bgm": JobType.synth_audio,
    "subtitle": JobType.plan_prompt,
    "lipsync": JobType.render_lipsync,
}

_DEFAULT_TRACKS = ["video", "tts", "sfx", "bgm"]


class InitTracksRequest(BaseModel):
    track_types: list[str] = Field(default_factory=lambda: list(_DEFAULT_TRACKS))
    recreate: bool = False


class TrackInitItem(BaseModel):
    track_type: str
    track_run_id: str
    units_created: int
    status: str


class InitTracksResponse(BaseModel):
    run_id: str
    tracks: list[TrackInitItem]


class TrackSummary(BaseModel):
    track_run_id: str
    track_type: str
    worker_type: str | None = None
    status: str
    blocked_reason: str | None = None
    total_units: int = 0
    success_units: int = 0
    failed_units: int = 0
    running_units: int = 0
    blocked_units: int = 0


class TrackUnitItem(BaseModel):
    unit_id: str
    unit_ref_id: str
    unit_kind: str
    status: str
    planned_start_ms: int | None = None
    planned_end_ms: int | None = None
    attempt_count: int
    max_attempts: int
    blocked_reason: str | None = None
    last_error_code: str | None = None
    last_error_message: str | None = None
    selected_asset_id: str | None = None
    selected_job_id: str | None = None
    output_candidates: list[dict[str, Any]] = Field(default_factory=list)


class RunTrackRequest(BaseModel):
    unit_ids: list[str] | None = None
    only_failed: bool = False
    force: bool = False


class RunTrackResponse(BaseModel):
    run_id: str
    track_type: str
    track_run_id: str
    track_status: str
    jobs_created: int
    blocked_reason: str | None = None


class RetryTrackUnitRequest(BaseModel):
    patch: dict[str, Any] = Field(default_factory=dict)


class RetryTrackUnitResponse(BaseModel):
    run_id: str
    track_run_id: str
    track_unit_id: str
    job_id: str
    status: str


class SelectTrackUnitCandidateRequest(BaseModel):
    artifact_id: str | None = None
    candidate_index: int | None = None


class SelectTrackUnitCandidateResponse(BaseModel):
    run_id: str
    track_run_id: str
    track_unit_id: str
    selected_asset_id: str
    selected_job_id: str | None = None
    status: str


class TrackUnitAttemptItem(BaseModel):
    attempt_id: str
    attempt_no: int
    trigger_type: str
    status: str
    job_id: str | None = None
    artifact_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    duration_ms: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_track(track_type: str) -> str:
    return track_type.strip().lower()


def _load_run_or_404(db: Session, run_id: str) -> RenderRun:
    run = db.get(RenderRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run


def _list_shots_for_run(db: Session, run: RenderRun) -> list[Shot]:
    return db.execute(
        select(Shot)
        .where(
            Shot.chapter_id == run.chapter_id,
            Shot.deleted_at.is_(None),
        )
        .order_by(Shot.shot_no.asc())
    ).scalars().all()


def _list_dialogues_for_run(db: Session, run: RenderRun) -> list[Dialogue]:
    return db.execute(
        select(Dialogue)
        .where(
            Dialogue.chapter_id == run.chapter_id,
            Dialogue.deleted_at.is_(None),
        )
        .order_by(Dialogue.line_no.asc())
    ).scalars().all()


def _build_shot_spans(shots: list[Shot]) -> tuple[dict[str, tuple[int, int]], int]:
    spans: dict[str, tuple[int, int]] = {}
    cursor = 0
    for shot in shots:
        dur = int(shot.duration_ms or 5000)
        start_ms = cursor
        end_ms = cursor + max(100, dur)
        spans[shot.id] = (start_ms, end_ms)
        cursor = end_ms
    return spans, cursor


def _ensure_track_run(db: Session, run: RenderRun, track_type: str) -> TrackRun:
    existing = db.execute(
        select(TrackRun)
        .where(
            TrackRun.run_id == run.id,
            TrackRun.track_type == track_type,
            TrackRun.deleted_at.is_(None),
        )
        .limit(1)
    ).scalars().first()
    if existing:
        return existing

    tr = TrackRun(
        id=f"tr_{uuid4().hex}",
        tenant_id=run.tenant_id,
        project_id=run.project_id,
        trace_id=run.trace_id,
        correlation_id=run.correlation_id,
        idempotency_key=f"idem_track_{run.id}_{track_type}",
        run_id=run.id,
        chapter_id=run.chapter_id,
        track_type=track_type,
        worker_type=_TRACK_TO_WORKER.get(track_type),
        status="queued",
    )
    db.add(tr)
    db.flush()
    return tr


def _clear_track_units(db: Session, track_run: TrackRun) -> None:
    units = db.execute(
        select(TrackUnit)
        .where(
            TrackUnit.track_run_id == track_run.id,
            TrackUnit.deleted_at.is_(None),
        )
    ).scalars().all()
    for unit in units:
        db.delete(unit)


def _clear_track_segments(db: Session, run_id: str, track_type: str) -> None:
    now = _utcnow()
    segments = db.execute(
        select(TimelineSegment)
        .where(
            TimelineSegment.run_id == run_id,
            TimelineSegment.track == track_type,
            TimelineSegment.deleted_at.is_(None),
        )
    ).scalars().all()
    for seg in segments:
        seg.deleted_at = now


def _ensure_placeholder_segment(
    db: Session,
    run: RenderRun,
    track_type: str,
    unit: TrackUnit,
) -> None:
    if unit.planned_start_ms is None or unit.planned_end_ms is None:
        return
    seg = TimelineSegment(
        id=f"seg_{uuid4().hex}",
        tenant_id=run.tenant_id,
        project_id=run.project_id,
        trace_id=run.trace_id,
        correlation_id=run.correlation_id,
        idempotency_key=f"idem_seg_{unit.id}",
        run_id=run.id,
        shot_id=unit.shot_id,
        track=track_type,
        start_ms=unit.planned_start_ms,
        end_ms=unit.planned_end_ms,
        artifact_id=None,
        meta_json={
            "track_unit_id": unit.id,
            "unit_ref_id": unit.unit_ref_id,
            "status": "planned",
        },
    )
    db.add(seg)



def _build_video_units(
    db: Session,
    run: RenderRun,
    track_run: TrackRun,
    shots: list[Shot],
    spans: dict[str, tuple[int, int]],
) -> int:
    created = 0
    for shot in shots:
        start_ms, end_ms = spans.get(shot.id, (0, int(shot.duration_ms or 5000)))
        unit = TrackUnit(
            id=f"tu_{uuid4().hex}",
            tenant_id=run.tenant_id,
            project_id=run.project_id,
            trace_id=run.trace_id,
            correlation_id=run.correlation_id,
            idempotency_key=f"idem_tu_{track_run.id}_{shot.id}",
            run_id=run.id,
            track_run_id=track_run.id,
            chapter_id=run.chapter_id,
            shot_id=shot.id,
            unit_ref_id=shot.id,
            unit_kind="shot",
            status="queued",
            planned_start_ms=start_ms,
            planned_end_ms=end_ms,
            input_payload_snapshot={
                "shot_id": shot.id,
                "prompt": (shot.prompt_json or {}).get("prompt", ""),
                "title": (shot.prompt_json or {}).get("title", f"Shot {shot.shot_no}"),
            },
        )
        db.add(unit)
        db.flush()
        _ensure_placeholder_segment(db, run, track_run.track_type, unit)
        created += 1
    return created



def _build_tts_units(
    db: Session,
    run: RenderRun,
    track_run: TrackRun,
    dialogues: list[Dialogue],
    timeline_total_ms: int,
) -> int:
    created = 0
    cursor = 0
    for dlg in dialogues:
        dur_ms = int(dlg.timing_hint_ms or 2000)
        start_ms = cursor
        end_ms = start_ms + max(300, dur_ms)
        if timeline_total_ms > 0:
            start_ms = min(start_ms, timeline_total_ms)
            end_ms = min(end_ms, timeline_total_ms)
            if end_ms <= start_ms:
                end_ms = start_ms + 300
        unit = TrackUnit(
            id=f"tu_{uuid4().hex}",
            tenant_id=run.tenant_id,
            project_id=run.project_id,
            trace_id=run.trace_id,
            correlation_id=run.correlation_id,
            idempotency_key=f"idem_tu_{track_run.id}_{dlg.id}",
            run_id=run.id,
            track_run_id=track_run.id,
            chapter_id=run.chapter_id,
            dialogue_id=dlg.id,
            unit_ref_id=dlg.id,
            unit_kind="dialogue",
            status="queued",
            planned_start_ms=start_ms,
            planned_end_ms=end_ms,
            input_payload_snapshot={
                "dialogue_id": dlg.id,
                "text": dlg.content,
                "speaker": dlg.speaker,
            },
        )
        db.add(unit)
        db.flush()
        _ensure_placeholder_segment(db, run, track_run.track_type, unit)
        created += 1
        cursor = end_ms
    return created


def _build_subtitle_units(
    db: Session,
    run: RenderRun,
    track_run: TrackRun,
    dialogues: list[Dialogue],
    timeline_total_ms: int,
) -> int:
    created = 0
    cursor = 0
    for dlg in dialogues:
        dur_ms = int(dlg.timing_hint_ms or 2000)
        start_ms = cursor
        end_ms = start_ms + max(300, dur_ms)
        if timeline_total_ms > 0:
            start_ms = min(start_ms, timeline_total_ms)
            end_ms = min(end_ms, timeline_total_ms)
            if end_ms <= start_ms:
                end_ms = start_ms + 300
        unit = TrackUnit(
            id=f"tu_{uuid4().hex}",
            tenant_id=run.tenant_id,
            project_id=run.project_id,
            trace_id=run.trace_id,
            correlation_id=run.correlation_id,
            idempotency_key=f"idem_tu_{track_run.id}_{dlg.id}",
            run_id=run.id,
            track_run_id=track_run.id,
            chapter_id=run.chapter_id,
            dialogue_id=dlg.id,
            unit_ref_id=f"{dlg.id}:subtitle",
            unit_kind="subtitle_line",
            status="queued",
            planned_start_ms=start_ms,
            planned_end_ms=end_ms,
            input_payload_snapshot={
                "dialogue_id": dlg.id,
                "text": dlg.content,
                "speaker": dlg.speaker,
                "line_break_mode": "smart",
                "max_chars_per_line": 24,
            },
        )
        db.add(unit)
        db.flush()
        _ensure_placeholder_segment(db, run, track_run.track_type, unit)
        created += 1
        cursor = end_ms
    return created


def _build_sfx_units(
    db: Session,
    run: RenderRun,
    track_run: TrackRun,
    shots: list[Shot],
    spans: dict[str, tuple[int, int]],
) -> int:
    created = 0
    for shot in shots:
        start_ms, end_ms = spans.get(shot.id, (0, int(shot.duration_ms or 5000)))
        sfx_end = min(end_ms, start_ms + 1200)
        unit = TrackUnit(
            id=f"tu_{uuid4().hex}",
            tenant_id=run.tenant_id,
            project_id=run.project_id,
            trace_id=run.trace_id,
            correlation_id=run.correlation_id,
            idempotency_key=f"idem_tu_{track_run.id}_{shot.id}",
            run_id=run.id,
            track_run_id=track_run.id,
            chapter_id=run.chapter_id,
            shot_id=shot.id,
            unit_ref_id=f"{shot.id}:sfx",
            unit_kind="event",
            status="queued",
            planned_start_ms=start_ms,
            planned_end_ms=max(start_ms + 300, sfx_end),
            input_payload_snapshot={"shot_id": shot.id},
        )
        db.add(unit)
        db.flush()
        _ensure_placeholder_segment(db, run, track_run.track_type, unit)
        created += 1
    return created



def _build_ambience_units(
    db: Session,
    run: RenderRun,
    track_run: TrackRun,
    shots: list[Shot],
    spans: dict[str, tuple[int, int]],
) -> int:
    created = 0
    for shot in shots:
        start_ms, end_ms = spans.get(shot.id, (0, int(shot.duration_ms or 5000)))
        unit = TrackUnit(
            id=f"tu_{uuid4().hex}",
            tenant_id=run.tenant_id,
            project_id=run.project_id,
            trace_id=run.trace_id,
            correlation_id=run.correlation_id,
            idempotency_key=f"idem_tu_{track_run.id}_{shot.id}",
            run_id=run.id,
            track_run_id=track_run.id,
            chapter_id=run.chapter_id,
            shot_id=shot.id,
            unit_ref_id=f"{shot.id}:ambience",
            unit_kind="segment",
            status="queued",
            planned_start_ms=start_ms,
            planned_end_ms=max(start_ms + 1000, end_ms),
            input_payload_snapshot={
                "shot_id": shot.id,
                "description": "ambient environment bed",
                "category": "ambient",
            },
        )
        db.add(unit)
        db.flush()
        _ensure_placeholder_segment(db, run, track_run.track_type, unit)
        created += 1
    return created



def _build_lipsync_units(
    db: Session,
    run: RenderRun,
    track_run: TrackRun,
    shots: list[Shot],
    spans: dict[str, tuple[int, int]],
) -> int:
    created = 0
    for shot in shots:
        start_ms, end_ms = spans.get(shot.id, (0, int(shot.duration_ms or 5000)))
        unit = TrackUnit(
            id=f"tu_{uuid4().hex}",
            tenant_id=run.tenant_id,
            project_id=run.project_id,
            trace_id=run.trace_id,
            correlation_id=run.correlation_id,
            idempotency_key=f"idem_tu_{track_run.id}_{shot.id}",
            run_id=run.id,
            track_run_id=track_run.id,
            chapter_id=run.chapter_id,
            shot_id=shot.id,
            unit_ref_id=f"{shot.id}:lipsync",
            unit_kind="shot",
            status="queued",
            planned_start_ms=start_ms,
            planned_end_ms=end_ms,
            input_payload_snapshot={
                "shot_id": shot.id,
                "alignment_mode": "auto",
                "face_detect": True,
                "output_format": "mp4",
            },
        )
        db.add(unit)
        db.flush()
        _ensure_placeholder_segment(db, run, track_run.track_type, unit)
        created += 1
    return created



def _build_bgm_units(
    db: Session,
    run: RenderRun,
    track_run: TrackRun,
    timeline_total_ms: int,
) -> int:
    end_ms = max(1000, timeline_total_ms or 60_000)
    unit = TrackUnit(
        id=f"tu_{uuid4().hex}",
        tenant_id=run.tenant_id,
        project_id=run.project_id,
        trace_id=run.trace_id,
        correlation_id=run.correlation_id,
        idempotency_key=f"idem_tu_{track_run.id}_bgm_main",
        run_id=run.id,
        track_run_id=track_run.id,
        chapter_id=run.chapter_id,
        unit_ref_id="bgm_main",
        unit_kind="segment",
        status="queued",
        planned_start_ms=0,
        planned_end_ms=end_ms,
        input_payload_snapshot={"segment": "full_timeline"},
    )
    db.add(unit)
    db.flush()
    _ensure_placeholder_segment(db, run, track_run.track_type, unit)
    return 1


def _build_aux_units(
    db: Session,
    run: RenderRun,
    track_run: TrackRun,
    timeline_total_ms: int,
) -> int:
    end_ms = max(1000, timeline_total_ms or 60_000)
    unit = TrackUnit(
        id=f"tu_{uuid4().hex}",
        tenant_id=run.tenant_id,
        project_id=run.project_id,
        trace_id=run.trace_id,
        correlation_id=run.correlation_id,
        idempotency_key=f"idem_tu_{track_run.id}_aux_main",
        run_id=run.id,
        track_run_id=track_run.id,
        chapter_id=run.chapter_id,
        unit_ref_id="aux_main",
        unit_kind="segment",
        status="queued",
        planned_start_ms=0,
        planned_end_ms=end_ms,
        input_payload_snapshot={"description": "auxiliary texture layer"},
    )
    db.add(unit)
    db.flush()
    _ensure_placeholder_segment(db, run, track_run.track_type, unit)
    return 1


def _normalize_token(value: str | None, fallback: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return fallback
    normalized = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in raw)
    normalized = normalized.strip("_")
    return normalized or fallback


def _resolve_lineage_context(db: Session, run: RenderRun) -> dict[str, str]:
    chapter = db.get(Chapter, run.chapter_id)
    config = run.config_json if isinstance(run.config_json, dict) else {}
    requested_payload_raw = config.get("requested_payload")
    selected_culture_raw = config.get("selected_culture_pack")
    requested_payload = requested_payload_raw if isinstance(requested_payload_raw, dict) else {}
    selected_culture = selected_culture_raw if isinstance(selected_culture_raw, dict) else {}

    source_language = _normalize_token(
        str(requested_payload.get("source_language") or requested_payload.get("language_context") or ""),
        "und",
    )
    target_language = _normalize_token(
        str(
            requested_payload.get("target_language")
            or requested_payload.get("target_locale")
            or requested_payload.get("language_context")
            or ""
        ),
        source_language,
    )
    culture_pack = _normalize_token(
        str(requested_payload.get("culture_pack_id") or selected_culture.get("culture_pack_id") or ""),
        "default",
    )
    world_pack_version = _normalize_token(
        str(requested_payload.get("world_pack_version") or requested_payload.get("world_version") or selected_culture.get("version") or ""),
        "v1",
    )
    novel_id = _normalize_token(chapter.novel_id if chapter else "", "novel_unknown")
    chapter_id = _normalize_token(run.chapter_id, "chapter_unknown")
    run_id = _normalize_token(run.id, "run_unknown")

    return {
        "novel_id": novel_id,
        "chapter_id": chapter_id,
        "run_id": run_id,
        "source_language": source_language,
        "target_language": target_language,
        "culture_pack_id": culture_pack,
        "world_pack_version": world_pack_version,
    }


def _build_artifact_path_hint(
    lineage_ctx: dict[str, str],
    track_type: str,
    unit_ref_id: str,
) -> str:
    unit_ref_token = _normalize_token(unit_ref_id, "unit")
    return (
        f"/novel/{lineage_ctx['novel_id']}"
        f"/chapter/{lineage_ctx['chapter_id']}"
        f"/run/{lineage_ctx['run_id']}"
        f"/lang/{lineage_ctx['target_language']}"
        f"/culture/{lineage_ctx['culture_pack_id']}"
        f"/world/{lineage_ctx['world_pack_version']}"
        f"/track/{_normalize_token(track_type, 'track')}"
        f"/unit/{unit_ref_token}"
    )



def _build_units_for_track(
    db: Session,
    run: RenderRun,
    track_run: TrackRun,
    shots: list[Shot],
    dialogues: list[Dialogue],
    shot_spans: dict[str, tuple[int, int]],
    timeline_total_ms: int,
) -> int:
    if track_run.track_type in {"video", "storyboard"}:
        return _build_video_units(db, run, track_run, shots, shot_spans)
    if track_run.track_type in {"tts", "dialogue", "narration"}:
        return _build_tts_units(db, run, track_run, dialogues, timeline_total_ms)
    if track_run.track_type == "sfx":
        return _build_sfx_units(db, run, track_run, shots, shot_spans)
    if track_run.track_type == "ambience":
        return _build_ambience_units(db, run, track_run, shots, shot_spans)
    if track_run.track_type == "bgm":
        return _build_bgm_units(db, run, track_run, timeline_total_ms)
    if track_run.track_type == "aux":
        return _build_aux_units(db, run, track_run, timeline_total_ms)
    if track_run.track_type == "lipsync":
        return _build_lipsync_units(db, run, track_run, shots, shot_spans)
    if track_run.track_type == "subtitle":
        return _build_subtitle_units(db, run, track_run, dialogues, timeline_total_ms)
    return 0



def _choose_worker_profile(db: Session, worker_type: str | None) -> str | None:
    if not worker_type:
        return None
    profiles = ProviderRegistry(db).list_profiles(worker_type)
    if not profiles:
        return None
    return profiles[0].id



def _artifact_uri_by_id(db: Session, artifact_id: str | None) -> str | None:
    if not artifact_id:
        return None
    art = db.get(Artifact, artifact_id)
    if art is None or art.deleted_at is not None:
        return None
    return art.uri


def _resolve_lipsync_sources(db: Session, run_id: str, unit: TrackUnit) -> tuple[str | None, str | None]:
    video_unit = db.execute(
        select(TrackUnit)
        .join(TrackRun, TrackRun.id == TrackUnit.track_run_id)
        .where(
            TrackUnit.run_id == run_id,
            TrackUnit.shot_id == unit.shot_id,
            TrackUnit.status == "success",
            TrackUnit.selected_asset_id.is_not(None),
            TrackRun.track_type.in_(["video", "storyboard"]),
            TrackUnit.deleted_at.is_(None),
            TrackRun.deleted_at.is_(None),
        )
        .order_by(TrackUnit.updated_at.desc())
        .limit(1)
    ).scalars().first()
    video_uri = _artifact_uri_by_id(db, video_unit.selected_asset_id if video_unit else None)

    start_ms = int(unit.planned_start_ms or 0)
    end_ms = int(unit.planned_end_ms or start_ms + 1)
    audio_unit = db.execute(
        select(TrackUnit)
        .join(TrackRun, TrackRun.id == TrackUnit.track_run_id)
        .where(
            TrackUnit.run_id == run_id,
            TrackUnit.status == "success",
            TrackUnit.selected_asset_id.is_not(None),
            TrackRun.track_type.in_(["tts", "dialogue", "narration"]),
            TrackUnit.deleted_at.is_(None),
            TrackRun.deleted_at.is_(None),
            or_(
                TrackUnit.shot_id == unit.shot_id,
                and_(
                    TrackUnit.planned_start_ms.is_not(None),
                    TrackUnit.planned_end_ms.is_not(None),
                    TrackUnit.planned_start_ms < end_ms,
                    TrackUnit.planned_end_ms > start_ms,
                ),
            ),
        )
        .order_by(TrackUnit.updated_at.desc())
        .limit(1)
    ).scalars().first()
    audio_uri = _artifact_uri_by_id(db, audio_unit.selected_asset_id if audio_unit else None)
    return video_uri, audio_uri


def _build_job_payload_for_unit(
    db: Session,
    run: RenderRun,
    track_run: TrackRun,
    unit: TrackUnit,
) -> tuple[dict[str, Any], str | None]:
    lineage_ctx = _resolve_lineage_context(db, run)
    artifact_path_hint = _build_artifact_path_hint(
        lineage_ctx=lineage_ctx,
        track_type=track_run.track_type,
        unit_ref_id=unit.unit_ref_id,
    )
    payload = dict(unit.input_payload_snapshot or {})
    payload.update(
        {
            "run_id": run.id,
            "chapter_id": run.chapter_id,
            "track_type": track_run.track_type,
            "track_run_id": track_run.id,
            "track_unit_id": unit.id,
            "unit_ref_id": unit.unit_ref_id,
            "planned_start_ms": unit.planned_start_ms,
            "planned_end_ms": unit.planned_end_ms,
            "worker_type": track_run.worker_type,
            "model_profile_id": track_run.model_profile_id,
            "artifact_path_hint": artifact_path_hint,
            "lineage_tags": {
                **lineage_ctx,
                "track_type": track_run.track_type,
                "track_run_id": track_run.id,
                "track_unit_id": unit.id,
                "unit_ref_id": unit.unit_ref_id,
            },
        }
    )

    if track_run.track_type in {"video", "storyboard"}:
        shot = db.get(Shot, unit.shot_id) if unit.shot_id else None
        payload.setdefault("shot_id", unit.shot_id)
        payload.setdefault("prompt", ((shot.prompt_json or {}) if shot else {}).get("prompt", ""))
    elif track_run.track_type in {"tts", "dialogue", "narration"}:
        dlg = db.get(Dialogue, unit.dialogue_id) if unit.dialogue_id else None
        payload.setdefault("text", dlg.content if dlg else "")
        payload.setdefault("voice_id", "narrator")
    elif track_run.track_type in {"sfx", "ambience", "aux"}:
        dur_ms = max(300, int((unit.planned_end_ms or 0) - (unit.planned_start_ms or 0)))
        description = "scene event"
        if track_run.track_type == "ambience":
            description = "ambient environment loop"
        if track_run.track_type == "aux":
            description = "auxiliary texture layer"
        payload.setdefault("description", description)
        payload.setdefault("start_ms", int(unit.planned_start_ms or 0))
        payload.setdefault("duration_ms", dur_ms)
    elif track_run.track_type == "bgm":
        payload.setdefault("mood", "neutral_background")
        payload.setdefault("genre", "ambient")
        payload.setdefault("duration_s", max(1.0, float((unit.planned_end_ms or 0) - (unit.planned_start_ms or 0)) / 1000.0))
    elif track_run.track_type == "lipsync":
        video_uri, audio_uri = _resolve_lipsync_sources(db, run.id, unit)
        if not video_uri:
            return payload, "dependency_missing:video"
        if not audio_uri:
            return payload, "dependency_missing:audio"
        payload.setdefault("video_uri", video_uri)
        payload.setdefault("audio_uri", audio_uri)
        payload.setdefault("alignment_mode", "auto")
        payload.setdefault("face_detect", True)
        payload.setdefault("output_format", "mp4")
        payload.setdefault("backend", "auto")
        payload.setdefault("pads", [0, 10, 0, 0])
    elif track_run.track_type == "subtitle":
        dlg = db.get(Dialogue, unit.dialogue_id) if unit.dialogue_id else None
        payload.setdefault("text", dlg.content if dlg else payload.get("text", ""))
        payload.setdefault("speaker", dlg.speaker if dlg else payload.get("speaker", ""))
        payload.setdefault("line_break_mode", "smart")
        payload.setdefault("max_chars_per_line", 24)
        payload.setdefault("output_format", "json")

    return payload, None



def _next_attempt_no(db: Session, track_unit_id: str) -> int:
    latest = db.execute(
        select(func.max(TrackUnitAttempt.attempt_no))
        .where(
            TrackUnitAttempt.track_unit_id == track_unit_id,
            TrackUnitAttempt.deleted_at.is_(None),
        )
    ).scalar_one_or_none()
    return int(latest or 0) + 1


def _sync_unit_segment_artifact(db: Session, run_id: str, track_type: str, unit_id: str, artifact_id: str) -> None:
    segments = db.execute(
        select(TimelineSegment)
        .where(
            TimelineSegment.run_id == run_id,
            TimelineSegment.track == track_type,
            TimelineSegment.deleted_at.is_(None),
        )
    ).scalars().all()
    for seg in segments:
        meta = seg.meta_json or {}
        if meta.get("track_unit_id") != unit_id:
            continue
        seg.artifact_id = artifact_id
        meta["status"] = "ready"
        meta["selected_asset_id"] = artifact_id
        meta["updated_at"] = _utcnow().isoformat()
        seg.meta_json = meta


def _enqueue_unit_job(
    db: Session,
    run: RenderRun,
    track_run: TrackRun,
    unit: TrackUnit,
    payload: dict[str, Any],
    *,
    trigger_type: str = "run_all",
    patch: dict[str, Any] | None = None,
) -> Job:
    job_type = _TRACK_TO_JOB_TYPE.get(track_run.track_type, JobType.render_video)
    job = Job(
        id=f"job_{uuid4().hex}",
        tenant_id=run.tenant_id,
        project_id=run.project_id,
        trace_id=run.trace_id,
        correlation_id=run.correlation_id,
        idempotency_key=f"idem_tu_job_{unit.id}_{uuid4().hex[:8]}",
        run_id=run.id,
        chapter_id=run.chapter_id,
        shot_id=unit.shot_id,
        track_unit_id=unit.id,
        job_type=job_type,
        stage=RenderStage.execute,
        status=JobStatus.queued,
        payload_json={
            **payload,
            "job_type": job_type.value,
        },
    )
    db.add(job)

    attempt = TrackUnitAttempt(
        id=f"tua_{uuid4().hex}",
        tenant_id=run.tenant_id,
        project_id=run.project_id,
        trace_id=run.trace_id,
        correlation_id=run.correlation_id,
        idempotency_key=f"idem_tua_{unit.id}_{job.id}",
        run_id=run.id,
        track_run_id=track_run.id,
        track_unit_id=unit.id,
        attempt_no=_next_attempt_no(db, unit.id),
        trigger_type=trigger_type,
        patch_json=patch if patch else None,
        job_id=job.id,
        status="queued",
    )
    db.add(attempt)

    event = EventEnvelope(
        event_type="job.created",
        producer="studio-api",
        occurred_at=_utcnow(),
        tenant_id=run.tenant_id,
        project_id=run.project_id,
        idempotency_key=job.idempotency_key or f"idem_job_{job.id}",
        run_id=run.id,
        job_id=job.id,
        trace_id=run.trace_id or "",
        correlation_id=run.correlation_id or "",
        payload=job.payload_json,
    )
    publish(SYSTEM_TOPICS.JOB_DISPATCH, event.model_dump(mode="json"))
    return job


@router.post("/runs/{run_id}/tracks/init", response_model=InitTracksResponse)
def init_run_tracks(
    run_id: str,
    body: InitTracksRequest,
    db: Session = Depends(get_db),
) -> InitTracksResponse:
    run = _load_run_or_404(db, run_id)
    shots = _list_shots_for_run(db, run)
    dialogues = _list_dialogues_for_run(db, run)
    shot_spans, total_ms = _build_shot_spans(shots)

    items: list[TrackInitItem] = []
    for raw_track in body.track_types:
        track_type = _normalize_track(raw_track)
        if track_type not in _TRACK_TO_WORKER:
            continue

        tr = _ensure_track_run(db, run, track_type)
        if body.recreate:
            _clear_track_units(db, tr)
            _clear_track_segments(db, run.id, track_type)

        has_active_units = db.execute(
            select(TrackUnit.id)
            .where(
                TrackUnit.track_run_id == tr.id,
                TrackUnit.deleted_at.is_(None),
            )
            .limit(1)
        ).scalar_one_or_none()

        created = 0
        if body.recreate or not has_active_units:
            created = _build_units_for_track(db, run, tr, shots, dialogues, shot_spans, total_ms)

        tr.status = "queued"
        tr.blocked_reason = None
        items.append(
            TrackInitItem(
                track_type=track_type,
                track_run_id=tr.id,
                units_created=created,
                status=tr.status,
            )
        )

    run.status = RunStatus.running
    run.stage = RenderStage.plan
    run.progress = max(int(run.progress or 0), 10)
    db.commit()

    return InitTracksResponse(run_id=run_id, tracks=items)


@router.get("/runs/{run_id}/tracks", response_model=list[TrackSummary])
def list_run_tracks(
    run_id: str,
    db: Session = Depends(get_db),
) -> list[TrackSummary]:
    _load_run_or_404(db, run_id)
    track_runs = db.execute(
        select(TrackRun)
        .where(
            TrackRun.run_id == run_id,
            TrackRun.deleted_at.is_(None),
        )
        .order_by(TrackRun.created_at.asc())
    ).scalars().all()

    out: list[TrackSummary] = []
    for tr in track_runs:
        units = db.execute(
            select(TrackUnit)
            .where(
                TrackUnit.track_run_id == tr.id,
                TrackUnit.deleted_at.is_(None),
            )
        ).scalars().all()
        total = len(units)
        success = sum(1 for u in units if u.status == "success")
        failed = sum(1 for u in units if u.status == "failed")
        running = sum(1 for u in units if u.status in {"running", "queued"})
        blocked = sum(1 for u in units if u.status == "blocked")
        out.append(
            TrackSummary(
                track_run_id=tr.id,
                track_type=tr.track_type,
                worker_type=tr.worker_type,
                status=tr.status,
                blocked_reason=tr.blocked_reason,
                total_units=total,
                success_units=success,
                failed_units=failed,
                running_units=running,
                blocked_units=blocked,
            )
        )
    return out


@router.get("/runs/{run_id}/tracks/{track_type}/units", response_model=list[TrackUnitItem])
def list_track_units(
    run_id: str,
    track_type: str,
    db: Session = Depends(get_db),
) -> list[TrackUnitItem]:
    _load_run_or_404(db, run_id)
    tr = db.execute(
        select(TrackRun)
        .where(
            TrackRun.run_id == run_id,
            TrackRun.track_type == _normalize_track(track_type),
            TrackRun.deleted_at.is_(None),
        )
        .limit(1)
    ).scalars().first()
    if tr is None:
        raise HTTPException(status_code=404, detail="track not found")

    units = db.execute(
        select(TrackUnit)
        .where(
            TrackUnit.track_run_id == tr.id,
            TrackUnit.deleted_at.is_(None),
        )
        .order_by(TrackUnit.created_at.asc())
    ).scalars().all()

    return [
        TrackUnitItem(
            unit_id=u.id,
            unit_ref_id=u.unit_ref_id,
            unit_kind=u.unit_kind,
            status=u.status,
            planned_start_ms=u.planned_start_ms,
            planned_end_ms=u.planned_end_ms,
            attempt_count=int(u.attempt_count or 0),
            max_attempts=int(u.max_attempts or 0),
            blocked_reason=u.blocked_reason,
            last_error_code=u.last_error_code,
            last_error_message=u.last_error_message,
            selected_asset_id=u.selected_asset_id,
            selected_job_id=u.selected_job_id,
            output_candidates=list(u.output_candidates_json or []),
        )
        for u in units
    ]


@router.post("/runs/{run_id}/tracks/{track_type}/run", response_model=RunTrackResponse)
def run_track(
    run_id: str,
    track_type: str,
    body: RunTrackRequest,
    db: Session = Depends(get_db),
) -> RunTrackResponse:
    run = _load_run_or_404(db, run_id)
    norm_track = _normalize_track(track_type)
    tr = db.execute(
        select(TrackRun)
        .where(
            TrackRun.run_id == run_id,
            TrackRun.track_type == norm_track,
            TrackRun.deleted_at.is_(None),
        )
        .limit(1)
    ).scalars().first()
    if tr is None:
        raise HTTPException(status_code=404, detail="track not found")

    tr.model_profile_id = _choose_worker_profile(db, tr.worker_type)
    if not tr.model_profile_id:
        tr.status = "blocked"
        tr.blocked_reason = "no_model"
        units = db.execute(
            select(TrackUnit)
            .where(
                TrackUnit.track_run_id == tr.id,
                TrackUnit.deleted_at.is_(None),
            )
        ).scalars().all()
        for unit in units:
            if unit.status in {"queued", "running", "blocked"}:
                unit.status = "blocked"
                unit.blocked_reason = "no_model"
        run.status = RunStatus.degraded
        db.commit()
        return RunTrackResponse(
            run_id=run_id,
            track_type=norm_track,
            track_run_id=tr.id,
            track_status=tr.status,
            jobs_created=0,
            blocked_reason=tr.blocked_reason,
        )

    q = select(TrackUnit).where(
        TrackUnit.track_run_id == tr.id,
        TrackUnit.deleted_at.is_(None),
    )
    if body.unit_ids:
        q = q.where(TrackUnit.id.in_(body.unit_ids))
    if body.only_failed:
        q = q.where(TrackUnit.status == "failed")
    elif not body.force:
        q = q.where(TrackUnit.status.in_(["queued", "failed", "blocked"]))
    units = db.execute(q.order_by(TrackUnit.created_at.asc())).scalars().all()

    trigger_type = "run_all"
    if body.only_failed:
        trigger_type = "retry_failed"
    elif body.unit_ids and len(body.unit_ids) == 1:
        trigger_type = "run_single"
    elif body.force:
        trigger_type = "run_force"

    jobs_created = 0
    blocked_due_dependency = 0
    for unit in units:
        payload, blocked_reason = _build_job_payload_for_unit(db, run, tr, unit)
        if blocked_reason:
            unit.status = "blocked"
            unit.blocked_reason = blocked_reason
            unit.last_error_code = "TRACK-DEPENDENCY-001"
            unit.last_error_message = blocked_reason
            blocked_due_dependency += 1
            continue
        _enqueue_unit_job(db, run, tr, unit, payload, trigger_type=trigger_type)
        unit.status = "queued"
        unit.blocked_reason = None
        unit.last_error_code = None
        unit.last_error_message = None
        jobs_created += 1

    if jobs_created > 0:
        tr.status = "running"
        tr.blocked_reason = None
    elif blocked_due_dependency > 0:
        tr.status = "blocked"
        tr.blocked_reason = "dependency_missing"
    tr.started_at = tr.started_at or _utcnow()

    if jobs_created > 0:
        run.status = RunStatus.running
        run.stage = RenderStage.execute
        run.progress = max(int(run.progress or 0), 20)
    elif blocked_due_dependency > 0:
        run.status = RunStatus.degraded

    db.commit()

    return RunTrackResponse(
        run_id=run_id,
        track_type=norm_track,
        track_run_id=tr.id,
        track_status=tr.status,
        jobs_created=jobs_created,
        blocked_reason=tr.blocked_reason,
    )


@router.post("/runs/{run_id}/tracks/units/{unit_id}/retry", response_model=RetryTrackUnitResponse)
def retry_track_unit(
    run_id: str,
    unit_id: str,
    body: RetryTrackUnitRequest,
    db: Session = Depends(get_db),
) -> RetryTrackUnitResponse:
    run = _load_run_or_404(db, run_id)
    unit = db.execute(
        select(TrackUnit)
        .where(
            TrackUnit.id == unit_id,
            TrackUnit.run_id == run_id,
            TrackUnit.deleted_at.is_(None),
        )
        .limit(1)
    ).scalars().first()
    if unit is None:
        raise HTTPException(status_code=404, detail="track unit not found")

    track_run = db.get(TrackRun, unit.track_run_id)
    if track_run is None or track_run.deleted_at is not None:
        raise HTTPException(status_code=404, detail="track run not found")

    payload, blocked_reason = _build_job_payload_for_unit(db, run, track_run, unit)
    if blocked_reason:
        unit.status = "blocked"
        unit.blocked_reason = blocked_reason
        unit.last_error_code = "TRACK-DEPENDENCY-001"
        unit.last_error_message = blocked_reason
        track_run.status = "blocked"
        track_run.blocked_reason = "dependency_missing"
        run.status = RunStatus.degraded
        db.commit()
        raise HTTPException(status_code=409, detail=blocked_reason)
    if body.patch:
        payload.update(body.patch)
    retry_trigger = "patch_retry" if body.patch else "manual_retry"
    job = _enqueue_unit_job(
        db,
        run,
        track_run,
        unit,
        payload,
        trigger_type=retry_trigger,
        patch=body.patch or None,
    )

    unit.status = "queued"
    unit.blocked_reason = None
    unit.last_error_code = None
    unit.last_error_message = None
    if body.patch:
        snap = dict(unit.input_payload_snapshot or {})
        snap.update(body.patch)
        unit.input_payload_snapshot = snap

    track_run.status = "running"
    track_run.blocked_reason = None
    track_run.started_at = track_run.started_at or _utcnow()

    run.status = RunStatus.running
    run.stage = RenderStage.execute

    db.commit()

    return RetryTrackUnitResponse(
        run_id=run_id,
        track_run_id=track_run.id,
        track_unit_id=unit.id,
        job_id=job.id,
        status="queued",
    )


@router.get("/runs/{run_id}/tracks/units/{unit_id}/attempts", response_model=list[TrackUnitAttemptItem])
def list_track_unit_attempts(
    run_id: str,
    unit_id: str,
    db: Session = Depends(get_db),
) -> list[TrackUnitAttemptItem]:
    _load_run_or_404(db, run_id)
    unit = db.execute(
        select(TrackUnit.id)
        .where(
            TrackUnit.id == unit_id,
            TrackUnit.run_id == run_id,
            TrackUnit.deleted_at.is_(None),
        )
        .limit(1)
    ).scalar_one_or_none()
    if unit is None:
        raise HTTPException(status_code=404, detail="track unit not found")

    attempts = db.execute(
        select(TrackUnitAttempt)
        .where(
            TrackUnitAttempt.run_id == run_id,
            TrackUnitAttempt.track_unit_id == unit_id,
            TrackUnitAttempt.deleted_at.is_(None),
        )
        .order_by(TrackUnitAttempt.attempt_no.asc())
    ).scalars().all()
    return [
        TrackUnitAttemptItem(
            attempt_id=item.id,
            attempt_no=int(item.attempt_no or 0),
            trigger_type=item.trigger_type,
            status=item.status,
            job_id=item.job_id,
            artifact_id=item.artifact_id,
            error_code=item.error_code,
            error_message=item.error_message,
            duration_ms=item.duration_ms,
            started_at=item.started_at,
            finished_at=item.finished_at,
        )
        for item in attempts
    ]


@router.post("/runs/{run_id}/tracks/units/{unit_id}/select-candidate", response_model=SelectTrackUnitCandidateResponse)
def select_track_unit_candidate(
    run_id: str,
    unit_id: str,
    body: SelectTrackUnitCandidateRequest,
    db: Session = Depends(get_db),
) -> SelectTrackUnitCandidateResponse:
    _load_run_or_404(db, run_id)
    unit = db.execute(
        select(TrackUnit)
        .where(
            TrackUnit.id == unit_id,
            TrackUnit.run_id == run_id,
            TrackUnit.deleted_at.is_(None),
        )
        .limit(1)
    ).scalars().first()
    if unit is None:
        raise HTTPException(status_code=404, detail="track unit not found")

    track_run = db.get(TrackRun, unit.track_run_id)
    if track_run is None or track_run.deleted_at is not None:
        raise HTTPException(status_code=404, detail="track run not found")

    candidates = list(unit.output_candidates_json or [])
    if not candidates:
        raise HTTPException(status_code=400, detail="no candidates to select")

    candidate: dict[str, Any] | None = None
    if body.artifact_id:
        candidate = next((item for item in candidates if str(item.get("artifact_id") or "") == body.artifact_id), None)
        if candidate is None:
            raise HTTPException(status_code=404, detail="candidate artifact not found")
    elif body.candidate_index is not None:
        if body.candidate_index < 0 or body.candidate_index >= len(candidates):
            raise HTTPException(status_code=400, detail="candidate index out of range")
        candidate = candidates[body.candidate_index]
    else:
        candidate = candidates[-1]

    artifact_id = str(candidate.get("artifact_id") or "")
    if not artifact_id:
        raise HTTPException(status_code=400, detail="candidate missing artifact_id")

    artifact = db.get(Artifact, artifact_id)
    if artifact is None or artifact.deleted_at is not None:
        raise HTTPException(status_code=404, detail="artifact not found")
    if artifact.run_id != run_id:
        raise HTTPException(status_code=400, detail="artifact does not belong to this run")

    selected_job_id_raw = str(candidate.get("job_id") or "").strip()
    selected_job_id: str | None = None
    if selected_job_id_raw:
        selected_job = db.get(Job, selected_job_id_raw)
        if selected_job is not None and selected_job.deleted_at is None:
            selected_job_id = selected_job.id

    unit.selected_asset_id = artifact_id
    unit.selected_job_id = selected_job_id
    unit.status = "success"
    unit.blocked_reason = None
    unit.last_error_code = None
    unit.last_error_message = None

    _sync_unit_segment_artifact(
        db=db,
        run_id=run_id,
        track_type=track_run.track_type,
        unit_id=unit.id,
        artifact_id=artifact_id,
    )
    db.commit()

    return SelectTrackUnitCandidateResponse(
        run_id=run_id,
        track_run_id=track_run.id,
        track_unit_id=unit.id,
        selected_asset_id=artifact_id,
        selected_job_id=unit.selected_job_id,
        status="selected",
    )
