# Agent 直落地实现就绪规范（2026-02-27）

## 1. 目标
- 给 AI agent 提供一个“是否可以直接开始编码”的统一门禁。
- 把业务流程前提、模型前提、测试前提变成可执行证据，避免只看口头结论。

## 2. 当前就绪结论（2026-02-27）
- **总体结论：`GO`（可开始落地编码）**
- 依据：`progress/PREIMPLEMENTATION_READINESS_REPORT.md`
  - `PASS=6 FAIL=0 WARN=0`
  - 覆盖项：规格文件完整性、`SKILL_01~22` 存在性、框架严格校验、skills 测试、`21/22` E2E 服务链、真实数据库持久化验证
- 当前真实状态：
  - `SKILL_01~20`：Service/DTO/调度框架已在位，仍需按矩阵补完 API/闭环级 E2E
  - `SKILL_21~22`：DTO/Service/Registry/Dispatcher/DAG/消费接线已落地，服务级 E2E 已通过

## 3. 强制边界（不可突破）
- 运行主对象只能用：`run/job/stage/event/artifact`
- 仅 `orchestrator` 可推进 `run.stage.changed`
- `worker.*.completed` 只能作执行明细，不可替代 `job.succeeded/job.failed`
- 所有写链路必须带：`tenant_id/project_id/trace_id/correlation_id/idempotency_key`
- 失败链路必须带：`error_code/retryable/owner_module/trace_id`

## 4. 框架与目录规范
- Web/API：FastAPI（按服务拆分路由与模块）
- ORM：SQLAlchemy 2.x Declarative（统一复用 shared models）
- 迁移：Alembic（只增 revision，不回改 baseline）
- DTO：Pydantic（统一 `code/shared/ainern2d_shared/schemas/`）
- 消息：RabbitMQ Topic（以 `queue-topics-and-retry-policy.md` 为准）
- 存储：PostgreSQL + MinIO/S3（产物走对象存储，DB 存元数据）

## 5. 前置门禁（提交前必须通过）
1. 运行统一门禁脚本  
   `python3 code/scripts/validate_preimplementation_readiness.py --strict`
2. 若需要真实库强校验，设置 `DATABASE_URL` 后再执行  
   `DATABASE_URL=postgresql+psycopg2://ainer:ainer_dev_2024@localhost:5432/ainer_dev python3 code/scripts/validate_preimplementation_readiness.py --strict`
3. 报告文件必须刷新并可追溯  
   `progress/PREIMPLEMENTATION_READINESS_REPORT.md`

## 6. No-Go 条件
- 门禁结果出现任一 `FAIL`
- 严格模式下出现任一 `WARN`
- 未注册事件类型或错误码（违反 `ainer_event_types.md` / `ainer_error_code.md`）
- 绕过 orchestrator 直接改写 run 终态

## 7. AI Agent 固定执行顺序
1. 先过门禁并落报告
2. 读取目标 `SKILL_XX_*.md` 与契约文档
3. 按 `DTO -> Service -> 调度 -> 测试 -> 进度回写` 实施
4. 更新 `progress/skill_delivery_status.yaml` 与 `implementation-status-ledger.md`
