"""Dispatch routing table – maps JobType → worker_type string."""

from __future__ import annotations

from ainern2d_shared.ainer_db_models.enum_models import JobType
from ainern2d_shared.telemetry.logging import get_logger

logger = get_logger(__name__)

# Static mapping from JobType enum values to the target worker service name.
_JOB_WORKER_MAP: dict[JobType, str] = {
    JobType.extract_entities: "worker-llm",
    JobType.canonicalize_entities: "worker-llm",
    JobType.match_assets: "worker-llm",
    JobType.plan_storyboard: "worker-llm",
    JobType.plan_prompt: "worker-llm",
    JobType.compile_dsl: "worker-llm",
    JobType.evaluate_quality: "worker-llm",
    JobType.synth_audio: "worker-audio",
    JobType.render_video: "worker-video",
    JobType.render_lipsync: "worker-lipsync",
    JobType.compose_final: "worker-composer",
}


class RoutingTable:
    """Resolves a JobType to the worker_type string used for dispatch."""

    def resolve(self, job_type: JobType, gpu_tier: str | None = None) -> str:
        """Return the worker-type string responsible for *job_type*.

        Raises ``ValueError`` if the job type has no mapping.
        """
        worker_type = _JOB_WORKER_MAP.get(job_type)
        if worker_type is None:
            raise ValueError(f"no worker mapping for job type {job_type!r}")
        logger.debug("resolved %s -> %s (gpu_tier=%s)", job_type, worker_type, gpu_tier)
        return worker_type