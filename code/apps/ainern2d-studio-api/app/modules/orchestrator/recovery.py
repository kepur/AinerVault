from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.enum_models import JobStatus, RenderStage
from ainern2d_shared.ainer_db_models.pipeline_models import (
    CompensationRecord,
    Job,
    RenderRun,
)
from ainern2d_shared.telemetry.logging import get_logger

logger = get_logger("orchestrator.recovery")

# Exponential back-off parameters.
_BASE_DELAY_S = 5
_MAX_DELAY_S = 300

# Stage → compensation actions mapping.
_COMPENSATION_ACTIONS: dict[str, List[str]] = {
    RenderStage.entity.value:    ["rollback_entity_cache"],
    RenderStage.knowledge.value: ["invalidate_kb_index"],
    RenderStage.plan.value:      ["discard_draft_plan"],
    RenderStage.route.value:     ["release_route_lock"],
    RenderStage.execute.value:   ["cancel_pending_workers"],
    RenderStage.audio.value:     ["cleanup_audio_artifacts"],
    RenderStage.video.value:     ["cleanup_video_artifacts"],
    RenderStage.lipsync.value:   ["cleanup_lipsync_artifacts"],
    RenderStage.compose.value:   ["cleanup_compose_artifacts"],
    RenderStage.observe.value:   ["archive_partial_report"],
}


class RecoveryManager:
    """Handles job retry decisions, scheduling, and stage compensation."""

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # Retry logic
    # ------------------------------------------------------------------

    def should_retry(self, job: Job) -> bool:
        """Return True if the job is eligible for another attempt."""
        if job.status not in (JobStatus.failed, JobStatus.retrying):
            return False
        # Honour the retryable flag from result payload when present.
        if job.result_json and job.result_json.get("retryable") is False:
            return False
        return job.attempts < job.max_attempts

    def schedule_retry(self, job: Job) -> None:
        """Mark the job for retry with exponential back-off."""
        delay = min(
            _BASE_DELAY_S * math.pow(2, job.attempts),
            _MAX_DELAY_S,
        )
        job.status = JobStatus.retrying
        job.next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
        self.db.flush()
        logger.info(
            "retry_scheduled | job_id={} attempt={}/{} delay={}s",
            job.id, job.attempts, job.max_attempts, delay,
        )

    # ------------------------------------------------------------------
    # Compensation
    # ------------------------------------------------------------------

    def compensate(self, run_id: str, failed_stage: RenderStage) -> List[CompensationRecord]:
        """Create CompensationRecord rows for the given failed stage."""
        run: Optional[RenderRun] = self.db.get(RenderRun, run_id)
        if run is None:
            raise LookupError(f"RenderRun id={run_id} not found")

        actions = _COMPENSATION_ACTIONS.get(failed_stage.value, ["generic_cleanup"])
        records: List[CompensationRecord] = []

        # Find the triggering failed job (if any) for context.
        failed_jobs: List[Job] = list(
            self.db.execute(
                select(Job).filter_by(run_id=run_id, status=JobStatus.failed)
            ).scalars().all()
        )
        trigger_job_id = failed_jobs[0].id if failed_jobs else None

        for action_name in actions:
            rec = CompensationRecord(
                id=f"comp_{uuid4().hex[:12]}",
                tenant_id=run.tenant_id,
                project_id=run.project_id,
                run_id=run_id,
                job_id=trigger_job_id,
                compensation_phase=failed_stage.value,
                action_name=action_name,
                status="pending",
                detail=f"Auto-compensation for failed stage {failed_stage.value}",
            )
            self.db.add(rec)
            records.append(rec)

        self.db.flush()
        logger.info(
            "compensation_created | run_id={} stage={} actions={}",
            run_id, failed_stage.value, len(records),
        )
        return records
