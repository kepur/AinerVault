# Round 2 实施清单（共享标准映射 + Alembic 拆解）

## 1. 交付物
- Agent启动入口：`START_HERE_FOR_AGENTS.md`
- 字段映射清单：`code/docs/architecture/shared-field-mapping-matrix.md`
- Stage权威：`code/docs/architecture/stage-enum-authority.md`
- 服务API契约：`code/docs/architecture/service-api-contracts.md`
- 队列与重试：`code/docs/architecture/queue-topics-and-retry-policy.md`
- Studio映射：`code/docs/architecture/studio-web-api-mapping.md`
- 迁移拆解：`code/docs/runbooks/alembic-migration-plan-p0-p2.md`
- 直落地就绪规范：`code/docs/runbooks/agent-direct-implementation-readiness.md`
- 本清单：`code/docs/runbooks/round2-implementation-checklist.md`
- 实施状态账本：`code/docs/runbooks/implementation-status-ledger.md`
- E2E交接验收：`code/docs/runbooks/e2e-handoff-test-matrix.md`
- Skill线上部署：`code/docs/runbooks/skill-online-deployment.md`
- P1治理计划：`code/docs/runbooks/p1-ops-governance-plan.md`
- 01~22接入说明：`README_21_22_INTEGRATION_GUIDE.md`
- CI门禁执行：`code/docs/runbooks/ci-gate-execution-spec.md`

## 2. 工作包（按优先级）

### P0（本周必须完成）
- [x] 完成 shared 核心表标准字段新增（novels/chapters/execution_requests/render_runs/jobs/artifacts）
- [x] 完成索引新增与 `jobs` 幂等兼容
- [ ] 完成回填脚本与回填报告（新项目可选）
- [ ] 补齐 shared 基础骨架空文件（schemas/queue/utils/telemetry/config/storage）
- [ ] 补齐工程基础文件（`code/apps/pyproject.toml`、`code/shared/pyproject.toml`、`code/scripts/*.sh`）
- [ ] 完成网关写入路径：所有新请求带 `tenant_id/project_id/trace_id/idempotency_key`
- [ ] 完成编排与 worker 回写路径：失败必带 `error_code`
- [x] 完成 Alembic 单一 init baseline（含回滚/重升验证）

### P1（下一阶段）
- [x] 上线 auth 多租户模型（users/tenants/projects/RBAC）
- [x] 上线 observer 错误与成本聚合表
- [x] 上线 RAG 多 embedding 治理字段
- [x] 上线 proposal 审核流程与版本推广门禁
- [x] 上线 RAG 评测与自动回滚建议
- [x] 接入 SKILL_14 Persona 到 SKILL_10（模型与文档约束层）
- [x] 接入 SKILL_15/19 到 SKILL_09 渲染规划前（模型与文档约束层）
- [x] 接入 SKILL_20 到执行器前编译层（模型与文档约束层）

### P2（收敛）
- [ ] 约束收紧（NOT NULL + UNIQUE）
- [ ] 清理 legacy 字段与查询路径
- [ ] 完成全链路压测与审计巡检
- [x] 接入 SKILL_16/18 质量门与降级闭环（模型与文档约束层）
- [x] 接入 SKILL_17 A/B 实验飞轮（模型与文档约束层）

## 3. 服务映射任务
- Orchestrator：
  - [ ] 工作流私有表继承标准字段
  - [ ] `run/stage/retry` 事件落 `trace_id` 与 `error_code`
- Worker Hub / Worker-*：
  - [ ] 执行日志继承标准字段
  - [ ] `job.claimed/job.failed/job.succeeded` 事件契约对齐
- Composer：
  - [ ] 合成批次、导出记录继承标准字段
- Observer：
  - [ ] 聚合指标按 `tenant_id/project_id/error_code` 维度可查询

## 4. 验收标准
- [ ] 业务闭环：登录 -> 提交任务 -> 执行 -> 合成 -> 回流可追踪
- [ ] 数据闭环：`run_id/job_id/artifact_id` 可用 `trace_id` 串联
- [ ] 治理闭环：错误码覆盖率 > 95%，关键表索引命中符合预期

## 4.1 当前验证结论（2026-02-26）
- [x] 模型闭环：已通过（见 `code/docs/runbooks/ideal-model-e2e-validation-report.md`）
- [x] 迁移闭环：已通过（`upgrade -> downgrade -> upgrade`）
- [x] 术语闭环：已通过（SKILL_01~22 均有术语对齐声明）
- [ ] 服务实现闭环：待业务服务代码按契约接线后复验

## 4.2 直落地可行性结论（2026-02-26）
- [x] “文档 + 模型”可支撑数据库与事件语义设计。
- [ ] 尚未达到“其他 AI agent 可直接端到端编码”的完成态。
- [ ] 阻塞项：`shared` 包关键基础模块与 `apps` 关键入口存在大量空文件。
- [ ] 执行基线：先按 `agent-direct-implementation-readiness.md` 补齐 P0 骨架，再进入服务接线。

## 5. 风险与管控
- 风险：历史数据缺失 `tenant_id/project_id`。
  - 方案：先默认租户回填，再逐批纠偏。
- 风险：大表加索引造成锁等待。
  - 方案：低峰执行 + 在线索引 + 超时中止。
- 风险：多服务版本错配。
  - 方案：双读双写窗口 + 契约版本门禁。

## 6. 强制执行顺序（给 AI Agent）
1) 先读 `implementation-status-ledger.md` 确认状态。
2) 按 `service-api-contracts.md` + `queue-topics-and-retry-policy.md` 实现接口与事件。
3) 严格依赖 `stage-enum-authority.md`，不得自定义 stage。
4) 按 `ci-gate-execution-spec.md` 通过门禁后方可合并。
