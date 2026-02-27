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
| SKILL DTO schemas | IN_PROGRESS | `code/shared/ainern2d_shared/schemas/skills/` | 01~22 DTO 已落地；01 已补齐 `tenant_id/project_id/trace_id/correlation_id/idempotency_key/schema_version` 治理字段；21/22 及其 08/10/15/16/17 消费字段已接通 |
| SKILL Service 层 | IN_PROGRESS | `code/apps/*/app/services/skills/` | 01~22 Service 已落地；01 已完成输出契约字段对齐与 01->02 交接 E2E；02 已完成错误码域对齐（`LANG-VALIDATION-*` -> `REQ-VALIDATION-*`）；03 已补齐 `03 -> 04 -> 21 -> 07` 依赖链联调测试，并完成 API 层 `ValueError` 到结构化错误对象映射（含 `error_code/retryable/http_status/owner_module/trace_id/correlation_id`）；04 已补 continuity handoff 字段并完成 `04 -> 21` 消费联调；05 已补 REVIEW_REQUIRED 分支触发判定与覆盖测试；06 已补 `tracks/timing` 输出契约一致性（`timeline_final.tracks` 分组 + timing 回归断言）；07 已接入 SKILL_21 稳定 `entity_id` 输入并贯通 `04 -> 21 -> 07` 联调；08 已补 `asset_library_index` 真实索引检索链并完成索引优先/回退回归；09 已完成状态机命名与规格/阶段权威语义对齐（`AUDIO_FEATURES_AGGREGATING`/`MOTION_SCORING`/`STRATEGY_MAPPING`/`MICROSHOT_SPLITTING`）并补回归断言；10~22 已完成目标验收（10 API+DB 回放闭环；11~13 事件契约+发布消费闭环；14 与 22 persona 绑定字段联调；15 已完成 policy stack 入库 + policy.stack.built 审计事件 + API 回放 E2E；16 已统一 0-100/0-1 分数阈值契约并补回归测试；17 已切换为 critic report 真实评分路径并补齐晋升门禁；18 已对齐降级阶梯顺序并补旧阈值兼容；19 已补历史渲染统计依赖并完成预算回路回归；20 已统一 backend_target 字段与 PLAN-* 错误码域；21 已补 API+DB E2E 连续性锁定闭环；22 已补 API+DB E2E（lineage/version update -> 10/15/17 消费一致与回滚验证））。 |
| SKILL 注册表 | DONE | `code/apps/ainern2d-studio-api/app/services/skill_registry.py` | SkillRegistry.dispatch() 可调度 |
| BaseSkillService 基类 | DONE | `code/shared/ainern2d_shared/services/base_skill.py` | 幂等/日志/状态记录/错误包装 |
| SKILL 进度跟踪 | IN_PROGRESS | `SKILL_IMPLEMENTATION_PROGRESS.md` | 目标链路已升级为 01~22；21/22 代码化进度待继续推进 |
| DevOps（docker/nginx/scripts） | DONE | `code/docker-compose.yml`, `code/infra/`, `code/scripts/` | 完整开发环境 |
| SKILL 核心逻辑实现 | IN_PROGRESS | `code/apps/*/app/services/skills/` | 基础 20 技能已实现并接入 21/22 消费链；10~22 已完成回放/回滚/检索、persona 绑定、policy 入库、critic 阈值契约统一、实验晋升门禁、降级阶梯对齐、算力预算历史回路、DSL 编译契约统一、continuity API+DB 闭环与 persona lineage 回滚闭环，剩余技能继续推进真实执行收敛 |
| Studio 产品层 API（23~30） | IN_PROGRESS | `code/apps/ainern2d-studio-api/app/api/v1/{auth,novels,config_center,rag_console,culture_packs,tasks,assets,timesline}.py`, `code/apps/ainern2d-studio-web/src/{App.vue,router/index.ts,pages/*.vue}` | 已完成统一结构化 API 错误对象封装（HTTPException/ValidationError/ValueError/Exception）、Bearer 验签 + RBAC 中间件（viewer/editor/admin）+ project 级 ACL 强制检查（非 admin 角色）、23~30 后端 smoke（2 passed）与模块回归（skills: 136 passed, 1 skipped）；Config Center 已补 Provider Token+Capability 配置、Provider/Profile CRUD、Feature Matrix 与 Telegram 通知配置；Task Snapshot 已冻结 language+telegram settings；新增“素材绑定一致性”独立页面与 `/projects/{project_id}/asset-bindings` 聚合 API（人物/场景/道具预览 + 锁定素材编辑 + 重生成入口）；Timeline 已补 patch 历史查询与回滚重跑接口，仍需完善工业级 NLE 编辑增强与运行看板 |
| E2E 集成测试 | IN_PROGRESS | `code/apps/ainern2d-studio-api/tests/skills/test_e2e_handoff_21_22.py` | 已新增 E2E-021/022 服务级链路验证；API+DB 级自动化归档待补 |

## 4. Agent 执行门禁
- MUST：实现前读取本 Ledger 与 `ainer_contracts.md`。
- MUST：若目标模块状态非 `DONE`，先补契约/测试矩阵再写实现。
- FORBID：绕过 `run.stage.changed` 与 `job.succeeded/job.failed` 主状态事件。

## 5. 更新规则
- 每次合并必须更新本表对应状态。
- 状态变更需要附带证据文件（代码/报告/测试输出）。
