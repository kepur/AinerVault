# START HERE FOR AGENTS

## 0. 目标
- 这是协作 AI/开发者的唯一启动入口。
- 目标：按统一边界与门禁实现，不跑偏，不越权。

## 1. 强制阅读顺序（MUST）
1) `code/docs/runbooks/implementation-status-ledger.md`
2) `ainer_contracts.md`
3) `ainer_event_types.md`
4) `ainer_error_code.md`
5) `code/docs/architecture/stage-enum-authority.md`
6) `code/docs/architecture/service-api-contracts.md`
7) `code/docs/architecture/queue-topics-and-retry-policy.md`
8) `code/docs/runbooks/agent-implementation-playbook.md`
9) `code/docs/runbooks/ci-gate-execution-spec.md`
10) `code/docs/runbooks/e2e-handoff-test-matrix.md`

## 2. 核心约束（必须遵守）
- 主运行对象：`run/job/stage/event/artifact`。
- 主状态事件：`job.succeeded/job.failed`；`worker.*.completed` 仅执行明细。
- 仅 Orchestrator 可发布 `run.stage.changed`。
- 所有写链路必须带：`tenant_id/project_id/trace_id/correlation_id/idempotency_key/schema_version`。
- 失败必须带：`error_code/retryable/owner_module/trace_id`。

## 3. 禁止项（FORBID）
- 禁止自定义与 stage 权威冲突的新 stage。
- 禁止绕过 orchestrator 直接写 run 终态。
- 禁止新增 `step.*` 作为运行态主事件。
- 禁止未过 CI/E2E Blocker 门禁直接合并。

## 4. 实施顺序（固定）
1) 模型与迁移
2) 编排状态机
3) 执行链路（worker-hub/worker）
4) 合成发布（composer）
5) 观测治理（observer）
6) 增强层（14~20）

## 5. 验收门禁
- `alembic upgrade -> downgrade -> upgrade` 必须通过。
- E2E Blocker 用例必须 100% 通过。
- 术语扫描必须一致（run/job/stage/event/artifact）。

## 6. 交付输出
- 更新 `implementation-status-ledger.md` 状态。
- 附验证证据（迁移日志、E2E结果、关键事件链）。
