# Implementation Status Ledger（单一事实源）

## 1. 目的
- 为其他 AI agent 提供唯一的“当前已落地状态”来源，避免把目标态误认为现状。
- 任何实现前，必须先读取本文件再执行编码。

## 2. 状态定义
- `DONE`：代码与文档均已落地并通过验证。
- `IN_PROGRESS`：文档完成但代码未完，或代码完成但验收未过。
- `TODO`：尚未落地。

## 3. 当前状态快照（2026-02-26）

| 领域 | 状态 | 证据文件 | 说明 |
|---|---|---|---|
| 术语统一（run/job/stage/event/artifact） | DONE | `ainer_contracts.md`, `ainer_event_types.md`, `00.架构.md` | 全仓主词典已统一 |
| 共享模型理想态（01~20） | DONE | `code/shared/ainern2d_shared/ainer_db_models/*.py` | 57+ 模型表对象已定义 |
| Alembic init baseline | DONE | `code/apps/alembic/versions/6f66885e0588_init_baseline.py` | upgrade/downgrade/upgrade 已验证 |
| 01~20 Skill 术语声明 | DONE | `SKILL_01~20` | 20/20 命中 |
| 服务 API 细粒度契约 | DONE | `code/docs/architecture/service-api-contracts.md` | 已补齐 |
| Queue topic 与重试策略 | DONE | `code/docs/architecture/queue-topics-and-retry-policy.md` | 已补齐 |
| Stage 权威枚举与迁移 | DONE | `code/docs/architecture/stage-enum-authority.md` | 已补齐 |
| 14~20 E2E 验收矩阵 | DONE | `code/docs/runbooks/e2e-handoff-test-matrix.md` | 已扩展到 E2E-020 |
| CI 门禁执行规范 | DONE | `code/docs/runbooks/ci-gate-execution-spec.md` | 已补齐 |
| shared 基础骨架（schemas/queue/utils/telemetry/config/storage） | IN_PROGRESS | `code/docs/runbooks/agent-direct-implementation-readiness.md` | 目录已建，关键文件待补齐 |
| 服务入口骨架（studio-api/worker-hub/composer/runtime） | IN_PROGRESS | `code/docs/runbooks/agent-direct-implementation-readiness.md` | 多数主干文件仍为空 |

## 4. Agent 执行门禁
- MUST：实现前读取本 Ledger 与 `ainer_contracts.md`。
- MUST：若目标模块状态非 `DONE`，先补契约/测试矩阵再写实现。
- FORBID：绕过 `run.stage.changed` 与 `job.succeeded/job.failed` 主状态事件。

## 5. 更新规则
- 每次合并必须更新本表对应状态。
- 状态变更需要附带证据文件（代码/报告/测试输出）。
