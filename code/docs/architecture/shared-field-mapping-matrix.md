# Shared 模型字段映射清单（Round 2）

## 1. 目标
- 将决策A落地为“共享字段标准 -> shared模型 -> 服务私有表映射”的可执行基线。
- 以 `code/shared/ainern2d_shared/ainer_db_models/base_model.py` 与各域模型文件为现状来源。

## 2. 共享字段标准（必须统一命名）
- `tenant_id`
- `project_id`
- `trace_id`
- `correlation_id`
- `idempotency_key`
- `error_code`
- `version`
- `created_at`
- `updated_at`
- `deleted_at`
- `created_by`
- `updated_by`

## 3. 核心表现状与目标映射（shared）

当前 `57` 个共享模型均继承 `StandardColumnsMixin`，核心共享标准列已统一落地。

| 表 | 模型 | 标准字段继承状态 | 当前差异/说明 | P级别 |
|---|---|---|---|---|
| `novels` | `Novel` | 已通过 | 无 | DONE |
| `chapters` | `Chapter` | 已通过 | 无 | DONE |
| `execution_requests` | `ExecutionRequest` | 已通过 | 无 | DONE |
| `render_runs` | `RenderRun` | 已通过 | `started_at/finished_at` 仍为字符串时间（见 4.4） | P1 |
| `jobs` | `Job` | 已通过 | `locked_at/next_retry_at` 仍为字符串时间（见 4.4） | P1 |
| `artifacts` | `Artifact` | 已通过 | 无 | DONE |
| `entities` | `Entity` | 已通过 | 无 | DONE |
| `rag_documents` | `RagDocument` | 已通过 | 无 | DONE |
| `rag_embeddings` | `RagEmbedding` | 已通过 | 无 | DONE |

## 4. 标准约束与索引策略

### 4.0 时间与类型权威（新增）
- `created_at/updated_at/deleted_at/occurred_at`：统一使用 `TIMESTAMP WITH TIME ZONE`。
- 事件与运行时间字段禁止使用业务自定义字符串时间。
- API 层时间序列化统一为 `ISO-8601 UTC`（示例：`2026-02-26T12:00:00Z`）。
- 重试与调度时间（如 `next_retry_at`）必须可转换为数据库 timestamp 并可索引。
- 若历史字段为字符串，视为过渡字段，后续统一迁移到 timestamp 类型。

### 4.1 统一唯一性
- 业务去重键：`(tenant_id, project_id, idempotency_key)`。
- 任务去重约束：`jobs` 以 `(tenant_id, project_id, job_type, idempotency_key)` 为权威约束。
- 历史 `dedupe_key` 兼容仅允许在服务适配层实现，不回写共享模型字段。

### 4.2 统一查询索引
- 生命周期索引：`(tenant_id, project_id, created_at)`。
- 链路追踪索引：`trace_id`、`correlation_id`。
- 状态查询索引：`status` 与 `updated_at` 组合。

### 4.3 软删除规范
- 增加 `deleted_at`；所有业务查询默认 `deleted_at IS NULL`。

### 4.4 当前模型偏差（实现前必须知晓）
- 运行态时间字段仍有字符串列：`render_runs.started_at/finished_at`、`jobs.locked_at/next_retry_at`、`workflow_events.occurred_at`、`job_attempts.started_at/finished_at`。
- 以上字段在新代码实现中必须统一输出 `ISO-8601 UTC`，并在后续迁移中收敛到 `TIMESTAMP WITH TIME ZONE`。
- 如果历史系统仍依赖 `dedupe_key`，必须在服务适配层做兼容映射，不允许回退共享模型命名标准。

## 5. 服务私有表映射规则
- Orchestrator 私有表必须继承：`tenant_id,project_id,trace_id,correlation_id,idempotency_key,error_code`。
- Worker Hub/Worker 私有执行日志必须继承：`tenant_id,project_id,trace_id,job_id,error_code,created_at`。
- Composer 私有合成批次必须继承：`tenant_id,project_id,trace_id,run_id,error_code`。
- Observer 聚合宽表至少保留：`tenant_id,project_id,trace_id,error_code,metric_ts`。

## 6. 模型拆分建议（与决策A一致）
- `pipeline_models.py`：ExecutionRequest / RenderRun / Job / IntegrationEvent。
- `content_models.py`：Novel / Chapter / Shot / Dialogue / Artifact。
- `knowledge_models.py`：Entity / Relationship / Event / EntityState。
- `rag_models.py`：RagCollection / RagDocument / RagEmbedding。
- `auth_models.py`：User / Tenant / Project / Role / Membership（新增）。

## 7. RAG 进化闭环新增对象（P0/P1）

| 表 | 用途 | 关键字段 | P级别 |
|---|---|---|---|
| `knowledge_items` | 可编辑知识条目 | `role,title,content_type,strength,status,version` | P0 |
| `kb_versions` | 知识库发布版本 | `kb_version_id,release_notes,status,active_flag` | P0 |
| `kb_version_items` | 版本与条目关联 | `kb_version_id,knowledge_item_id,action` | P0 |
| `rag_chunks` | 文本切片层 | `knowledge_item_id,chunk_text,chunk_meta,embedding_status` | P0 |
| `feedback_events` | 用户反馈记录 | `run_id,shot_id,rating,issues,free_text,action_taken` | P0 |
| `improvement_proposals` | 进化提案 | `feedback_event_id,suggested_role,suggested_tags,status` | P0 |
| `proposal_reviews` | 提案审核记录 | `proposal_id,decision,reviewer,decision_reason` | P0 |
| `eval_reports` | RAG评测报告 | `kb_version_id,recall_at_k,conflict_rate,recommendation` | P1 |
| `rollout_records` | 版本推广与回滚 | `from_version,to_version,rollout_status,rollback_reason` | P1 |

约束建议：
- 所有新表继承统一字段标准。
- `run` 记录必须可回溯到 `kb_version_id + recipe_id + embedding_model_profile_id`。
