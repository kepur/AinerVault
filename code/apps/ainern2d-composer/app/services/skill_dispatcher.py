"""
ComposerSkillDispatcher — 将 ainern2d-composer 的 DAG Job 映射到 SKILL 06/20 并执行。

负责的 job_type:
  - assemble_audio_timeline → SKILL 06 (AudioTimelineService)
  - compile_dsl             → SKILL 20 (DslCompilerService)
"""
from __future__ import annotations

from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.enum_models import JobStatus, JobType
from ainern2d_shared.ainer_db_models.pipeline_models import Job
from ainern2d_shared.services.base_skill import BaseSkillService, SkillContext

from .skills.skill_06_audio_timeline import AudioTimelineService
from .skills.skill_20_dsl_compiler import DslCompilerService

# ── skill registry for composer ───────────────────────────────────────────────
_COMPOSER_SKILL_MAP: dict[str, type[BaseSkillService]] = {
    JobType.assemble_audio_timeline.value: AudioTimelineService,
    JobType.compile_dsl.value:             DslCompilerService,
}


class ComposerSkillDispatcher:
    """Executes SKILL 06 and 20 jobs within the ainern2d-composer service."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self._instances: dict[str, BaseSkillService] = {}

    # ── Instance cache ────────────────────────────────────────────────────────

    def _get_service(self, job_type_value: str) -> BaseSkillService | None:
        cls = _COMPOSER_SKILL_MAP.get(job_type_value)
        if cls is None:
            return None
        if job_type_value not in self._instances:
            self._instances[job_type_value] = cls(self.db)
        return self._instances[job_type_value]

    # ── Main entry ────────────────────────────────────────────────────────────

    def execute_job(self, job: Job) -> Any:
        """Execute a single composer SKILL job."""
        jt = job.job_type.value if hasattr(job.job_type, "value") else str(job.job_type)
        service = self._get_service(jt)

        if service is None:
            logger.warning(f"[ComposerDispatcher] no composer skill for job_type={jt}")
            return None

        ctx = _build_ctx(job)
        payload = job.payload_json or {}

        try:
            job.status = JobStatus.claimed
            self.db.flush()

            result = service.run(payload, ctx)

            job.status = JobStatus.success
            job.result_json = result.model_dump(mode="json") if hasattr(result, "model_dump") else {"status": "ok"}
            self.db.flush()
            logger.info(f"[ComposerDispatcher] job={job.id} jt={jt} → success")
            return result

        except Exception as exc:
            job.status = JobStatus.failed
            job.attempts = (job.attempts or 0) + 1
            job.result_json = {"error_code": "COMPOSE-SKILL-001", "error_message": str(exc)}
            self.db.flush()
            logger.error(f"[ComposerDispatcher] job={job.id} jt={jt} FAILED: {exc}")
            return None

    # ── Batch processing ──────────────────────────────────────────────────────

    def process_enqueued(self, run_id: str | None = None) -> int:
        """Process all enqueued composer SKILL jobs. Returns jobs executed."""
        owned_types = list(_COMPOSER_SKILL_MAP.keys())
        query = select(Job).where(
            Job.status == JobStatus.enqueued,
            Job.job_type.in_(owned_types),
        )
        if run_id:
            query = query.where(Job.run_id == run_id)

        jobs = self.db.execute(query).scalars().all()
        count = 0
        for job in jobs:
            self.execute_job(job)
            count += 1

        if count:
            self.db.commit()
        return count

    @staticmethod
    def owns_job_type(job_type_value: str) -> bool:
        return job_type_value in _COMPOSER_SKILL_MAP


# ── Helper ────────────────────────────────────────────────────────────────────

def _build_ctx(job: Job) -> SkillContext:
    return SkillContext(
        tenant_id=job.tenant_id or "",
        project_id=job.project_id or "",
        run_id=job.run_id or "",
        trace_id=getattr(job, "trace_id", "") or "",
        correlation_id=getattr(job, "correlation_id", "") or "",
        idempotency_key=job.idempotency_key or f"{job.run_id}_{job.job_type}",
        schema_version="1.0",
    )
