from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

_ERROR_CODE_RE = re.compile(r"^([A-Z]+-[A-Z_]+-\d{3})\s*:\s*(.+)$")
_DEFAULT_ERROR_CODE = "SYS-DEPENDENCY-001"
_OWNER_MODULE = "ainern2d-studio-api"
_ERROR_SCHEMA_VERSION = "1.0"


def _split_error_code(error_code: str) -> tuple[str, str]:
    parts = error_code.split("-")
    if len(parts) < 2:
        return "", ""
    return parts[0], parts[1]


def _http_status_for(error_code: str) -> int:
    domain, category = _split_error_code(error_code)
    if category == "VALIDATION":
        return 422
    if domain == "REQ" and category == "IDEMPOTENCY":
        return 409
    if domain == "AUTH" and category == "FORBIDDEN":
        return 403
    if domain in {"ORCH", "PLAN", "ROUTE", "WORKER", "COMPOSE", "ASSET", "RAG", "OBS", "SYS"}:
        return 500
    return 500


def _default_error_code_for_status(status_code: int) -> str:
    if status_code in {400, 422}:
        return "REQ-VALIDATION-001"
    if status_code == 401:
        return "AUTH-VALIDATION-001"
    if status_code == 403:
        return "AUTH-FORBIDDEN-002"
    if status_code == 404:
        return "REQ-VALIDATION-001"
    if status_code == 409:
        return "REQ-IDEMPOTENCY-001"
    return _DEFAULT_ERROR_CODE


def _retryable_for(error_code: str) -> bool:
    domain, category = _split_error_code(error_code)
    if category in {"VALIDATION", "FORBIDDEN", "IDEMPOTENCY"}:
        return False
    if domain in {"ORCH", "PLAN", "ROUTE", "WORKER", "COMPOSE", "ASSET", "RAG", "OBS", "SYS"}:
        return True
    return False


def _parse_value_error(exc: ValueError) -> tuple[str, str]:
    raw = str(exc).strip()
    match = _ERROR_CODE_RE.match(raw)
    if match:
        return match.group(1), match.group(2).strip()
    if not raw:
        return _DEFAULT_ERROR_CODE, "unexpected value error"
    return _DEFAULT_ERROR_CODE, raw


def _parse_http_exception(exc: HTTPException) -> tuple[str, str, dict[str, Any]]:
    detail = exc.detail
    if isinstance(detail, dict):
        code = str(detail.get("error_code") or _default_error_code_for_status(exc.status_code))
        message = str(detail.get("message") or detail.get("detail") or "request failed")
        return code, message, detail
    if isinstance(detail, list):
        return _default_error_code_for_status(exc.status_code), "request validation failed", {"issues": detail}
    if isinstance(detail, str):
        match = _ERROR_CODE_RE.match(detail.strip())
        if match:
            return match.group(1), match.group(2).strip(), {"raw_detail": detail}
        return _default_error_code_for_status(exc.status_code), detail, {"raw_detail": detail}
    return _default_error_code_for_status(exc.status_code), "request failed", {}


def _request_trace_id(request: Request) -> str:
    return (
        request.headers.get("x-trace-id")
        or request.headers.get("trace_id")
        or f"tr_{uuid4().hex[:16]}"
    )


def _request_correlation_id(request: Request) -> str:
    return (
        request.headers.get("x-correlation-id")
        or request.headers.get("correlation_id")
        or f"co_{uuid4().hex[:16]}"
    )


def _build_error_response(
    *,
    request: Request,
    status_code: int,
    error_code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    trace_id = _request_trace_id(request)
    correlation_id = _request_correlation_id(request)
    merged_details = {
        "path": request.url.path,
        "method": request.method,
        **(details or {}),
    }
    error_obj = {
        "schema_version": _ERROR_SCHEMA_VERSION,
        "error_code": error_code,
        "message": message,
        "retryable": _retryable_for(error_code),
        "http_status": status_code,
        "owner_module": _OWNER_MODULE,
        "trace_id": trace_id,
        "correlation_id": correlation_id,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "details": merged_details,
    }
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "error": error_obj,
            # Compatibility fields for existing callers/tests.
            **error_obj,
        },
    )


def build_error_response(
    *,
    request: Request,
    status_code: int,
    error_code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    return _build_error_response(
        request=request,
        status_code=status_code,
        error_code=error_code,
        message=message,
        details=details,
    )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def _handle_request_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _build_error_response(
            request=request,
            status_code=422,
            error_code="REQ-VALIDATION-001",
            message="request validation failed",
            details={"issues": exc.errors()},
        )

    @app.exception_handler(HTTPException)
    async def _handle_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
        error_code, message, details = _parse_http_exception(exc)
        return _build_error_response(
            request=request,
            status_code=exc.status_code,
            error_code=error_code,
            message=message,
            details=details,
        )

    @app.exception_handler(ValueError)
    async def _handle_value_error(request: Request, exc: ValueError) -> JSONResponse:
        error_code, message = _parse_value_error(exc)
        status_code = _http_status_for(error_code)
        return _build_error_response(
            request=request,
            status_code=status_code,
            error_code=error_code,
            message=message,
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected_exception(request: Request, exc: Exception) -> JSONResponse:
        return _build_error_response(
            request=request,
            status_code=500,
            error_code=_DEFAULT_ERROR_CODE,
            message=str(exc) if str(exc) else "internal server error",
            details={"exception_type": type(exc).__name__},
        )
