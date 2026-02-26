from __future__ import annotations

from typing import Optional

import httpx
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.provider_models import ModelProfile, ModelProvider
from ainern2d_shared.telemetry.logging import get_logger

logger = get_logger("model_router.health")

_PROBE_TIMEOUT_S = 5.0


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
        """
        profiles: list[ModelProfile] = self.db.query(ModelProfile).all()
        result: dict[str, bool] = {}
        for p in profiles:
            provider: Optional[ModelProvider] = self.db.get(ModelProvider, p.provider_id)
            result[p.id] = self._probe(provider)
        logger.info("check_all | endpoints={}", len(result))
        return result

    def mark_unhealthy(self, profile_id: str) -> None:
        """Flag the endpoint backing *profile_id* as unhealthy in the audit log."""
        profile: Optional[ModelProfile] = self.db.get(ModelProfile, profile_id)
        if profile is None:
            logger.warning("mark_unhealthy_unknown | profile_id={}", profile_id)
            return
        logger.warning(
            "endpoint_marked_unhealthy | profile_id={} provider_id={}",
            profile_id, profile.provider_id,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _probe(provider: Optional[ModelProvider]) -> bool:
        """Perform a synchronous HTTP HEAD probe against the provider endpoint."""
        if provider is None or not provider.endpoint:
            return False
        try:
            # Use HEAD for cheapest possible health check; fall back to GET
            with httpx.Client(timeout=_PROBE_TIMEOUT_S) as client:
                resp = client.head(provider.endpoint)
                return resp.status_code < 500
        except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPError):
            return False
