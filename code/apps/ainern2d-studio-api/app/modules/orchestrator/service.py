from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.enum_models import (
    JobStatus,
    RenderStage,
    RunStatus,
)
from ainern2d_shared.ainer_db_models.pipeline_models import Job, RenderRun
from ainern2d_shared.schemas.events import EventEnvelope
from ainern2d_shared.telemetry.logging import get_logger

from .dag_engine import DagEngine
from .event_log import EventLogger
from .recovery import RecoveryManager
from .state_machine import RunStateMachine

logger = get_logger("orchestrator.service")


class OrchestratorService:
    """Façade that ties together StateMachine, DagEngine, EventLogger,
    and RecoveryManager to drive a RenderRun through its pipeline."""

    def __init__(self, db: Session):
        self.db = db
        self.state_machine = RunStateMachine(db)
        self.dag = DagEngine(db)
        self.event_logger = EventLogger(db)
        self.recovery = RecoveryManager(db)

    # ------------------------------------------------------------------
    # Main event dispatcher
    # ------------------------------------------------------------------

    def handle_event(self, event: EventEnvelope) -> None:
        """Route an incoming event to the appropriate handler."""
        self.event_logger.log(event)

        etype = event.event_type
        if etype == "job.succeeded":
            self._on_job_succeeded(event)
        elif etype == "job.failed":
            self._on_job_failed(event)
        elif etype == "job.claimed":
            self._on_job_claimed(event)
        elif etype == "run.created":
            self._on_run_created(event)
        elif etype == "run.cancel.requested":
            self._on_run_cancel(event)
        else:
            logger.info("unhandled_event_type | type={}", etype)

    # ------------------------------------------------------------------
    # Advance run
    # ------------------------------------------------------------------

    def advance_run(self, run_id: str) -> None:
        """Check if the current stage is complete; if so, transition to
        the next stage and dispatch the next batch of jobs."""
        run: Optional[RenderRun] = self.db.get(RenderRun, run_id)
        if run is None:
            logger.error("advance_run_not_found | run_id={}", run_id)
            return

        if run.status in (RunStatus.failed, RunStatus.canceled, RunStatus.success):
            return

        # Resolve any ready jobs in the current DAG.
        ready_jobs = self.dag.resolve_next(run_id)
        if ready_jobs:
            self._dispatch_jobs(ready_jobs, run)
            return

        # If no more jobs are ready, check completion.
        if not self.dag.is_complete(run_id):
            return

        # All jobs finished — decide if we advance or finalize.
        if self.dag.all_succeeded(run_id):
            next_stage = self.state_machine.next_stage(run.stage)
            if next_stage is None:
                # Pipeline finished.
                run.status = RunStatus.success
                run.finished_at = datetime.now(timezone.utc)
                self.db.flush()
                logger.info("run_completed | run_id={}", run_id)
                return

            ok = self.state_machine.transition(
                run_id,
                from_stage=run.stage,
                to_stage=next_stage,
                guard_result={"passed": True, "reason": "all_jobs_succeeded"},
            )
            if ok:
                self._build_and_dispatch_stage(run, next_stage)
        else:
            # Some jobs failed — mark run as degraded/failed.
            run.status = RunStatus.failed
            run.finished_at = datetime.now(timezone.utc)
            self.db.flush()
            self.recovery.compensate(run_id, run.stage)
            logger.warning("run_failed | run_id={} stage={}", run_id, run.stage.value)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_run_created(self, event: EventEnvelope) -> None:
        run_id = event.run_id
        if not run_id:
            return
        run = self.db.get(RenderRun, run_id)
        if run is None:
            return
        shot_plan = event.payload.get("shot_plan", {})
        self.dag.build_dag(run_id, shot_plan)
        self.advance_run(run_id)

    def _on_job_succeeded(self, event: EventEnvelope) -> None:
        job_id = event.payload.get("job_id") or event.job_id
        if not job_id:
            return
        job: Optional[Job] = self.db.get(Job, job_id)
        if job is None:
            return
        job.status = JobStatus.success
        job.result_json = event.payload.get("result_data")
        self.db.flush()

        if job.run_id:
            self.advance_run(job.run_id)

    def _on_job_failed(self, event: EventEnvelope) -> None:
        job_id = event.payload.get("job_id") or event.job_id
        if not job_id:
            return
        job: Optional[Job] = self.db.get(Job, job_id)
        if job is None:
            return

        job.status = JobStatus.failed
        job.attempts += 1
        job.result_json = {
            "error_code": event.payload.get("error_code"),
            "error_message": event.payload.get("error_message"),
            "retryable": event.payload.get("retryable", True),
        }
        self.db.flush()

        if self.recovery.should_retry(job):
            self.recovery.schedule_retry(job)
        elif job.run_id:
            self.advance_run(job.run_id)

    def _on_job_claimed(self, event: EventEnvelope) -> None:
        job_id = event.payload.get("job_id") or event.job_id
        if not job_id:
            return
        job: Optional[Job] = self.db.get(Job, job_id)
        if job is None:
            return
        job.status = JobStatus.claimed
        job.locked_by = event.payload.get("worker_node_id")
        job.locked_at = datetime.now(timezone.utc)
        self.db.flush()

    def _on_run_cancel(self, event: EventEnvelope) -> None:
        run_id = event.run_id
        if not run_id:
            return
        run = self.db.get(RenderRun, run_id)
        if run is None:
            return
        run.status = RunStatus.canceled
        run.finished_at = datetime.now(timezone.utc)
        self.db.flush()
        logger.info("run_canceled | run_id={}", run_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_and_dispatch_stage(
        self, run: RenderRun, stage: RenderStage
    ) -> None:
        """Build a minimal DAG for the new stage and dispatch ready jobs."""
        ready = self.dag.resolve_next(run.id)
        if ready:
            self._dispatch_jobs(ready, run)

    def _dispatch_jobs(self, jobs: list[Job], run: RenderRun) -> None:
        """Mark jobs as enqueued.  Actual queue publishing is handled by
        an outer integration layer; we only update status here."""
        for job in jobs:
            job.status = JobStatus.enqueued
        self.db.flush()
        logger.info(
            "jobs_dispatched | run_id={} count={}",
            run.id, len(jobs),
        )
