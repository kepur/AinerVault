# Shared 模型字段映射清单（Round 2）

## 1. 目标
- 将决策A落地为“共享字段标准 -> shared模型 -> 服务私有表映射”的可执行基线。
- 以 `code/shared/ainern2d_shared/ainer_db_models/base.py` 为现状来源。

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

| 表 | 模型 | 现状关键字段 | 缺失字段（按标准） | P级别 |
|---|---|---|---|---|
| `novels` | `Novel` | `id,title,created_at` | `tenant_id,project_id,trace_id,correlation_id,idempotency_key,error_code,version,updated_at,deleted_at,created_by,updated_by` | P0 |
| `chapters` | `Chapter` | `id,novel_id,language_code,chapter_no,created_at` | `tenant_id,project_id,trace_id,correlation_id,idempotency_key,error_code,version,updated_at,deleted_at,created_by,updated_by` | P0 |
| `execution_requests` | `ExecutionRequest` | `id,novel_id,chapter_id,status,created_at,updated_at` | `tenant_id,project_id,trace_id,correlation_id,idempotency_key,error_code,version,deleted_at,created_by,updated_by` | P0 |
| `render_runs` | `RenderRun` | `id,chapter_id,status,stage,created_at` | `tenant_id,project_id,trace_id,correlation_id,idempotency_key,error_code,version,updated_at,deleted_at,created_by,updated_by` | P0 |
| `jobs` | `Job` | `id,run_id,status,dedupe_key,created_at,updated_at,error_message` | `tenant_id,project_id,trace_id,correlation_id,idempotency_key,error_code,version,deleted_at,created_by,updated_by`（`idempotency_key` 可复用/兼容 `dedupe_key`） | P0 |
| `artifacts` | `Artifact` | `id,run_id,shot_id,type,path,created_at` | `tenant_id,project_id,trace_id,correlation_id,idempotency_key,error_code,version,updated_at,deleted_at,created_by,updated_by` | P0 |
| `entities` | `Entity` | `id,novel_id,type,label,created_at` | `tenant_id,project_id,trace_id,correlation_id,idempotency_key,error_code,version,updated_at,deleted_at,created_by,updated_by` | P1 |
| `rag_documents` | `RagDocument` | `id,scope,source_type,novel_id,created_at` | `tenant_id,project_id,trace_id,correlation_id,idempotency_key,error_code,version,updated_at,deleted_at,created_by,updated_by` | P1 |
| `rag_embeddings` | `RagEmbedding` | `id,doc_id,embedding_model_profile_id,embedding_dim,created_at` | `tenant_id,project_id,trace_id,correlation_id,idempotency_key,error_code,version,updated_at,deleted_at,created_by,updated_by` | P1 |

## 4. 标准约束与索引策略

### 4.1 统一唯一性
- 业务去重键：`(tenant_id, project_id, idempotency_key)`。
- 任务去重兼容：`jobs` 保留 `(job_type, dedupe_key)`，新增 `(tenant_id, project_id, idempotency_key)`。

### 4.2 统一查询索引
- 生命周期索引：`(tenant_id, project_id, created_at)`。
- 链路追踪索引：`trace_id`、`correlation_id`。
- 状态查询索引：`status` 与 `updated_at` 组合。

### 4.3 软删除规范
- 增加 `deleted_at`；所有业务查询默认 `deleted_at IS NULL`。

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
