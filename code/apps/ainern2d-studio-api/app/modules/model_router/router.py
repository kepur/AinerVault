from __future__ import annotations

from uuid import uuid4

from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.provider_models import ModelProfile
from ainern2d_shared.schemas.task import DispatchDecision, TaskSpec
from ainern2d_shared.telemetry.logging import get_logger

from .provider_registry import ProviderRegistry

logger = get_logger("model_router.router")


class ModelRouter:
    """Select the best model profile for a task and build a DispatchDecision."""

    def __init__(self, db: Session, registry: ProviderRegistry):
        self.db = db
        self.registry = registry

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def route(self, task_spec: TaskSpec, worker_type: str) -> DispatchDecision:
        """Pick the optimal profile by quality → cost → latency and return
        a DispatchDecision including a fallback chain."""
        profiles = self.registry.list_profiles(worker_type)
        ranked = self._rank(profiles, task_spec)

        primary = ranked[0] if ranked else None
        fallback_chain = [p.id for p in ranked[1:4]] if len(ranked) > 1 else []

        decision = DispatchDecision(
            task_id=task_spec.task_id,
            route_id=f"rt_{uuid4().hex[:12]}",
            worker_type=worker_type,
            model_profile_id=primary.id if primary else "",
            fallback_chain=fallback_chain,
            timeout_ms=task_spec.deadline_ms or 30_000,
            cost_estimate=0.0,
            gpu_tier="",
            degrade_policy=task_spec.user_overrides or {},
        )
        logger.info(
            "route_decided | task_id={} profile={} fallbacks={}",
            task_spec.task_id,
            decision.model_profile_id,
            len(fallback_chain),
        )
        return decision

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _rank(profiles: list[ModelProfile], task_spec: TaskSpec) -> list[ModelProfile]:
        """Rank profiles by quality match → cost → latency.

        TODO: implement real scoring using params_json fields and
        task_spec.requested_quality / budget_profile.
        """
        # Stub: return profiles in their original order.
        return list(profiles)
