from __future__ import annotations

from typing import Optional

import httpx
from sqlalchemy.orm import Session

from ainern2d_shared.ainer_db_models.provider_models import ModelProfile, ModelProvider, ProviderAdapter
from ainern2d_shared.telemetry.logging import get_logger

logger = get_logger("model_router.provider_registry")

_PROBE_TIMEOUT_S = 5.0


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

    def get_endpoint(self, profile_id: str) -> Optional[ModelProvider]:
        """Resolve the ModelProvider (endpoint) for a given profile."""
        profile: Optional[ModelProfile] = self.db.get(ModelProfile, profile_id)
        if profile is None:
            return None
        return self.db.get(ModelProvider, profile.provider_id)

    def check_health(self, profile_id: str) -> dict:
        """Check whether the endpoint backing *profile_id* is healthy using Adapter Spec Probe if available."""
        import time 

        profile: Optional[ModelProfile] = self.db.get(ModelProfile, profile_id)
        if profile is None:
            return {"status": "error", "error_message": "profile not found", "latency_ms": 0, "response_preview": ""}
            
        provider: Optional[ModelProvider] = self.db.get(ModelProvider, profile.provider_id)
        if provider is None or not provider.endpoint:
            return {"status": "error", "error_message": "provider or endpoint not found", "latency_ms": 0, "response_preview": ""}

        adapter: Optional[ProviderAdapter] = None
        if profile.adapter_id:
            adapter = self.db.get(ProviderAdapter, profile.adapter_id)
            
        try:
            with httpx.Client(timeout=_PROBE_TIMEOUT_S) as client:
                t0 = time.monotonic()
                if adapter and adapter.request_json and adapter.request_json.get("body_template"):
                    # Use ProviderAdapter for full functional POST Probe
                    url = adapter.endpoint_json.get("url", provider.endpoint) if adapter.endpoint_json else provider.endpoint
                    method = adapter.endpoint_json.get("method", "POST") if adapter.endpoint_json else "POST"
                    
                    headers = adapter.request_json.get("headers", {})
                    if adapter.auth_json and adapter.auth_json.get("type") == "bearer":
                        headers[adapter.auth_json.get("header_name", "Authorization")] = f"{adapter.auth_json.get('prefix', 'Bearer ')}probe_test_token"
                        
                    body = adapter.request_json.get("body_template", {})
                    
                    if method.upper() == "POST":
                        resp = client.post(url, headers=headers, json=body)
                    else:
                        resp = client.request(method, url, headers=headers)
                        
                    latency_ms = int((time.monotonic() - t0) * 1000)
                    is_ok = resp.status_code < 500
                    
                    return {
                        "status": "success" if is_ok else "error",
                        "latency_ms": latency_ms,
                        "response_preview": resp.text[:200],
                        "error_message": "" if is_ok else f"HTTP {resp.status_code}",
                        "method": "POST"
                    }
                else:
                    # Fallback to simple HEAD request
                    resp = client.head(provider.endpoint)
                    latency_ms = int((time.monotonic() - t0) * 1000)
                    is_ok = resp.status_code < 500
                    return {
                        "status": "success" if is_ok else "error",
                        "latency_ms": latency_ms,
                        "response_preview": "",
                        "error_message": "" if is_ok else f"HTTP {resp.status_code}",
                        "method": "HEAD"
                    }
        except Exception as exc:
            return {
                "status": "error",
                "latency_ms": 0,
                "response_preview": "",
                "error_message": str(exc),
                "method": "UNKNOWN"
            }
