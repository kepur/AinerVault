"""Base adapter providing JSON-driven parameter mapping for unified HTTP execution."""

from __future__ import annotations

import copy
from typing import Any

from ainern2d_shared.ainer_db_models.pipeline_models import Job
from ainern2d_shared.ainer_db_models.provider_models import ProviderAdapter
from ainern2d_shared.telemetry.logging import get_logger

logger = get_logger(__name__)


def apply_adapter_mapping(job_payload: dict[str, Any], adapter: ProviderAdapter) -> dict[str, Any]:
    """
    Apply the ProviderAdapter JSON spec to the canonical job payload.
    Produces a generic HTTP dispatch map containing url, method, headers, and body.
    """
    # 1. Start with the body template
    req_json = adapter.request_json or {}
    body_template = copy.deepcopy(req_json.get("body_template", {}))
    param_map = req_json.get("param_map", {})
    transforms = req_json.get("transforms", {})
    
    # 2. Iterate canonical inputs provided in the job payload
    for canonical_key, value in job_payload.items():
        # Apply transforms if defined for this key
        if canonical_key in transforms:
            transform = transforms[canonical_key]
            if "default" in transform and value is None:
                value = transform["default"]
            if "clamp" in transform and isinstance(value, (int, float)):
                min_val, max_val = transform["clamp"]
                value = max(min_val, min(value, max_val))
        
        # Map canonical_key to target_key
        target_key = param_map.get(canonical_key, canonical_key)
        
        # If the target_key exists in the body template, we inject it.
        # This implementation simply assigns it at the root of the template.
        # For nested injection, a jsonpath-like resolver could be used.
        body_template[target_key] = value

    # 3. Assemble the HTTP dispatch struct
    endpoint_json = adapter.endpoint_json or {}
    auth_json = adapter.auth_json or {}
    
    headers = copy.deepcopy(req_json.get("headers", {}))
    auth_type = auth_json.get("type")
    
    if auth_type == "bearer":
        header_name = auth_json.get("header_name", "Authorization")
        prefix = auth_json.get("prefix", "Bearer ")
        # In a real impl, you'd fetch the actual token from the secrets vault via Provider ID
        token = "{{SECRET_TOKEN}}" 
        headers[header_name] = f"{prefix}{token}"
        
    dispatch = {
        "http_spec": {
            "url": endpoint_json.get("url", ""),
            "method": endpoint_json.get("method", "POST"),
            "headers": headers,
            "body": body_template,
            "timeout_sec": adapter.timeout_sec,
        },
        "response_spec": adapter.response_json or {},
        "retry_spec": adapter.retry_json or {},
    }
    
    return dispatch
