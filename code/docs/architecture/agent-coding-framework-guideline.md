# Agent 编码框架与代码生成模板指南 (Agent Coding Framework Guideline)

## 1. 定位与目标
当 AI Agent 接收到“实现一个 API”、“增加一个 Worker 消费者”、“编写某个业务逻辑”的任务时，必须遵循本指南的**代码结构与实现模板**。
这是确保所有生成的 Python 代码能够与现有 AinerHub 系统（FastAPI + RabbitMQ + SQLAlchemy）完美契合，“不凭空创造框架、不偏离现有基建”的根本保证。

## 2. 目录结构与分层标准 (Layering Standards)
Agent 生成的代码必须放入其所属微服务（如 `apps/ainern2d-studio-api`）的特定目录中，严格遵循以下代码分层：

- **`app/api/v1/` (Controller层)**：只负责 HTTP 路由、校验 Request 参数 Schema、提取 Headers (tenant_id/trace_id)、调用 Service 层、格式化 Response。**绝对禁止在此处写 SQL 会话或复杂运算。**
- **`app/services/` (Service层)**：业务逻辑的编排器。负责组合各种 Repository 或者调用外部大模型。
- **`app/db/repositories/` (Repository层)**：所有的数据库读写操作必须封装在这里。入参是 Pydantic/离散参数，出参是 ORM Model 或者聚合结果。
- **`app/consumers/` (Queue层)**：所有的 RabbitMQ/Redis 消费逻辑必须写在这里，通过调用 Service 层来处理业务。

## 3. 代码生成模板 (Code Templates)

### 3.1 FastAPI Router 模板
当你被要求写一个 API 时，必须遵循这种模式：

```python
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session
from loguru import logger

from ainern2d_shared.schemas.task import TaskCreateRequest, TaskResponse
from ainern2d_shared.db.session import get_db
from app.services.task_service import TaskService

router = APIRouter()

@router.post("/tasks", response_model=TaskResponse, status_code=202)
def create_task(
    request: TaskCreateRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-Id"),
    x_project_id: str = Header(..., alias="X-Project-Id"),
    x_trace_id: str = Header(..., alias="X-Trace-Id"),
    x_idempotency_key: str = Header(..., alias="X-Idempotency-Key"),
    db: Session = Depends(get_db)
):
    """
    提交新任务的 API。所有系统请求头是跨服务追踪的必填项。
    """
    logger.info(f"Received create_task request. TraceID: {x_trace_id}")
    
    # 将 Header 组装入 Request Context，或者直接传给 Service
    service = TaskService(db=db)
    
    try:
        # 业务层必须抛出符合 ainer_error_code 的自定义异常
        result = service.create_job(
            tenant_id=x_tenant_id,
            project_id=x_project_id,
            trace_id=x_trace_id,
            idempotency_key=x_idempotency_key,
            payload=request
        )
        return result
    except ValueError as e:
        # Agent 注意：这里应转换为统一的 Ainer 系统错误
        logger.error(f"Validation failed: {str(e)}")
        raise HTTPException(status_code=400, detail={"error_code": "INVALID_PARAMS", "message": str(e)})
```

### 3.2 Repository 落库模板
在 Repository 中，严格使用 `BaseModel` 中自带的标准字段。

```python
from sqlalchemy.orm import Session
from ainern2d_shared.ainer_db_models.pipeline_models import Job

class JobRepository:
    def __init__(self, db: Session):
        self.db = db
        
    def create_job(self, tenant_id: str, project_id: str, trace_id: str, idempotency_key: str, status: str) -> Job:
        """
        严禁漏掉 shared 基线的五个核心字段。
        """
        new_job = Job(
            tenant_id=tenant_id,
            project_id=project_id,
            trace_id=trace_id,
            idempotency_key=idempotency_key,
            status=status,
            error_code=None
        )
        self.db.add(new_job)
        self.db.commit()
        self.db.refresh(new_job)
        return new_job
```

### 3.3 Event / Queue 生产与消费模板
如果涉及模块之间的解耦，严禁自己写 HTTP 轮询。

**生产 (Producer):**
```python
from ainern2d_shared.queue.rabbitmq import RabbitMQPublisher
from ainern2d_shared.queue.topics import SYSTEM_TOPICS
from ainern2d_shared.schemas.events import EventEnvelope

def publish_task_event(publisher: RabbitMQPublisher, event: EventEnvelope):
    # 强制路由到文档 queue-topics-and-retry-policy 指定的 topic
    publisher.publish(
        topic=SYSTEM_TOPICS.JOB_DISPATCH, 
        message=event.model_dump_json()
    )
```

## 4. 依赖库与工具集基线
AI Agent 在文件开头写 `import` 时，必须优先使用系统中已存在的共享包，不要自己 pip install 重复的第三方库。
- **日志**：禁止用 `print` 或原生的 `logging`，**统一使用 `loguru` 或预配置的 `ainern2d_shared.telemetry.logging`**。
- **重试逻辑**：不要自己写 `time.sleep` 的 `while` 循环，统一使用 `ainern2d_shared.utils.retry.retry_with_backoff` 装饰器。
- **时间获取**：不要直接 `datetime.now()`，统一使用 `ainern2d_shared.utils.time.utcnow()` 确保时区带 `tzinfo` 且序列化安全。

## 5. Agent 代码生成审查 Checklist
在最终执行写文件 (`write_to_file`/`replace_file_content`) 前，Agent 必须进行自我审查：
1. [ ] 代码是否分层放入了 Controller / Service / Repository？
2. [ ] 是否强行引入了未在需求中的新 Python 依赖？
3. [ ] FastAPI 路由参数中是否完整的承接了 `tenant_id`, `project_id`, `trace_id`？
4. [ ] 日志或报错中，抛出的是否满足 `ainer_error_code.md` 规范的字典而不是裸字符串？
