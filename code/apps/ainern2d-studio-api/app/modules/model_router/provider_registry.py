from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.provider_models import ModelProfile, ProviderEndpoint
from ainern2d_shared.telemetry.logging import get_logger

logger = get_logger("model_router.provider_registry")


class ProviderRegistry:
    """Query and inspect registered model profiles and provider endpoints."""

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_profiles(self, worker_type: str) -> list[ModelProfile]:
        """Return all ModelProfile rows matching *worker_type* (purpose field)."""
        profiles = (
            self.db.query(ModelProfile)
            .filter(ModelProfile.purpose == worker_type)
            .all()
        )
        logger.info(
            "list_profiles | worker_type={} count={}",
            worker_type, len(profiles),
        )
        return profiles

    def get_endpoint(self, profile_id: str) -> Optional[ProviderEndpoint]:
        """Resolve the ProviderEndpoint for a given profile."""
        profile: Optional[ModelProfile] = self.db.get(ModelProfile, profile_id)
        if profile is None:
            return None
        return self.db.get(ProviderEndpoint, profile.provider_id)

    def check_health(self, profile_id: str) -> bool:
        """Check whether the endpoint backing *profile_id* is healthy.

        TODO: implement actual HTTP health probe.
        """
        endpoint = self.get_endpoint(profile_id)
        if endpoint is None:
            return False
        return True
