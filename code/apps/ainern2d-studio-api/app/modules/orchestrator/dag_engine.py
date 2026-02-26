from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.enum_models import (
    JobStatus,
    JobType,
    RenderStage,
)
from ainern2d_shared.ainer_db_models.pipeline_models import (
    Job,
    JobDependency,
    RenderRun,
)
from ainern2d_shared.telemetry.logging import get_logger

logger = get_logger("orchestrator.dag_engine")

# Maps each JobType to its pipeline stage.
_JOB_STAGE: Dict[JobType, RenderStage] = {
    # Story entry pipeline
    JobType.ingest_story:             RenderStage.route,
    JobType.route_language:           RenderStage.route,
    JobType.plan_scene_shots:         RenderStage.plan,
    JobType.extract_entities:         RenderStage.entity,
    # Audio pipeline
    JobType.plan_audio_assets:        RenderStage.audio,
    JobType.assemble_audio_timeline:  RenderStage.audio,
    # Canonicalization + asset matching
    JobType.canonicalize_entities:    RenderStage.entity,
    JobType.match_assets:             RenderStage.knowledge,
    # Visual + prompt
    JobType.plan_visual_render:       RenderStage.plan,
    JobType.plan_storyboard:          RenderStage.plan,
    JobType.plan_prompt:              RenderStage.plan,
    JobType.compile_dsl:              RenderStage.route,
    # Execution workers
    JobType.synth_audio:              RenderStage.audio,
    JobType.render_video:             RenderStage.video,
    JobType.render_lipsync:           RenderStage.lipsync,
    # Quality + composition
    JobType.evaluate_quality:         RenderStage.observe,
    JobType.compose_final:            RenderStage.compose,
}

# Full pipeline sequence (each inner list = parallel batch; outer list = ordered stages).
_DEFAULT_SEQUENCE: List[List[JobType]] = [
    # Stage 1: story ingestion
    [JobType.ingest_story],
    # Stage 2: language routing
    [JobType.route_language],
    # Stage 3: scene/shot planning + entity extraction (parallel)
    [JobType.plan_scene_shots, JobType.extract_entities],
    # Stage 4: audio asset planning
    [JobType.plan_audio_assets],
    # Stage 5: canonicalization + audio synthesis (parallel)
    [JobType.canonicalize_entities, JobType.synth_audio],
    # Stage 6: audio timeline assembly
    [JobType.assemble_audio_timeline],
    # Stage 7: asset matching
    [JobType.match_assets],
    # Stage 8: visual render planning
    [JobType.plan_visual_render],
    # Stage 9: prompt planning
    [JobType.plan_prompt],
    # Stage 10: DSL compilation
    [JobType.compile_dsl],
    # Stage 11: video render + lipsync
    [JobType.render_video, JobType.render_lipsync],
    # Stage 12: quality evaluation + compose (parallel start; compose depends on both workers)
    [JobType.evaluate_quality],
    [JobType.compose_final],
]


class DagEngine:
    """Builds and resolves a Job dependency DAG for a RenderRun."""

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # Build DAG
    # ------------------------------------------------------------------

    def build_dag(
        self,
        run_id: str,
        shot_plan: Dict[str, Any],
    ) -> List[Job]:
        """Create Job rows with dependency edges from a shot plan.

        ``shot_plan`` may contain an optional ``"steps"`` key that overrides
        the default sequence.  Each entry is a dict with ``"job_type"`` and
        optional ``"depends_on"`` (list of job-type names).
        """
        run: Optional[RenderRun] = self.db.get(RenderRun, run_id)
        if run is None:
            raise LookupError(f"RenderRun id={run_id} not found")

        steps = shot_plan.get("steps") or self._default_steps()
        created_jobs: Dict[str, Job] = {}
        previous_ids: List[str] = []

        for step in steps:
            jt = JobType(step["job_type"])
            job_id = f"job_{uuid4().hex[:12]}"
            job = Job(
                id=job_id,
                tenant_id=run.tenant_id,
                project_id=run.project_id,
                run_id=run_id,
                chapter_id=run.chapter_id,
                shot_id=shot_plan.get("shot_id"),
                job_type=jt,
                stage=_JOB_STAGE.get(jt, RenderStage.execute),
                status=JobStatus.queued,
                priority=step.get("priority", 0),
                payload_json=step.get("payload", {}),
                idempotency_key=f"{run_id}_{jt.value}_{uuid4().hex[:8]}",
            )
            self.db.add(job)
            self.db.flush()
            created_jobs[jt.value] = job

            # Resolve explicit deps or fall back to previous layer.
            dep_names: List[str] = step.get("depends_on") or []
            dep_ids = [created_jobs[d].id for d in dep_names if d in created_jobs]
            if not dep_ids and previous_ids:
                dep_ids = list(previous_ids)

            for dep_id in dep_ids:
                dep = JobDependency(
                    id=f"jdep_{uuid4().hex[:12]}",
                    tenant_id=run.tenant_id,
                    project_id=run.project_id,
                    job_id=job_id,
                    depends_on_job_id=dep_id,
                )
                self.db.add(dep)

            previous_ids = [job_id]

        self.db.flush()
        logger.info("dag_built | run_id={} jobs={}", run_id, len(created_jobs))
        return list(created_jobs.values())

    # ------------------------------------------------------------------
    # Resolve next executable jobs
    # ------------------------------------------------------------------

    def resolve_next(self, run_id: str) -> List[Job]:
        """Return queued jobs whose dependencies are all succeeded."""
        all_jobs: Sequence[Job] = (
            self.db.execute(
                select(Job).filter_by(run_id=run_id)
            ).scalars().all()
        )
        job_map = {j.id: j for j in all_jobs}

        deps: Sequence[JobDependency] = (
            self.db.execute(
                select(JobDependency).where(
                    JobDependency.job_id.in_([j.id for j in all_jobs])
                )
            ).scalars().all()
        )
        dep_map: Dict[str, List[str]] = {}
        for d in deps:
            dep_map.setdefault(d.job_id, []).append(d.depends_on_job_id)

        ready: List[Job] = []
        for job in all_jobs:
            if job.status != JobStatus.queued:
                continue
            upstream_ids = dep_map.get(job.id, [])
            if all(
                job_map[uid].status == JobStatus.success
                for uid in upstream_ids
                if uid in job_map
            ):
                ready.append(job)

        logger.info("resolve_next | run_id={} ready={}", run_id, len(ready))
        return ready

    # ------------------------------------------------------------------
    # Completion check
    # ------------------------------------------------------------------

    def is_complete(self, run_id: str) -> bool:
        """True when every job in the run has a terminal status."""
        jobs: Sequence[Job] = (
            self.db.execute(select(Job).filter_by(run_id=run_id)).scalars().all()
        )
        if not jobs:
            return False
        terminal = {JobStatus.success, JobStatus.failed, JobStatus.canceled}
        return all(j.status in terminal for j in jobs)

    def all_succeeded(self, run_id: str) -> bool:
        """True when every job in the run has succeeded."""
        jobs: Sequence[Job] = (
            self.db.execute(select(Job).filter_by(run_id=run_id)).scalars().all()
        )
        if not jobs:
            return False
        return all(j.status == JobStatus.success for j in jobs)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _default_steps() -> List[Dict[str, Any]]:
        """Build steps list with explicit depends_on for each parallel batch."""
        steps: List[Dict[str, Any]] = []
        prev_layer: List[str] = []

        for batch in _DEFAULT_SEQUENCE:
            batch_names = [jt.value for jt in batch]
            for jt in batch:
                step: Dict[str, Any] = {"job_type": jt.value, "payload": {}}
                if prev_layer:
                    step["depends_on"] = list(prev_layer)
                steps.append(step)
            prev_layer = batch_names

        return steps
