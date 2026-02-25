# Alembic 迁移拆解（P0/P1/P2）

## 1. 迁移原则
- 先“加列与索引”，后“回填”，最后“约束收紧”。
- 所有新增默认可空，回填完成后再改 `NOT NULL`。
- 大表索引优先在线创建（避免长锁）。

## 2. 版本命名建议
- `r2_p0_001_add_shared_standard_columns`
- `r2_p0_002_add_trace_and_idempotency_indexes`
- `r2_p0_003_backfill_project_tenant_scope`
- `r2_p1_001_add_auth_tenant_project_tables`
- `r2_p1_002_add_observer_error_dimensions`
- `r2_p1_003_add_rag_multimodel_governance_columns`
- `r2_p2_001_enforce_not_null_and_unique_constraints`
- `r2_p2_002_cleanup_legacy_columns_and_views`

## 3. P0（闭环可运行）

### P0-1 加标准列（shared核心表）
目标表：
- `novels`
- `chapters`
- `execution_requests`
- `render_runs`
- `jobs`
- `artifacts`

新增列：
- `tenant_id`, `project_id`, `trace_id`, `correlation_id`, `idempotency_key`, `error_code`, `version`, `deleted_at`, `created_by`, `updated_by`
- 缺失 `updated_at` 的表补齐 `updated_at`

### P0-2 加索引与兼容约束
- 索引：`(tenant_id, project_id, created_at)`、`trace_id`、`correlation_id`
- `jobs` 兼容：保留 `dedupe_key`，新增 `idempotency_key`

### P0-3 回填
回填来源：
- `tenant_id/project_id`：按项目映射表或默认租户策略回填
- `trace_id/correlation_id`：历史数据回填可置空或生成 `legacy_*`
- `version`：默认 `v1`

验收：
- 所有新写入记录均带标准字段
- `run/job/artifact` 可按 `tenant_id+project_id+trace_id` 串联

## 4. P1（可运营可治理）

### P1-1 权限与多租户实体
新增表：
- `users`, `tenants`, `projects`, `tenant_members`, `project_members`, `roles`, `role_bindings`, `service_accounts`

### P1-2 观测增强
新增/扩展表：
- `error_events`（错误归因维表）
- `cost_ledger`（模型调用成本）
- `job_metrics_hourly`（聚合宽表）

### P1-3 RAG 多模型治理
- `rag_documents` / `rag_embeddings` 增加 `tenant_id/project_id/trace_id/version`
- 增加回归比较字段：`quality_score`, `is_primary`

验收：
- 登录/授权链路能隔离租户与项目
- Observer 可按租户/项目/错误码聚合
- RAG 支持多 embedding 模型并存治理

## 5. P2（工业化收敛）

### P2-1 收紧约束
- 将关键列升级为 `NOT NULL`：`tenant_id`, `project_id`, `version`, `updated_at`
- 增加唯一约束：`(tenant_id, project_id, idempotency_key)`（按表分批）

### P2-2 清理兼容层
- 下线 legacy 查询路径
- 归档旧列/旧视图
- 补最终数据字典文档

验收：
- 线上不再依赖 legacy 字段
- 关键查询均命中新索引
- 契约版本与表结构版本一致

## 6. 回滚策略
- 每个 revision 必须可逆（drop index/constraint/column 前做数据快照）。
- 约束收紧前必须有回填验证脚本与统计报告。
- 遇到锁等待超阈值立即中止并回滚该 revision。
