from typing import Any, Dict, Optional
from pydantic import Field

from .base import BaseSchema


class WorkerResult(BaseSchema):
    job_id: str
    run_id: str
    worker_type: str
    status: str
    artifact_uri: Optional[str] = None
    metrics: Dict[str, Any] = Field(default_factory=dict)
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    retryable: Optional[bool] = None
    schema_version: str = "1.0"
