from typing import Optional, Dict, Any, List
from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime


class BaseSchema(BaseModel):
    """
    通用基类模型，全局使用别名生成驼峰/小写标准或保证 Pydantic v2 设置。
    """
    model_config = ConfigDict(
        populate_by_name=True,
        from_attributes=True,
        protected_namespaces=()
    )


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
