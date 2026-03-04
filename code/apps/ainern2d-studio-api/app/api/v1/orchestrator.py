from __future__ import annotations

from datetime import datetime, timezone
import time
from urllib.parse import urlparse

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from uuid import uuid4

from ainern2d_shared.ainer_db_models.content_models import Artifact, Chapter, TimelineSegment
from ainern2d_shared.ainer_db_models.enum_models import ArtifactType, JobStatus, RenderStage, RunStatus
from ainern2d_shared.ainer_db_models.pipeline_models import (
    ArtifactLineageIndex,
    Job,
    TrackRun,
    TrackUnit,
    TrackUnitAttempt,
    WorkflowEvent,
)
from ainern2d_shared.ainer_db_models.provider_models import ProviderAdapter
from ainern2d_shared.db.repositories.pipeline import RenderRunRepository
from ainern2d_shared.queue.topics import SYSTEM_TOPICS
from ainern2d_shared.schemas.events import EventEnvelope
from ainern2d_shared.services.base_skill import SkillContext
from ainern2d_shared.config.setting import settings
from ainern2d_shared.queue.rabbitmq import RabbitMQConsumer

from app.api.deps import get_db, get_db_session, publish
from ainern2d_shared.telemetry.logging import get_logger
from app.services.telegram_notify import notify_telegram_event
from app.modules.model_router.router import ModelRouter
from app.modules.model_router.provider_registry import ProviderRegistry
from ainern2d_shared.schemas.task import TaskSpec

router = APIRouter(prefix="/internal/orchestrator", tags=["orchestrator"])

_logger = get_logger("orchestrator")


def _persist_event(db: Session, event: EventEnvelope) -> None:
    """Save an EventEnvelope as a WorkflowEvent row."""
    wf = WorkflowEvent(
        id=event.event_id,
        tenant_id=event.tenant_id,
        project_id=event.project_id,
        trace_id=event.trace_id,
        correlation_id=event.correlation_id,
        idempotency_key=event.idempotency_key,
        run_id=event.run_id,
        event_type=event.event_type,
        event_version=event.event_version,
        producer=event.producer,
        occurred_at=event.occurred_at,
        payload_json=event.payload,
    )
    db.add(wf)


def _event_exists(db: Session, event_id: str) -> bool:
    """Idempotency guard: whether this event_id is already persisted."""
    return db.get(WorkflowEvent, event_id) is not None


def _extract_artifact_uri(payload: dict) -> str | None:
    uri = payload.get("artifact_uri")
    if isinstance(uri, str) and uri:
        return uri
    output = payload.get("output")
    if isinstance(output, dict):
        for key in ("artifact_uri", "video_uri", "audio_uri", "uri"):
            val = output.get(key)
            if isinstance(val, str) and val:
                return val
    return None


def _artifact_type_for_track(track_type: str) -> ArtifactType:
    norm = (track_type or "").strip().lower()
    if norm in {"tts", "dialogue", "narration"}:
        return ArtifactType.dialogue_wav
    if norm in {"sfx", "bgm", "ambience", "aux"}:
        return ArtifactType.mixed_audio
    if norm == "subtitle":
        return ArtifactType.subtitles
    return ArtifactType.shot_video


def _normalize_token(value: str | None, fallback: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return fallback
    token = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in raw)
    token = token.strip("_")
    return token or fallback


def _guess_artifact_extension(track_type: str, artifact_uri: str | None) -> str:
    default_map = {
        "video": "mp4",
        "storyboard": "png",
        "tts": "wav",
        "dialogue": "wav",
        "narration": "wav",
        "sfx": "wav",
        "ambience": "wav",
        "aux": "wav",
        "bgm": "wav",
        "subtitle": "json",
        "lipsync": "mp4",
    }
    fallback = default_map.get((track_type or "").strip().lower(), "bin")
    if not artifact_uri:
        return fallback
    path = urlparse(artifact_uri).path
    if "." not in path:
        return fallback
    ext = path.rsplit(".", 1)[-1].lower().strip()
    if not ext or len(ext) > 8:
        return fallback
    return _normalize_token(ext, fallback)


def _extract_worker_artifact_meta(payload: dict) -> dict:
    output = payload.get("output")
    if not isinstance(output, dict):
        return {}
    for key in ("artifact_meta", "media_meta", "meta"):
        meta = output.get(key)
        if isinstance(meta, dict):
            return dict(meta)
    return {}


def _build_artifact_lineage(
    db: Session,
    run,
    track_run: TrackRun,
    unit: TrackUnit,
    artifact_id: str,
    artifact_uri_raw: str | None,
) -> tuple[str, dict, list[str]]:
    chapter = db.get(Chapter, run.chapter_id)
    config = run.config_json if isinstance(run.config_json, dict) else {}
    requested_payload_raw = config.get("requested_payload")
    selected_culture_raw = config.get("selected_culture_pack")
    requested_payload = requested_payload_raw if isinstance(requested_payload_raw, dict) else {}
    selected_culture = selected_culture_raw if isinstance(selected_culture_raw, dict) else {}

    source_language = _normalize_token(
        str((requested_payload or {}).get("source_language") or (requested_payload or {}).get("language_context") or ""),
        "und",
    )
    target_language = _normalize_token(
        str(
            (requested_payload or {}).get("target_language")
            or (requested_payload or {}).get("target_locale")
            or (requested_payload or {}).get("language_context")
            or ""
        ),
        source_language,
    )
    culture_pack_id = _normalize_token(
        str((requested_payload or {}).get("culture_pack_id") or (selected_culture or {}).get("culture_pack_id") or ""),
        "default",
    )
    world_pack_version = _normalize_token(
        str(
            (requested_payload or {}).get("world_pack_version")
            or (requested_payload or {}).get("world_version")
            or (selected_culture or {}).get("version")
            or ""
        ),
        "v1",
    )
    novel_id = _normalize_token(chapter.novel_id if chapter else "", "novel_unknown")
    chapter_id = _normalize_token(run.chapter_id, "chapter_unknown")
    run_id = _normalize_token(run.id, "run_unknown")
    track_type = _normalize_token(track_run.track_type, "track")
    unit_ref_id = _normalize_token(unit.unit_ref_id, "unit")
    extension = _guess_artifact_extension(track_run.track_type, artifact_uri_raw)

    canonical_path = (
        f"/novel/{novel_id}"
        f"/chapter/{chapter_id}"
        f"/run/{run_id}"
        f"/lang/{target_language}"
        f"/culture/{culture_pack_id}"
        f"/world/{world_pack_version}"
        f"/track/{track_type}"
        f"/unit/{unit_ref_id}"
        f"/{artifact_id}.{extension}"
    )

    required_tokens = [
        f"/chapter/{chapter_id}",
        f"/run/{run_id}",
        f"/track/{track_type}",
        f"/unit/{unit_ref_id}",
    ]
    is_uri_canonical = bool(artifact_uri_raw) and all(token in str(artifact_uri_raw) for token in required_tokens)
    normalized_uri = str(artifact_uri_raw) if is_uri_canonical else f"lineage://{canonical_path.lstrip('/')}"

    meta = {
        "lineage_schema": "run-track-unit.v1",
        "novel_id": novel_id,
        "chapter_id": chapter_id,
        "run_id": run_id,
        "track_type": track_type,
        "track_run_id": track_run.id,
        "track_unit_id": unit.id,
        "unit_ref_id": unit_ref_id,
        "source_language": source_language,
        "target_language": target_language,
        "culture_pack_id": culture_pack_id,
        "world_pack_version": world_pack_version,
        "model_profile_id": track_run.model_profile_id,
        "artifact_path_canonical": canonical_path,
        "origin_artifact_uri": artifact_uri_raw,
        "artifact_uri_normalized": normalized_uri,
    }

    required_keys = [
        "novel_id",
        "chapter_id",
        "run_id",
        "track_type",
        "track_run_id",
        "track_unit_id",
        "unit_ref_id",
        "target_language",
        "culture_pack_id",
        "world_pack_version",
        "artifact_path_canonical",
    ]
    missing_keys = [key for key in required_keys if not meta.get(key)]
    meta["meta_validation"] = {
        "required_keys": required_keys,
        "missing_keys": missing_keys,
        "valid": not missing_keys,
    }
    return normalized_uri, meta, missing_keys


def _refresh_track_rollups(db: Session, run) -> None:
    track_runs = db.execute(
        select(TrackRun)
        .where(
            TrackRun.run_id == run.id,
            TrackRun.deleted_at.is_(None),
        )
    ).scalars().all()
    if not track_runs:
        return

    total_units = 0
    success_units = 0
    has_running = False
    any_done = False
    any_failed_or_blocked = False

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
        blocked = sum(1 for u in units if u.status == "blocked")
        running = sum(1 for u in units if u.status in {"queued", "running"})
        partial = success > 0 and (failed > 0 or blocked > 0 or running > 0)

        tr.counters_json = {
            "total": total,
            "success": success,
            "failed": failed,
            "blocked": blocked,
            "running": running,
        }
        if total == 0:
            tr.status = "queued"
        elif blocked == total:
            tr.status = "blocked"
        elif success == total:
            tr.status = "done"
            tr.finished_at = tr.finished_at or datetime.now(timezone.utc)
        elif failed == total:
            tr.status = "failed"
        elif partial:
            tr.status = "partial"
        elif running > 0:
            tr.status = "running"
        else:
            tr.status = "queued"

        total_units += total
        success_units += success
        has_running = has_running or running > 0
        any_done = any_done or tr.status in {"done", "partial"}
        any_failed_or_blocked = any_failed_or_blocked or tr.status in {"failed", "blocked", "partial"}

    if total_units > 0:
        run.progress = int((success_units / total_units) * 100)
    if all(tr.status == "done" for tr in track_runs):
        run.status = RunStatus.success
        run.stage = RenderStage.observe
        run.progress = 100
        run.finished_at = run.finished_at or datetime.now(timezone.utc)
    elif has_running:
        run.status = RunStatus.running
        run.stage = RenderStage.execute
    elif any_done and any_failed_or_blocked:
        run.status = RunStatus.degraded
        run.stage = RenderStage.observe
    elif any_failed_or_blocked and not any_done:
        run.status = RunStatus.failed
        run.stage = RenderStage.execute


def _find_attempt_for_job(db: Session, job_id: str) -> TrackUnitAttempt | None:
    return db.execute(
        select(TrackUnitAttempt)
        .where(
            TrackUnitAttempt.job_id == job_id,
            TrackUnitAttempt.deleted_at.is_(None),
        )
        .order_by(TrackUnitAttempt.created_at.desc())
        .limit(1)
    ).scalars().first()


def _sync_unit_segment_artifact(db: Session, run_id: str, track_type: str, unit_id: str, artifact_id: str, lineage_path: str | None) -> None:
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
        if lineage_path:
            meta["lineage_path"] = lineage_path
        seg.meta_json = meta


def _handle_track_unit_job_event(db: Session, event: EventEnvelope, run) -> bool:
    job_id = event.payload.get("job_id") or event.job_id
    if not job_id:
        return False
    job = db.get(Job, job_id)
    if job is None:
        return False

    track_unit_id = (
        event.payload.get("track_unit_id")
        or (job.payload_json or {}).get("track_unit_id")
        or job.track_unit_id
    )
    if not track_unit_id:
        return False

    unit = db.get(TrackUnit, track_unit_id)
    if unit is None or unit.deleted_at is not None:
        return False
    track_run = db.get(TrackRun, unit.track_run_id)
    if track_run is None or track_run.deleted_at is not None:
        return False

    now = datetime.now(timezone.utc)
    if event.event_type == "job.claimed":
        job.status = JobStatus.claimed
        unit.status = "running"
        attempt = _find_attempt_for_job(db, job.id)
        if attempt is not None:
            attempt.status = "running"
            attempt.started_at = attempt.started_at or now
        track_run.status = "running"
        track_run.started_at = track_run.started_at or now
        run.status = RunStatus.running
        run.stage = RenderStage.execute
        return True

    if event.event_type == "job.succeeded":
        job.status = JobStatus.success
        job.result_json = event.payload
        artifact_uri_raw = _extract_artifact_uri(event.payload or {})
        artifact_id = f"art_{uuid4().hex}"
        artifact_uri, lineage_meta, missing_keys = _build_artifact_lineage(
            db=db,
            run=run,
            track_run=track_run,
            unit=unit,
            artifact_id=artifact_id,
            artifact_uri_raw=artifact_uri_raw,
        )
        worker_meta = _extract_worker_artifact_meta(event.payload or {})
        media_meta = {
            **worker_meta,
            **lineage_meta,
            "track_run_id": track_run.id,
            "track_unit_id": unit.id,
            "track_type": track_run.track_type,
            "unit_ref_id": unit.unit_ref_id,
            "dialogue_id": unit.dialogue_id,
            "model_profile_id": track_run.model_profile_id,
        }

        if missing_keys:
            job.status = JobStatus.failed
            unit.status = "failed"
            unit.attempt_count = int(unit.attempt_count or 0) + 1
            unit.last_error_code = "ARTIFACT-META-001"
            unit.last_error_message = f"artifact lineage meta invalid: missing {','.join(missing_keys)}"
            attempt = _find_attempt_for_job(db, job.id)
            if attempt is not None:
                attempt.status = "failed"
                attempt.error_code = unit.last_error_code
                attempt.error_message = unit.last_error_message
                attempt.finished_at = now
                if attempt.started_at:
                    attempt.duration_ms = max(
                        0,
                        int((attempt.finished_at - attempt.started_at).total_seconds() * 1000),
                    )
            _refresh_track_rollups(db, run)
            return True

        artifact = Artifact(
            id=artifact_id,
            tenant_id=run.tenant_id,
            project_id=run.project_id,
            trace_id=run.trace_id,
            correlation_id=run.correlation_id,
            idempotency_key=f"idem_track_artifact_{unit.id}_{uuid4().hex[:8]}",
            run_id=run.id,
            shot_id=unit.shot_id,
            type=_artifact_type_for_track(track_run.track_type),
            uri=artifact_uri,
            media_meta_json=media_meta,
        )
        db.add(artifact)
        db.flush()

        chapter_row = db.get(Chapter, run.chapter_id)
        lineage_index = ArtifactLineageIndex(
            id=f"ali_{uuid4().hex}",
            tenant_id=run.tenant_id,
            project_id=run.project_id,
            trace_id=run.trace_id,
            correlation_id=run.correlation_id,
            idempotency_key=f"idem_ali_{artifact.id}",
            artifact_id=artifact.id,
            run_id=run.id,
            track_run_id=track_run.id,
            track_unit_id=unit.id,
            novel_id=chapter_row.novel_id if chapter_row else None,
            chapter_id=run.chapter_id,
            source_language=lineage_meta.get("source_language"),
            target_language=lineage_meta.get("target_language"),
            culture_pack_id=lineage_meta.get("culture_pack_id"),
            world_pack_version=lineage_meta.get("world_pack_version"),
            track_type=lineage_meta.get("track_type"),
            unit_ref_id=lineage_meta.get("unit_ref_id"),
            canonical_path=lineage_meta.get("artifact_path_canonical"),
            model_profile_id=track_run.model_profile_id,
            extra_meta_json=media_meta,
        )
        db.add(lineage_index)

        candidates = list(unit.output_candidates_json or [])
        candidates.append(
            {
                "job_id": job.id,
                "artifact_id": artifact_id,
                "artifact_uri": artifact_uri,
                "origin_artifact_uri": artifact_uri_raw,
                "lineage_path": lineage_meta.get("artifact_path_canonical"),
                "at": now.isoformat(),
            }
        )
        unit.output_candidates_json = candidates
        unit.selected_asset_id = artifact_id or unit.selected_asset_id
        unit.selected_job_id = job.id
        unit.status = "success"
        unit.blocked_reason = None
        unit.last_error_code = None
        unit.last_error_message = None
        attempt = _find_attempt_for_job(db, job.id)
        if attempt is not None:
            attempt.status = "success"
            attempt.artifact_id = artifact.id
            attempt.error_code = None
            attempt.error_message = None
            attempt.finished_at = now
            if attempt.started_at:
                attempt.duration_ms = max(
                    0,
                    int((attempt.finished_at - attempt.started_at).total_seconds() * 1000),
                )

        _sync_unit_segment_artifact(
            db=db,
            run_id=run.id,
            track_type=track_run.track_type,
            unit_id=unit.id,
            artifact_id=unit.selected_asset_id or artifact.id,
            lineage_path=lineage_meta.get("artifact_path_canonical"),
        )
        _refresh_track_rollups(db, run)
        return True

    if event.event_type == "job.failed":
        job.status = JobStatus.failed
        job.result_json = event.payload
        unit.status = "failed"
        unit.attempt_count = int(unit.attempt_count or 0) + 1
        unit.last_error_code = event.payload.get("error_code", "WORKER-EXEC-002")
        unit.last_error_message = event.payload.get("error_message", "job failed")
        attempt = _find_attempt_for_job(db, job.id)
        if attempt is not None:
            attempt.status = "failed"
            attempt.error_code = unit.last_error_code
            attempt.error_message = unit.last_error_message
            attempt.finished_at = now
            if attempt.started_at:
                attempt.duration_ms = max(
                    0,
                    int((attempt.finished_at - attempt.started_at).total_seconds() * 1000),
                )
        segments = db.execute(
            select(TimelineSegment)
            .where(
                TimelineSegment.run_id == run.id,
                TimelineSegment.track == track_run.track_type,
                TimelineSegment.deleted_at.is_(None),
            )
        ).scalars().all()
        for seg in segments:
            meta = seg.meta_json or {}
            if meta.get("track_unit_id") == unit.id:
                meta["status"] = "failed"
                meta["error_code"] = unit.last_error_code
                meta["error_message"] = unit.last_error_message
                seg.meta_json = meta
        _refresh_track_rollups(db, run)
        return True

    return False


def handle_task_submitted(payload: dict) -> None:
    event = EventEnvelope.model_validate(payload)
    run_id = event.run_id
    if not run_id:
        return

    db = get_db_session()
    try:
        run_repo = RenderRunRepository(db)
        run = run_repo.get(run_id)
        if run is None:
            return

        run.status = RunStatus.running
        run.stage = RenderStage.route
        _persist_event(db, event)

        payload_ctx = event.payload.get("payload") or {}
        if bool(payload_ctx.get("track_mode")):
            run.stage = RenderStage.plan
            db.commit()
            return

        # 1. Routing Definition (Stage -> Feature -> Router)
        registry = ProviderRegistry(db)
        router = ModelRouter(db, registry)
        requested_worker_type = str(payload_ctx.get("worker_type") or "worker-video")
        task_spec = TaskSpec(
            task_id=f"tsk_{uuid4().hex[:8]}",
            budget_profile="balanced",
            deadline_ms=60000,
            user_overrides={},
        )
        decision = router.route(task_spec, requested_worker_type)
        
        # 2. Fetch configured AdapterSpec if any
        adapter_json = None
        if decision.model_profile_id:
            from ainern2d_shared.ainer_db_models.provider_models import ModelProfile
            profile = db.get(ModelProfile, decision.model_profile_id)
            if profile and profile.adapter_id:
                adapter = db.get(ProviderAdapter, profile.adapter_id)
                if adapter:
                    adapter_json = {
                        "endpoint_json": adapter.endpoint_json,
                        "auth_json": adapter.auth_json,
                        "request_json": adapter.request_json,
                        "response_json": adapter.response_json,
                        "timeout_sec": adapter.timeout_sec
                    }

        # 3. Assemble Canonical Dispatch payload
        dispatch_event = EventEnvelope(
            event_type="job.created",
            producer="orchestrator",
            occurred_at=datetime.now(timezone.utc),
            tenant_id=event.tenant_id,
            project_id=event.project_id,
            idempotency_key=event.idempotency_key,
            run_id=run_id,
            job_id=f"job_{uuid4().hex}",
            trace_id=event.trace_id,
            correlation_id=event.correlation_id,
            payload={
                "worker_type": decision.worker_type,
                "timeout_ms": decision.timeout_ms,
                "fallback_chain": decision.fallback_chain,
                "model_profile_id": decision.model_profile_id,
                "adapter_spec": adapter_json,
                "chapter_id": event.payload.get("chapter_id"),
                "requested_quality": event.payload.get("requested_quality"),
                "language_context": event.payload.get("language_context"),
            },
        )
        publish(SYSTEM_TOPICS.JOB_DISPATCH, dispatch_event.model_dump(mode="json"))
        _persist_event(db, dispatch_event)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def handle_job_status(payload: dict) -> None:
    event = EventEnvelope.model_validate(payload)
    run_id = event.run_id

    db = get_db_session()
    try:
        run_repo = RenderRunRepository(db)
        run = run_repo.get(run_id) if run_id else None

        if run is not None:
            if _handle_track_unit_job_event(db, event, run):
                _persist_event(db, event)
                db.commit()
                return

            if event.event_type == "job.claimed":
                run.status = RunStatus.running
                run.stage = RenderStage.execute
                run.progress = max(run.progress, 15)
            elif event.event_type == "job.succeeded":
                run.status = RunStatus.running
                run.stage = RenderStage.compose
                run.progress = max(run.progress, 70)
                compose_event = EventEnvelope(
                    event_type="compose.started",
                    producer="orchestrator",
                    occurred_at=datetime.now(timezone.utc),
                    tenant_id=event.tenant_id,
                    project_id=event.project_id,
                    idempotency_key=event.idempotency_key,
                    run_id=event.run_id,
                    trace_id=event.trace_id,
                    correlation_id=event.correlation_id,
                    payload={
                        "timeline_final": {"tracks": []},
                        "artifact_refs": [event.payload.get("artifact_uri")],
                    },
                )
                publish(SYSTEM_TOPICS.COMPOSE_DISPATCH, compose_event.model_dump(mode="json"))
                _persist_event(db, compose_event)
            elif event.event_type == "job.failed":
                run.status = RunStatus.failed
                run.stage = RenderStage.execute
                run.error_code = event.payload.get("error_code", "WORKER-EXEC-002")
                run.error_message = event.payload.get("error_message", "job failed")

        _persist_event(db, event)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def handle_compose_status(payload: dict) -> None:
    event = EventEnvelope.model_validate(payload)
    run_id = event.run_id

    db = get_db_session()
    try:
        run_repo = RenderRunRepository(db)
        run = run_repo.get(run_id) if run_id else None

        if run is not None:
            if event.event_type == "compose.completed":
                run.status = RunStatus.success
                run.stage = RenderStage.observe
                run.progress = 100
            elif event.event_type == "compose.failed":
                run.status = RunStatus.failed
                run.stage = RenderStage.compose
                run.error_code = event.payload.get("error_code", "COMPOSE-FFMPEG-001")
                run.error_message = event.payload.get("error_message", "compose failed")

        _persist_event(db, event)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def handle_skill_event(payload: dict) -> None:
    """Consume SKILL event stream and execute cross-skill rollback linkage."""
    event = EventEnvelope.model_validate(payload)
    db = get_db_session()
    try:
        if _event_exists(db, event.event_id):
            _logger.info("skip duplicate skill event event_id={}", event.event_id)
            return

        _persist_event(db, event)
        try:
            # Force uniqueness check before side-effects to avoid duplicate rollback
            # under concurrent consumers.
            db.flush()
        except IntegrityError:
            db.rollback()
            _logger.info("skip duplicate skill event on flush event_id={}", event.event_id)
            return

        if event.event_type == "kb.version.rolled_back":
            rollback_payload = event.payload or {}
            # If executor already handled rollback, this consumer is no-op.
            if not rollback_payload.get("executor_triggered"):
                kb_id = str(rollback_payload.get("kb_id") or "").strip()
                target_version_id = str(
                    rollback_payload.get("rollback_target_kb_version_id") or ""
                ).strip()
                if kb_id and target_version_id:
                    from ainern2d_shared.schemas.skills.skill_11 import Skill11Input
                    from app.services.skills.skill_11_rag_kb_manager import RagKBManagerService

                    out11 = RagKBManagerService(db).execute(
                        Skill11Input(
                            kb_id=kb_id,
                            action="rollback",
                            rollback_target_version_id=target_version_id,
                            rollback_reason=str(rollback_payload.get("reason") or "skill_event_consumer"),
                        ),
                        SkillContext(
                            tenant_id=event.tenant_id,
                            project_id=event.project_id,
                            run_id=event.run_id or "",
                            trace_id=event.trace_id,
                            correlation_id=event.correlation_id,
                            idempotency_key=event.idempotency_key,
                            schema_version=event.schema_version,
                        ),
                    )
                    for emitted in out11.event_envelopes:
                        _persist_event(db, emitted)
                else:
                    _logger.warning(
                        "skip rollback consume: missing kb_id/target_version_id event_id={}",
                        event.event_id,
                    )

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def handle_alert_event(payload: dict) -> None:
    """Consume alert.events and execute queued Telegram retries."""
    if payload.get("event_type") != "telegram.notify.retry":
        return
    tenant_id = str(payload.get("tenant_id") or "").strip()
    project_id = str(payload.get("project_id") or "").strip()
    if not tenant_id or not project_id:
        return

    delay_ms = int(payload.get("delay_ms") or 0)
    if delay_ms > 0:
        time.sleep(min(delay_ms / 1000.0, 5.0))

    retry_attempt = int(payload.get("retry_attempt") or 0)
    max_retry_attempts = int(payload.get("max_retry_attempts") or 3)
    db = get_db_session()
    try:
        result = notify_telegram_event(
            db=db,
            tenant_id=tenant_id,
            project_id=project_id,
            event_type=str(payload.get("source_event_type") or "unknown"),
            summary=str(payload.get("summary") or "queued telegram notify"),
            run_id=str(payload.get("run_id") or "") or None,
            job_id=str(payload.get("job_id") or "") or None,
            trace_id=str(payload.get("trace_id") or "") or None,
            correlation_id=str(payload.get("correlation_id") or "") or None,
            extra=dict(payload.get("extra") or {}),
            queue_on_failure=False,
            retry_attempt=retry_attempt,
            max_retry_attempts=max_retry_attempts,
        )
        reason = str(result.get("reason") or "")
        status_code = int(result.get("status_code") or 0)
        retryable = (
            reason.startswith("network_error")
            or reason.startswith("notify_error")
            or reason.startswith("circuit_open")
            or reason.startswith("telegram_not_ok")
            or (reason.startswith("http_error:") and status_code >= 500)
        )
        if (not result.get("delivered")) and retryable and retry_attempt < max_retry_attempts:
            publish(
                SYSTEM_TOPICS.ALERT_EVENTS,
                {
                    **payload,
                    "retry_attempt": retry_attempt + 1,
                    "delay_ms": max(1000, int(payload.get("delay_ms") or 1000) * 2),
                },
            )
    finally:
        db.close()


def consume_orchestrator_topic(topic: str) -> None:
    consumer = RabbitMQConsumer(settings.rabbitmq_url)
    if topic == SYSTEM_TOPICS.TASK_SUBMITTED:
        consumer.consume(topic, handle_task_submitted)
    elif topic == SYSTEM_TOPICS.JOB_STATUS:
        consumer.consume(topic, handle_job_status)
    elif topic == SYSTEM_TOPICS.COMPOSE_STATUS:
        consumer.consume(topic, handle_compose_status)
    elif topic == SYSTEM_TOPICS.SKILL_EVENTS:
        consumer.consume(topic, handle_skill_event)
    elif topic == SYSTEM_TOPICS.ALERT_EVENTS:
        consumer.consume(topic, handle_alert_event)


@router.post("/events", status_code=202)
def ingest_event(event: EventEnvelope, db: Session = Depends(get_db)) -> dict[str, str]:
    _persist_event(db, event)

    if event.event_type in {"job.claimed", "job.succeeded", "job.failed"}:
        handle_job_status(event.model_dump(mode="json"))
    elif event.event_type in {"compose.completed", "compose.failed"}:
        handle_compose_status(event.model_dump(mode="json"))
    elif event.event_type == "task.submitted":
        handle_task_submitted(event.model_dump(mode="json"))
    else:
        _logger.info("ignore event_type={} in sync endpoint", event.event_type)

    run_id = event.run_id
    if run_id:
        stage_event = EventEnvelope(
            event_type="run.stage.changed",
            producer="orchestrator",
            occurred_at=datetime.now(timezone.utc),
            tenant_id=event.tenant_id,
            project_id=event.project_id,
            idempotency_key=event.idempotency_key,
            run_id=run_id,
            trace_id=event.trace_id,
            correlation_id=event.correlation_id,
            payload={"from_event": event.event_type},
        )
        _persist_event(db, stage_event)
        publish(SYSTEM_TOPICS.JOB_STATUS, stage_event.model_dump(mode="json"))

    db.commit()
    return {"status": "accepted"}
