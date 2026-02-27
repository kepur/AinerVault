# Implementation Status Ledger（单一事实源）

## 1. 目的
- 为其他 AI agent 提供唯一的“当前已落地状态”来源，避免把目标态误认为现状。
- 任何实现前，必须先读取本文件再执行编码。

## 2. 状态定义
- `DONE`：代码与文档均已落地并通过验证。
- `IN_PROGRESS`：文档完成但代码未完，或代码完成但验收未过。
- `TODO`：尚未落地。

## 3. 当前状态快照（2026-02-27 更新）

| 领域 | 状态 | 证据文件 | 说明 |
|---|---|---|---|
| 术语统一（run/job/stage/event/artifact） | DONE | `ainer_contracts.md`, `ainer_event_types.md`, `00.架构.md` | 全仓主词典已统一 |
| 共享模型理想态（01~22） | IN_PROGRESS | `code/shared/ainern2d_shared/ainer_db_models/*.py` | 基础链路模型已定义；21/22 迁移与服务消费接线已落地，API级 E2E 与治理闭环待补 |
| Alembic init baseline | DONE | `code/apps/alembic/versions/6f66885e0588_init_baseline.py` | upgrade/downgrade/upgrade 已验证 |
| 01~22 Skill 术语声明 | DONE | `SKILL_01~22` | 22/22 需求文档已存在 |
| 服务 API 细粒度契约 | DONE | `code/docs/architecture/service-api-contracts.md` | 已补齐 |
| Queue topic 与重试策略 | DONE | `code/docs/architecture/queue-topics-and-retry-policy.md` | 已补齐 |
| Stage 权威枚举与迁移 | DONE | `code/docs/architecture/stage-enum-authority.md` | 已补齐 |
| 14~22 E2E 验收矩阵 | IN_PROGRESS | `code/docs/runbooks/e2e-handoff-test-matrix.md` | 已补到 E2E-022；自动化执行与结果归档待补 |
| CI 门禁执行规范 | DONE | `code/docs/runbooks/ci-gate-execution-spec.md` | 已补齐 |
| 前置开工门禁（可执行） | DONE | `code/scripts/validate_preimplementation_readiness.py`, `progress/PREIMPLEMENTATION_READINESS_REPORT.md` | 严格模式通过：PASS=6/FAIL=0/WARN=0 |
| shared 基础骨架 | DONE | `code/shared/ainern2d_shared/` | schemas(8) + queue(3) + utils(3) + telemetry(3) + config(2) + storage(2) + db(4) + services(2) — 全部有实现 |
| 服务入口骨架 | DONE | `code/apps/*/app/main.py` | 4 服务 main.py + 所有路由注册 + 所有 __init__.py |
| 业务模块实现 | DONE | `code/apps/*/app/modules/` | 66 个原空文件已全部实现，16 个 __init__.py |
| SKILL DTO schemas | IN_PROGRESS | `code/shared/ainern2d_shared/schemas/skills/` | 01~22 DTO 已落地；21/22 及其 08/10/15/16/17 消费字段已接通，API级 E2E 待补 |
| SKILL Service 层 | IN_PROGRESS | `code/apps/*/app/services/skills/` | 01~22 Service 已落地；10~13 已完成目标验收（10 API+DB 回放闭环；11~13 事件契约+发布消费闭环，含 RabbitMQ 联调与重复投递去重保护）；21/22 消费接线与服务级 E2E 已补，剩余链路继续收敛 |
| SKILL 注册表 | DONE | `code/apps/ainern2d-studio-api/app/services/skill_registry.py` | SkillRegistry.dispatch() 可调度 |
| BaseSkillService 基类 | DONE | `code/shared/ainern2d_shared/services/base_skill.py` | 幂等/日志/状态记录/错误包装 |
| SKILL 进度跟踪 | IN_PROGRESS | `SKILL_IMPLEMENTATION_PROGRESS.md` | 目标链路已升级为 01~22；21/22 代码化进度待继续推进 |
| DevOps（docker/nginx/scripts） | DONE | `code/docker-compose.yml`, `code/infra/`, `code/scripts/` | 完整开发环境 |
| SKILL 核心逻辑实现 | IN_PROGRESS | `code/apps/*/app/services/skills/` | 基础 20 技能已实现并接入 21/22 消费链；10~13 已完成回放/回滚/检索基线闭环，剩余技能继续推进真实执行收敛 |
| E2E 集成测试 | IN_PROGRESS | `code/apps/ainern2d-studio-api/tests/skills/test_e2e_handoff_21_22.py` | 已新增 E2E-021/022 服务级链路验证；API+DB 级自动化归档待补 |

## 4. Agent 执行门禁
- MUST：实现前读取本 Ledger 与 `ainer_contracts.md`。
- MUST：若目标模块状态非 `DONE`，先补契约/测试矩阵再写实现。
- FORBID：绕过 `run.stage.changed` 与 `job.succeeded/job.failed` 主状态事件。

## 5. 更新规则
- 每次合并必须更新本表对应状态。
- 状态变更需要附带证据文件（代码/报告/测试输出）。
