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
        """Rank profiles by weighted score: quality × quality_weight - cost × cost_weight - latency × latency_weight.

        Weights are derived from task_spec.budget_profile:
        - "premium":  quality 0.7, cost 0.1, latency 0.2
        - "balanced": quality 0.4, cost 0.3, latency 0.3
        - "economy":  quality 0.1, cost 0.6, latency 0.3
        """
        budget = getattr(task_spec, "budget_profile", "balanced") or "balanced"
        weights = {
            "premium":  (0.7, 0.1, 0.2),
            "balanced": (0.4, 0.3, 0.3),
            "economy":  (0.1, 0.6, 0.3),
        }.get(budget, (0.4, 0.3, 0.3))
        w_quality, w_cost, w_latency = weights

        def score(p: ModelProfile) -> float:
            params: dict = p.params_json or {}
            quality = float(params.get("quality_score", 5.0)) / 10.0
            # Normalise cost per 1K tokens to [0, 1]: $0 → 1.0 (best), $0.1+ → 0.0
            raw_cost = float(params.get("cost_per_1k_tokens", 0.01))
            cost_norm = max(0.0, 1.0 - raw_cost / 0.1)
            # Normalise latency in ms to [0, 1]: 0ms → 1.0, 60_000ms+ → 0.0
            raw_lat = float(params.get("latency_ms", 3000.0))
            lat_norm = max(0.0, 1.0 - raw_lat / 60_000.0)
            return w_quality * quality + w_cost * cost_norm + w_latency * lat_norm

        return sorted(profiles, key=score, reverse=True)
