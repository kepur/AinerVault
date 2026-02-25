# CI Gate Execution Spec

## 1. 阻断目标
- 保证契约、事件、术语、E2E 用例在合并前通过，避免 AI 代理实现偏航。

## 2. Gate 列表（按阻断级）

### Gate-1 契约字段完整性（Blocker）
- 校验 MUST 字段：`tenant_id/project_id/trace_id/correlation_id/idempotency_key/schema_version`。
- 失败即阻断发布。

### Gate-2 事件注册一致性（Blocker）
- 新事件必须在 `ainer_event_types.md` 注册。
- 运行态事件仅允许 `run.*`/`job.*`（`worker.*.completed` 为明细）。

### Gate-3 术语一致性（High）
- 扫描关键文档是否统一 `run/job/stage/event/artifact`。
- 若出现主线 `step.*`，判为失败（deprecated 区除外）。

### Gate-4 E2E Blocker 套件（Blocker）
- `e2e-handoff-test-matrix` 中 Blocker 用例必须 100% 通过。

## 3. 本地执行顺序
1) 模型/文档静态检查
2) Alembic upgrade 验证
3) 术语扫描
4) E2E Blocker 回放

## 4. 失败处理
- Blocker 失败：禁止合并。
- High 失败：允许修复后重跑，不允许带病发布。
