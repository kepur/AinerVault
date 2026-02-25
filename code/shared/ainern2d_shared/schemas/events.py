from typing import Optional, Dict, Any, Literal
from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from datetime import datetime
from uuid import uuid4


class EventEnvelope(BaseModel):
    """
    贯穿微服务与 RabbitMQ 的标准事件信封。
    请勿更改必填项结构。所有业务消息体装入 payload。
    """
    model_config = ConfigDict(populate_by_name=True)

    event_id: str = Field(default_factory=lambda: f"evt_{uuid4().hex}")
    event_type: str = Field(..., description="注册在 ainer_event_types.md 的标准类型, 如 job.succeeded")
    event_version: str = Field(default="1.0", description="事件版本")
    schema_version: str = Field(default="1.0", description="Schema 版本")
    producer: str = Field(..., description="产生事件的模块，如 orchestrator, worker-video")
    occurred_at: datetime = Field(..., description="事件发生时间 (UTC)")
    
    # 追踪/幂等上下文 (强制传递)
    tenant_id: str
    project_id: str
    idempotency_key: str
    run_id: Optional[str] = None
    job_id: Optional[str] = None
    trace_id: str
    correlation_id: str
    
    payload: Dict[str, Any] = Field(default_factory=dict, description="真正的业务消息体")


class JobStatusPayload(BaseModel):
    """
    job.* 事件 (如 job.succeeded, job.failed, job.claimed) 的 Payload 定义
    """
    job_id: str
    run_id: str
    status: Literal['created', 'claimed', 'running', 'succeeded', 'failed', 'retrying']
    worker_node_id: Optional[str] = None
    
    # 失败时携带
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    retryable: Optional[bool] = None
    
    # 成功时携带
    result_data: Optional[Dict[str, Any]] = None


class RunStageTransitionPayload(BaseModel):
    """
    run.stage.changed 事件 (仅 Orchestrator 能发) 的 Payload
    """
    run_id: str
    old_stage: str
    new_stage: str
    reason: Optional[str] = None
