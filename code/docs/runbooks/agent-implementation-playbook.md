# Agent Implementation Playbook（一页纸）

## 1. 目标
- 让任意 AI agent 按固定顺序落地实现，避免边界漂移、状态机冲突、事件语义错配。

## 2. 开始前（必须阅读）
1) `code/docs/runbooks/implementation-status-ledger.md`
2) `ainer_contracts.md`
3) `ainer_event_types.md`
4) `code/docs/architecture/stage-enum-authority.md`
5) `code/docs/architecture/service-api-contracts.md`
6) `code/docs/architecture/queue-topics-and-retry-policy.md`

## 3. 实施顺序（固定）
1) **模型层**：先实现/校验数据库模型与 Alembic（禁止先写业务逻辑）。
2) **编排层**：实现 `run.stage.changed` 与 `job.*` 主状态链。
3) **执行层**：接 worker-hub 与 worker 明细事件（仅明细，不改主状态）。
4) **合成层**：接 composer 发布 `artifact.published`。
5) **观测层**：接 observer 告警与审计。
6) **增强层**：按 14→15→19→20→16→18→13→17 顺序接入。

## 4. 绝对约束
- MUST：主运行对象仅 `run/job/stage/event/artifact`。
- MUST：失败必须带 `error_code + retryable + trace_id`。
- MUST：所有写接口带 `idempotency_key`。
- FORBID：绕过 orchestrator 写 run 终态。
- FORBID：新增 `step.*` 运行态事件。

## 5. 验收门禁（最小）
- 契约门禁通过（字段、事件注册、术语一致）。
- Alembic `upgrade -> downgrade -> upgrade` 通过。
- E2E Blocker 用例 100% 通过（见 `e2e-handoff-test-matrix.md`）。

## 6. 交付标准
- 更新实现状态：`implementation-status-ledger.md`
- 提交验证证据：迁移日志、E2E结果、关键事件链截图/日志
- 未满足门禁：一律标记 No-Go
