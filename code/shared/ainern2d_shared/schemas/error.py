from typing import Any, Dict, Optional

from .base import BaseSchema


class ErrorInfo(BaseSchema):
    code: str
    message: str
    retryable: bool = False
    details: Optional[Dict[str, Any]] = None


class AinerErrorResponse(BaseSchema):
    request_id: str
    trace_id: str
    correlation_id: str
    error: ErrorInfo
    schema_version: str = "1.0"
