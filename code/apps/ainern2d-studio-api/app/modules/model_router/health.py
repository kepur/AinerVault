from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.provider_models import ModelProfile, ProviderEndpoint
from ainern2d_shared.telemetry.logging import get_logger

logger = get_logger("model_router.health")


class EndpointHealthMonitor:
    """Monitor and report on provider endpoint health."""

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_all(self) -> dict[str, bool]:
        """Probe every registered endpoint and return a health map.

        Returns ``{profile_id: is_healthy}`` for each ModelProfile.
        TODO: implement real HTTP/gRPC health probes.
        """
        profiles: list[ModelProfile] = self.db.query(ModelProfile).all()
        result: dict[str, bool] = {}
        for p in profiles:
            endpoint: Optional[ProviderEndpoint] = self.db.get(
                ProviderEndpoint, p.provider_id,
            )
            result[p.id] = self._probe(endpoint)
        logger.info("check_all | endpoints={}", len(result))
        return result

    def mark_unhealthy(self, profile_id: str) -> None:
        """Flag the endpoint backing *profile_id* as unhealthy.

        TODO: define a status column on ProviderEndpoint or
        maintain a separate health-state table.
        """
        profile: Optional[ModelProfile] = self.db.get(ModelProfile, profile_id)
        if profile is None:
            logger.warning("mark_unhealthy_unknown | profile_id={}", profile_id)
            return
        # Stub: log the action — actual status update pending schema addition.
        logger.warning(
            "endpoint_marked_unhealthy | profile_id={} provider_id={}",
            profile_id, profile.provider_id,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _probe(endpoint: Optional[ProviderEndpoint]) -> bool:
        """Perform a health probe against *endpoint*.

        TODO: implement real connectivity check.
        """
        if endpoint is None:
            return False
        return True
