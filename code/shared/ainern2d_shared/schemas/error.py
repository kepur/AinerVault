from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict


class BaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ErrorInfo(BaseSchema):
    code: str
    message: str
    retriable: bool = False
    details: Optional[Dict[str, Any]] = None


class AinerErrorResponse(BaseSchema):
    request_id: str
    trace_id: str
    correlation_id: str
    error: ErrorInfo
    schema_version: str = "1.0"
