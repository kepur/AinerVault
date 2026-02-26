from typing import Optional, Dict, Any, List
from pydantic import Field
from datetime import datetime

from .base import BaseSchema


class TaskCreateRequest(BaseSchema):
    """
    任务（Job/Run）创建请求，网关或业务域通用。
    符合架构契约的必填上下文必须通过 Request / Header 取到，但如果写在 Body 中：
    """
    tenant_id: str = Field(description="租户ID")
    project_id: str = Field(description="项目ID")
    chapter_id: str = Field(description="内容上下文源(如小说章节ID)")
    requested_quality: Optional[str] = Field("standard", description="调度/生成质量(draft, standard, ultra)")
    language_context: Optional[str] = Field("zh-CN", description="语言环境")
    
    # 额外自定义参数
    payload: Optional[Dict[str, Any]] = Field(default_factory=dict, description="额外编排参数")


class TaskSpec(BaseSchema):
    task_id: str
    tenant_id: str
    project_id: str
    chapter_id: str
    requested_quality: str = "standard"
    language_context: str = "zh-CN"
    input_uri: str
    budget_profile: Optional[str] = None
    deadline_ms: Optional[int] = None
    priority: Optional[int] = None
    user_overrides: Dict[str, Any] = Field(default_factory=dict)
    schema_version: str = "1.0"


class DispatchDecision(BaseSchema):
    task_id: str
    route_id: str
    worker_type: str
    model_profile_id: str
    fallback_chain: List[str] = Field(default_factory=list)
    timeout_ms: int
    cost_estimate: Optional[float] = None
    gpu_tier: Optional[str] = None
    degrade_policy: Optional[Dict[str, Any]] = None
    schema_version: str = "1.0"


class TaskResponse(BaseSchema):
    """
    标准创建响应
    """
    run_id: str = Field(description="全局一次完整生成的 Run ID")
    status: str = Field(description="状态: queued, running, failed, succeeded 等")
    message: Optional[str] = Field(None, description="可选响应信息")


class TaskDetailResponse(BaseSchema):
    """
    查询任务详情的响应
    """
    run_id: str = Field(description="Run ID")
    status: str = Field(description="任务状态")
    stage: str = Field(description="业务节点 Stage (如 Extractor, Planner, Video Worker)")
    progress: float = Field(default=0.0, description="0-100 的总体进度")
    latest_error: Optional[str] = Field(None, description="最后一次的错误(如果失败)")
    final_artifact_uri: Optional[str] = Field(None, description="成功后的产物 URI")
    created_at: datetime
    updated_at: datetime


class RunDetailResponse(BaseSchema):
    run_id: str
    status: str
    stage: str
    progress: float = 0.0
    latest_error: Optional[Dict[str, Any]] = None
    final_artifact_uri: Optional[str] = None
    schema_version: str = "1.0"


class ComposeRequest(BaseSchema):
    run_id: str
    timeline_final: Dict[str, Any]
    artifact_refs: List[str] = Field(default_factory=list)
    tenant_id: str
    project_id: str
    trace_id: str
    correlation_id: str
    idempotency_key: str
    schema_version: str = "1.0"
