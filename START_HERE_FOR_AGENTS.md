# START HERE FOR AGENTS

## 0. 目标
- 这是协作 AI/开发者的唯一启动入口。
- 目标：按统一边界与门禁实现，不跑偏，不越权。

## 1. 强制阅读顺序（MUST）
1) `SKILL_IMPLEMENTATION_PROGRESS.md`（SKILL 落地进度 — **首先阅读，了解全局状态**）
2) `code/docs/runbooks/implementation-status-ledger.md`
3) `ainer_contracts.md`
4) `ainer_event_types.md`
5) `ainer_error_code.md`
6) `code/docs/architecture/stage-enum-authority.md`
7) `code/docs/architecture/service-api-contracts.md`
8) `code/docs/architecture/queue-topics-and-retry-policy.md`
9) `code/docs/runbooks/agent-implementation-playbook.md`
10) `code/docs/runbooks/ci-gate-execution-spec.md`
11) `code/docs/runbooks/e2e-handoff-test-matrix.md`
12) `code/docs/architecture/agent-data-model-guideline.md` (Agent数据模型直接落地必读基线)
13) `code/docs/runbooks/agent-direct-implementation-readiness.md`（直落地可行性与补齐清单）
14) `code/docs/architecture/agent-coding-framework-guideline.md` (Agent编码框架与代码生成模板指南)

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

## 4.5 SKILL 实现框架（AI 接力必读）
- 每个 SKILL 有独立的 Service 类，位于 `code/apps/*/app/services/skills/skill_XX_*.py`
- 每个 SKILL 有独立的 Input/Output DTO，位于 `code/shared/ainern2d_shared/schemas/skills/skill_XX.py`
- 所有 Service 继承 `BaseSkillService`，统一 `execute(input, ctx)` 入口
- Orchestrator 通过 `SkillRegistry.dispatch(skill_id, input, ctx)` 调度
- **实现某个 SKILL 后必须更新 `SKILL_IMPLEMENTATION_PROGRESS.md` 中对应行的状态**
- SKILL DAG 依赖关系见 `SKILL_IMPLEMENTATION_PROGRESS.md` 第 3 节

## 5. 验收门禁
- `alembic upgrade -> downgrade -> upgrade` 必须通过。
- E2E Blocker 用例必须 100% 通过。
- 术语扫描必须一致（run/job/stage/event/artifact）。

## 6. 交付输出
- 更新 `implementation-status-ledger.md` 状态。
- 附验证证据（迁移日志、E2E结果、关键事件链）。
