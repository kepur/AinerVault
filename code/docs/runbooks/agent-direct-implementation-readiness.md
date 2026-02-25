# Agent 直落地实现就绪规范（2026-02-26）

## 1. 目标
- 给其他 AI agent 一个“看文档 + 看模型即可直接编码”的硬约束入口。
- 明确当前可落地范围、必须先补的骨架、以及禁止跑偏边界。

## 2. 当前就绪结论（必须先看）
- **数据库模型层：已就绪**  
  - `code/shared/ainern2d_shared/ainer_db_models/` 已定义 `57` 个共享模型，统一继承 `StandardColumnsMixin`。
  - `code/apps/alembic/versions/6f66885e0588_init_baseline.py` 可直接落库。
- **服务实现层：未就绪（必须补骨架）**  
  - 当前 `code/` 下 Python 文件共 `101` 个，其中空文件 `87` 个。
  - 关键共享基础代码为空：`schemas/queue/utils/telemetry/config/storage`。
  - 关键服务入口为空：`studio-api`、`worker-hub`、`composer`、`worker-runtime` 主干文件。
- **结论**  
  - 现在达到“模型可落库 + 文档可指导”状态。  
  - 尚未达到“其他 AI agent 无补充即可直接完成端到端编码”状态。

## 3. 强制边界（不可突破）
- 运行主对象只能用：`run/job/stage/event/artifact`。
- 仅 `orchestrator` 可推进 `run.stage.changed`。
- `worker.*.completed` 只能作执行明细，不可替代 `job.succeeded/job.failed`。
- 所有写链路必须带：`tenant_id/project_id/trace_id/correlation_id/idempotency_key`。
- 失败链路必须带：`error_code/retryable/owner_module/trace_id`。

## 4. 框架与目录落地规范
- Web/API：FastAPI（按服务拆分路由与模块）。
- ORM：SQLAlchemy 2.x Declarative（统一复用 shared models）。
- 迁移：Alembic（只增 revision，不修改 baseline）。
- DTO：Pydantic（统一放在 `code/shared/ainern2d_shared/schemas/`）。
- 消息：RabbitMQ Topic（主题以 `queue-topics-and-retry-policy.md` 为准）。
- 存储：PostgreSQL + MinIO/S3（产物走对象存储，DB 存元数据）。

## 5. P0 必补清单（补齐后才允许大规模实现）
- `code/shared/ainern2d_shared/schemas/task.py`
- `code/shared/ainern2d_shared/schemas/timeline.py`
- `code/shared/ainern2d_shared/schemas/artifact.py`
- `code/shared/ainern2d_shared/schemas/events.py`
- `code/shared/ainern2d_shared/queue/topics.py`
- `code/shared/ainern2d_shared/queue/message_contracts.py`
- `code/shared/ainern2d_shared/queue/rabbitmq.py`
- `code/shared/ainern2d_shared/utils/time.py`
- `code/shared/ainern2d_shared/utils/idempotency.py`
- `code/shared/ainern2d_shared/utils/retry.py`
- `code/shared/ainern2d_shared/telemetry/logging.py`
- `code/shared/ainern2d_shared/telemetry/metrics.py`
- `code/shared/ainern2d_shared/telemetry/tracing.py`
- `code/shared/ainern2d_shared/config/setting.py`
- `code/shared/ainern2d_shared/config/enums.py`
- `code/shared/ainern2d_shared/storage/s3.py`
- `code/shared/ainern2d_shared/storage/minio.py`
- `code/apps/pyproject.toml`
- `code/shared/pyproject.toml`
- `code/scripts/dev-up.sh`, `dev-down.sh`, `migrate.sh`, `seed_rag.sh`, `init_storage.sh`

## 6. 模型与契约对齐细则（防跑偏）
- `schema_version` 是事件/DTO 权威字段；数据库中的结构版本使用 `version`，两者禁止混用语义。
- 运行态时间字段当前存在字符串列（如 `started_at/finished_at/occurred_at`）；新代码必须统一输出 `ISO-8601 UTC`。
- 新增事件类型必须同步登记 `ainer_event_types.md`，未登记视为违规实现。
- 新增错误码必须同步登记 `ainer_error_code.md`，失败事件必须包含错误对象。

## 7. AI Agent 固定实施顺序
1. 先补 `shared` 空骨架（DTO、队列、时间/幂等/重试、遥测、配置、存储）。
2. 再补服务入口（studio-api -> orchestrator -> worker-hub -> composer -> observer）。
3. 最后接增强链路（14~20）与治理闭环。

## 8. 最小验收门禁（提交前必须通过）
- Alembic：`upgrade -> downgrade -> upgrade` 全通过。
- 契约：MUST 字段与事件注册检查通过。
- 术语：`run/job/stage/event/artifact` 一致性检查通过。
- E2E：`e2e-handoff-test-matrix.md` 的 Blocker 用例 100% 通过。

## 9. No-Go 条件
- 任一共享骨架仍为空文件。
- 出现未注册事件类型或未注册错误码。
- 绕过 orchestrator 直接改写 run 终态。
- Blocker 门禁未通过。
