# Agent 数据模型与直接落地指南 (Agent Data Model Guideline)

## 1. 定位与目标
本文档是其他 AI Agent 在进行**底层逻辑编写、API 开发、Worker 消费者开发**时的**唯一数据模型落地依据**。
任何 Agent 在进行实际的数据库读写、接口对象封装前，**必须优先查阅本指南**，严禁凭空伪造（Hallucinate）数据库表结构或 Pydantic 模型。

## 2. Single Source of Truth（唯一事实来源）
系统的理想数据模型（58+表）**已经完全代码化**。任何对于表的列名、类型、外键约束、默认值等细节的探索，**直接去代码库查看，不要依赖纯文本 markdown 的推断**：
- **SQLAlchemy ORM 模型统一定义在**：`code/shared/ainern2d_shared/ainer_db_models/`
  - 核心基类：`base_model.py`
  - 身份与权限模型：`auth_models.py`
  - 统一流水线与任务模型：`pipeline_models.py`
  - 内容与产物模型：`content_models.py`
  - 知识提炼模型：`knowledge_models.py`
  - 核心 RAG 模型：`rag_models.py`
  - 治理与路由模型：`governance_models.py`, `provider_models.py`
  - 预览与 21/22 绑定模型：`preview_models.py`
- **Alembic 初始数据库定义在**：`code/apps/alembic/versions/6f66885e0588_init_baseline.py`
- **共享 Pydantic DTO (Schemas) 目录在**：`code/shared/ainern2d_shared/schemas/`
  - 注意：当前该目录为“待补齐骨架”，必须先按 `code/docs/runbooks/agent-direct-implementation-readiness.md` 的 P0 清单补齐后，才允许批量业务实现。

## 3. 核心边界与强制约束 (Strict Boundaries)

### 3.1 继承与共享字段强制要求
所有核心业务表（继承自 `BaseModel`）**已经自带**了以下共享标准列：
`tenant_id`, `project_id`, `trace_id`, `correlation_id`, `idempotency_key`, `error_code`, `version`, `created_at`, `updated_at`, `deleted_at`, `created_by`, `updated_by`。
- **Agent 落地要求**：在编写创建逻辑（Insert/Create）时，**必须从 API Context 或 Event Payload 中提取并传递** `tenant_id`, `project_id`, `trace_id`，禁止将其硬编码为 Null 或留空。
- **Agent 查询要求**：所有的业务查询必须默认过滤软删除，并优先带上业务去重或范围查找（如 `filter(Model.deleted_at.is_(None), Model.tenant_id == tenant_id)`）。

### 3.2 严禁私自绕过 Shared Models
- **禁止行为**：Agent 在独立的 FastAPI 微服务（如 `orchestrator` 或 `worker-hub`）中，自己写一个私有的 SQL 原生执行语句或私有 ORM Class。
- **正确要求**：必须从 `ainern2d_shared.ainer_db_models` 导入模型并使用。如果当前微服务需要新增私有表，需评估是否属于系统级概念；若属于，**必须**加到 `shared` 包中并统一用 alembic 迁移。

### 3.3 数据库迁移 (Alembic) 的铁律
- 初期基线 `6f66885e0588_init_baseline.py` **禁止篡改**。
- 如果在实现新 Skill(14~22) 或增强 RAG 逻辑时，需要增加字段或新表，**必须生成新的 alembic revision**。所有的 downgrade 脚本必须经过测试可以无损回滚新建的列/表。

## 4. API 与框架对接落地细节规范
为了避免偏离现有框架，遵循以下代码落地细节：
1. **Repository Pattern (仓储模式)**：建议将数据库访问封装在 `repositories` 目录中，API/Service 层禁止直接写复杂的 `session.query(...)` 联表。
2. **DTO 转换隔离**：Controller (API Router) 返回的永远是 `code/shared/ainern2d_shared/schemas/` 下定义的 Pydantic Schema，严禁直接 `return db_model_instance` 给前端或消息队列。如果 Pydantic 模型不存在，则优先在 `shared` 下创建。
3. **事务边界 (Transaction scope)**：一个明确的 API 请求或消费事件，对应一个 DB Session 事务。保证强一致性。对于长耗时的外部调用（如 LLM、Worker），**绝对不允许**在这个过程中保持 DB 事务打开。

## 5. Agent 落地三步曲 (Checklist for Code Generation)
当其他 Agent 被要求“实现 API / 写数据库落库逻辑”时：
1. `view_file` 查看 `code/shared/ainern2d_shared/ainer_db_models/` 中对应的表结构定义。
2. 确认 `code/shared/ainern2d_shared/schemas/` 中是否存在对应的 Event 或 Request Schema；若不存在，先在 shared 中补齐再开发服务代码。
3. 生成的代码中强引用 `ainern2d_shared` 的模块结构，确保时区处理统一使用 `ainern2d_shared.utils.time` 等基建库。
