"""
SkillDispatcher — 将 DAG Job 映射到对应 SKILL 服务并执行。

工作流:
  1. OrchestratorService._dispatch_jobs() 将 Job 置为 enqueued
  2. SkillDispatcher.execute_job() 被调用（同步或通过轮询）
  3. 根据 job.job_type 查找 skill_id，调用 SkillRegistry.dispatch()
  4. 将 Job 状态更新为 success / failed

使用示例 (同步模式，适用于单测/开发):
    dispatcher = SkillDispatcher(db)
    dispatcher.execute_job(job)

使用示例 (轮询守护模式):
    SkillDispatcher(db).run_poll_loop()
"""
from __future__ import annotations

import time
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.enum_models import JobStatus, JobType
from ainern2d_shared.ainer_db_models.pipeline_models import Job
from ainern2d_shared.services.base_skill import SkillContext

from .skill_registry import SkillRegistry

# ── JobType → skill_id mapping ────────────────────────────────────────────────
# Workers (render_video / render_lipsync / synth_audio) are not SKILL services
# — they are forwarded to Worker-Hub and not handled here.
_JOB_TYPE_TO_SKILL: dict[str, str] = {
    JobType.ingest_story.value:            "skill_01",
    JobType.route_language.value:          "skill_02",
    JobType.plan_scene_shots.value:        "skill_03",
    JobType.extract_entities.value:        "skill_04",
    JobType.plan_audio_assets.value:       "skill_05",
    # skill_06 (assemble_audio_timeline) lives in ainern2d-composer
    JobType.canonicalize_entities.value:   "skill_07",
    JobType.match_assets.value:            "skill_08",
    JobType.plan_visual_render.value:      "skill_09",
    JobType.plan_prompt.value:             "skill_10",
    # plan_storyboard is an alias for scene/shot planning (same as plan_scene_shots)
    JobType.plan_storyboard.value:         "skill_03",
    # compile_dsl lives in ainern2d-composer (skill_20)
    JobType.evaluate_quality.value:        "skill_16",
}

# Job types handled by external workers (not dispatched through SkillRegistry)
_WORKER_JOB_TYPES: frozenset[str] = frozenset({
    JobType.synth_audio.value,
    JobType.render_video.value,
    JobType.render_lipsync.value,
    JobType.compose_final.value,
    JobType.assemble_audio_timeline.value,  # handled by composer
    JobType.compile_dsl.value,              # handled by composer
})

_POLL_INTERVAL_SECONDS = 2


class SkillDispatcher:
    """Executes enqueued SKILL jobs by delegating to SkillRegistry."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self._registry = SkillRegistry(db)

    # ── Main entry ────────────────────────────────────────────────────────────

    def execute_job(self, job: Job) -> Any:
        """Execute a single Job.  Returns the SKILL output DTO or None for worker jobs."""
        jt = job.job_type.value if hasattr(job.job_type, "value") else str(job.job_type)

        if jt in _WORKER_JOB_TYPES:
            logger.info(
                f"[SkillDispatcher] job_type={jt} is a worker job — skipping SKILL dispatch"
            )
            return None

        skill_id = _JOB_TYPE_TO_SKILL.get(jt)
        if skill_id is None:
            logger.warning(f"[SkillDispatcher] no skill_id for job_type={jt}")
            job.status = JobStatus.failed
            job.result_json = {"error_code": "SKILL-DISPATCH-001", "error_message": f"unknown job_type: {jt}"}
            self.db.flush()
            return None

        ctx = _build_ctx(job)
        payload = job.payload_json or {}

        try:
            job.status = JobStatus.claimed
            self.db.flush()

            result = self._registry.dispatch(skill_id, payload, ctx)

            job.status = JobStatus.success
            job.result_json = result.model_dump(mode="json") if hasattr(result, "model_dump") else {"status": "ok"}
            self.db.flush()
            logger.info(f"[SkillDispatcher] job={job.id} skill={skill_id} → success")
            return result

        except Exception as exc:
            err_msg = str(exc)
            err_code = "SKILL-EXEC-001"
            if ":" in err_msg:
                parts = err_msg.split(":", 1)
                if "-" in parts[0] and len(parts[0]) < 30:
                    err_code = parts[0].strip()
                    err_msg = parts[1].strip()

            job.status = JobStatus.failed
            job.attempts = (job.attempts or 0) + 1
            job.result_json = {
                "error_code": err_code,
                "error_message": err_msg,
                "retryable": True,
            }
            self.db.flush()
            logger.error(f"[SkillDispatcher] job={job.id} skill={skill_id} FAILED: {exc}")
            return None

    # ── Batch processing ──────────────────────────────────────────────────────

    def process_enqueued(self, run_id: str | None = None) -> int:
        """Process all enqueued SKILL jobs (optionally scoped to a run_id).
        Returns the number of jobs executed."""
        query = select(Job).where(Job.status == JobStatus.enqueued)
        if run_id:
            query = query.where(Job.run_id == run_id)
        jobs = self.db.execute(query).scalars().all()

        count = 0
        for job in jobs:
            jt = job.job_type.value if hasattr(job.job_type, "value") else str(job.job_type)
            if jt in _WORKER_JOB_TYPES:
                continue
            self.execute_job(job)
            count += 1

        if count:
            self.db.commit()
        return count

    def run_poll_loop(self, max_iterations: int = 0) -> None:
        """Blocking poll loop — runs until interrupted or max_iterations reached."""
        iterations = 0
        logger.info("[SkillDispatcher] poll loop started")
        while True:
            try:
                executed = self.process_enqueued()
                if executed:
                    logger.info(f"[SkillDispatcher] executed {executed} jobs")
            except Exception as exc:
                logger.error(f"[SkillDispatcher] poll error: {exc}")
            iterations += 1
            if max_iterations and iterations >= max_iterations:
                break
            time.sleep(_POLL_INTERVAL_SECONDS)

    # ── Convenience factory ───────────────────────────────────────────────────

    @staticmethod
    def list_skill_job_types() -> dict[str, str]:
        """Return the mapping of job_type → skill_id for reference."""
        return dict(_JOB_TYPE_TO_SKILL)


# ── Helper ────────────────────────────────────────────────────────────────────

def _build_ctx(job: Job) -> SkillContext:
    from ainern2d_shared.services.base_skill import SkillContext
    return SkillContext(
        tenant_id=job.tenant_id or "",
        project_id=job.project_id or "",
        run_id=job.run_id or "",
        trace_id=getattr(job, "trace_id", "") or "",
        correlation_id=getattr(job, "correlation_id", "") or "",
        idempotency_key=job.idempotency_key or f"{job.run_id}_{job.job_type}",
        schema_version="1.0",
    )
