"""API error mapping tests for ValueError -> structured contract payload."""
from __future__ import annotations

import os
import sys

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../shared"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../"))

from app.api.error_mapping import register_error_handlers


def test_value_error_mapping_for_skill03_validation_code() -> None:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/raise-skill03")
    def _raise_skill03_error() -> None:
        raise ValueError(
            "REQ-VALIDATION-001: segments list is empty — SKILL 01 output required"
        )

    with TestClient(app) as client:
        response = client.get(
            "/raise-skill03",
            headers={
                "x-trace-id": "tr_test_skill03",
                "x-correlation-id": "co_test_skill03",
            },
        )

    assert response.status_code == 422
    payload = response.json()
    assert payload["error_code"] == "REQ-VALIDATION-001"
    assert payload["error"]["error_code"] == "REQ-VALIDATION-001"
    assert payload["retryable"] is False
    assert payload["http_status"] == 422
    assert payload["owner_module"] == "ainern2d-studio-api"
    assert payload["trace_id"] == "tr_test_skill03"
    assert payload["correlation_id"] == "co_test_skill03"


def test_value_error_mapping_for_idempotency_code() -> None:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/raise-idem")
    def _raise_idempotency_error() -> None:
        raise ValueError("REQ-IDEMPOTENCY-001: duplicate request")

    with TestClient(app) as client:
        response = client.get("/raise-idem")

    assert response.status_code == 409
    payload = response.json()
    assert payload["error_code"] == "REQ-IDEMPOTENCY-001"
    assert payload["error"]["error_code"] == "REQ-IDEMPOTENCY-001"
    assert payload["retryable"] is False
    assert payload["http_status"] == 409


def test_http_exception_mapping_keeps_error_contract() -> None:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/raise-http")
    def _raise_http_error() -> None:
        raise HTTPException(status_code=403, detail="AUTH-FORBIDDEN-002: no project permission")

    with TestClient(app) as client:
        response = client.get("/raise-http")

    assert response.status_code == 403
    payload = response.json()
    assert payload["success"] is False
    assert payload["error_code"] == "AUTH-FORBIDDEN-002"
    assert payload["error"]["owner_module"] == "ainern2d-studio-api"


def test_request_validation_mapping_keeps_structured_payload() -> None:
    app = FastAPI()
    register_error_handlers(app)

    class _Body(BaseModel):
        required_value: str

    @app.post("/raise-validation")
    def _raise_validation(body: _Body) -> dict[str, str]:
        return {"ok": body.required_value}

    with TestClient(app) as client:
        response = client.post("/raise-validation", json={})

    assert response.status_code == 422
    payload = response.json()
    assert payload["error_code"] == "REQ-VALIDATION-001"
    assert payload["error"]["details"]["issues"]
