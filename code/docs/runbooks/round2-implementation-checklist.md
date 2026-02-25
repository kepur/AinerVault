# Round 2 实施清单（共享标准映射 + Alembic 拆解）

## 1. 交付物
- 字段映射清单：`code/docs/architecture/shared-field-mapping-matrix.md`
- 迁移拆解：`code/docs/runbooks/alembic-migration-plan-p0-p2.md`
- 本清单：`code/docs/runbooks/round2-implementation-checklist.md`
- E2E交接验收：`code/docs/runbooks/e2e-handoff-test-matrix.md`
- Skill线上部署：`code/docs/runbooks/skill-online-deployment.md`
- P1治理计划：`code/docs/runbooks/p1-ops-governance-plan.md`
- 14~20接入说明：`README_14_20_INTEGRATION_GUIDE.md`

## 2. 工作包（按优先级）

### P0（本周必须完成）
- [ ] 完成 shared 核心表标准字段新增（novels/chapters/execution_requests/render_runs/jobs/artifacts）
- [ ] 完成索引新增与 `jobs` 幂等兼容
- [ ] 完成回填脚本与回填报告
- [ ] 完成网关写入路径：所有新请求带 `tenant_id/project_id/trace_id/idempotency_key`
- [ ] 完成编排与 worker 回写路径：失败必带 `error_code`

### P1（下一阶段）
- [ ] 上线 auth 多租户模型（users/tenants/projects/RBAC）
- [ ] 上线 observer 错误与成本聚合表
- [ ] 上线 RAG 多 embedding 治理字段
- [ ] 上线 proposal 审核流程与版本推广门禁
- [ ] 上线 RAG 评测与自动回滚建议
- [ ] 接入 SKILL_14 Persona 到 SKILL_10
- [ ] 接入 SKILL_15/19 到 SKILL_09 渲染规划前
- [ ] 接入 SKILL_20 到执行器前编译层

### P2（收敛）
- [ ] 约束收紧（NOT NULL + UNIQUE）
- [ ] 清理 legacy 字段与查询路径
- [ ] 完成全链路压测与审计巡检
- [ ] 接入 SKILL_16/18 质量门与降级闭环
- [ ] 接入 SKILL_17 A/B 实验飞轮

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

## 5. 风险与管控
- 风险：历史数据缺失 `tenant_id/project_id`。
  - 方案：先默认租户回填，再逐批纠偏。
- 风险：大表加索引造成锁等待。
  - 方案：低峰执行 + 在线索引 + 超时中止。
- 风险：多服务版本错配。
  - 方案：双读双写窗口 + 契约版本门禁。
