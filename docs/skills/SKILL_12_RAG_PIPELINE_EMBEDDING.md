# 12_RAG_PIPELINE_EMBEDDING.md
# RAG Pipeline: Chunking + Embedding + Indexing + Eval（向量化管线 Skill 模板｜中文版）

## 0. 文档定位
本 Skill 定义从 Knowledge Items 到“可检索向量索引”的完整管线：
- 文档/条目解析
- 切片（chunking）策略
- embedding 生成与存储（pgvector）
- 索引版本化（kb_version_id）
- 检索过滤（role/tags/strength）
- 质量评测与回滚建议

> 本模块不负责前端管理（见 11），也不负责反馈生成（见 13）。

---

## 术语对齐声明（固定模板）
- 本文统一运行对象命名：`run / job / stage / event / artifact`。
- `run`：一次端到端业务运行；`job`：run 内原子执行单元；`stage`：run 阶段状态。
- `event`：跨模块事实消息，统一采用 `EventEnvelope`；`artifact`：可回溯产物元数据。
- `worker.*.completed` 为执行明细事件，不替代 `job.succeeded / job.failed` 主状态事件。
- `step` 仅表示内部步骤序号，不作为运行态主对象或事件前缀。
- 必带治理字段：`tenant_id / project_id / trace_id / correlation_id / idempotency_key / schema_version`。

## 1. Workflow Goal（目标）
针对某个 `kb_release_manifest.json`：
1. 将 included_items 的内容切片为 chunks
2. 为 chunks 生成 embedding 向量
3. 写入向量索引（按 kb_version 分区或带版本字段）
4. 生成检索用元数据索引（role/tags/strength/status）
5. 跑基础评测（召回正确性/冲突率/长度等）
6. 输出 `kb_index_build_report.json`

---

## 2. Inputs（输入）

### 2.1 必需输入
- `kb_release_manifest.json`（来自 11）
- `knowledge_items[]`（manifest 包含的条目内容与元数据）
- `embedding_model_config`
- `vector_store_config`（pgvector）
- `chunking_policy_id`

### 2.2 可选输入
- `preview_queries[]`（用于回归评测）
- `role_recipes[]`（用于多角色组合检索测试）
- `feature_flags`
  - enable_semantic_chunking
  - enable_dedup
  - enable_eval_suite
  - enable_conflict_scan

---

## 3. Outputs（输出）

### 3.1 主输出文件
- `kb_index_build_report.json`

### 3.2 产物
- `chunks` 表/集合（chunk_text + meta）
- `embeddings` 表/向量列（pgvector）
- `kb_version` 与 `index_version` 状态

---

## 4. Chunking Policy（切片策略）

### 4.1 建议按 content_type 选择策略
- rule / checklist：短切片（150~400 tokens），尽量“一条规则一个chunk”
- template：按字段块切（title / steps / example）
- long_doc：按标题/小节 + 语义切分（400~900 tokens）
- anti_pattern：短切片，强调“不要做什么”

### 4.2 chunk 元数据必须包含
- kb_version_id
- knowledge_item_id
- role
- tags（flatten）
- strength
- status（active/deprecated）
- content_type
- source
- created_at/updated_at

---

## 5. Indexing & Retrieval Rules（索引与检索规则）

### 5.1 强约束优先（hard_constraint）
检索合并时必须：
1. hard_constraint 优先于 soft_preference
2. 冲突时输出 conflict candidates（供上层处理）

### 5.2 Filter-first 再向量检索（推荐）
1. role 过滤（或 role recipe）
2. tags/locale/culture_pack/genre/era/style_mode 过滤
3. 再做向量相似度 top-k
4. 再按 strength/recency/quality 排序融合

---

## 6. Branching Logic（分支流程与判断）

### [P1] Precheck（预检查）
#### Actions
1. 检查 manifest 完整性（included_items、chunking_policy、embedding_model）
2. 校验 items 状态（active vs deprecated）
3. 生成 build_id
#### Output
- build_context

---

### [P2] Parse & Normalize（解析与规范化）
#### Actions
1. Markdown/HTML 清洗
2. 去除无意义噪声（过长重复、目录样板）
3. 标准化换行与空白
#### Output
- normalized item texts

---

### [P3] Chunking（切片）
#### Actions
1. 按 content_type 选择切片策略
2. 生成 chunks（chunk_text + meta）
3. 可选去重（相似chunk合并）
4. 记录 chunk_count、平均长度
#### Output
- chunks[]

---

### [P4] Embedding（向量化）
#### Actions
1. 对 chunks 批量生成 embedding
2. 写入 pgvector（带 kb_version_id）
3. 标记 embedding_status=ready
#### Output
- embedding stats

---

### [P5] Index Build（索引构建）
#### Actions
1. 构建/更新检索索引（元数据过滤索引）
2. 若采用分区：创建 kb_version 分区
3. 输出 index metadata
#### Output
- index metadata

---

### [P6] Eval Suite（评测，建议启用）
#### Actions
1. 对 preview_queries 跑检索
2. 指标：
   - recall@k（是否召回预期条目/角色）
   - constraint_conflict_rate（硬约束冲突率）
   - redundancy（重复率）
   - avg_latency（可选）
3. 生成建议：
   - 是否发布为 active index
   - 是否回滚
#### Output
- eval report

---

## 7. State Machine（状态机）
States:
- INIT
- PRECHECKING
- NORMALIZING
- CHUNKING
- EMBEDDING
- BUILDING_INDEX
- EVALUATING
- INDEX_READY
- REVIEW_REQUIRED
- FAILED

---

## 8. Output Contract（输出契约）
```json
{
  "version": "1.0",
  "kb_version_id": "KB_V1_20260226_001",
  "build_id": "KB_BUILD_0001",
  "status": "index_ready",
  "chunking_policy_id": "CHUNK_POLICY_V1",
  "embedding_model": "your_embedding_model_name",
  "stats": {
    "items": 42,
    "chunks": 318,
    "avg_chunk_chars": 820,
    "embedding_time_sec": 54.2
  },
  "eval": {
    "enabled": true,
    "preview_queries": 20,
    "recall_at_8": 0.85,
    "constraint_conflict_rate": 0.07,
    "redundancy_rate": 0.11,
    "recommendation": "promote_to_active"
  },
  "warnings": [],
  "review_required_items": []
}
```

---

## 9. Operational Notes（运维要点）
- 建议 embedding 异步任务队列化（RabbitMQ/Redis queue）
- 建议对 kb_version 进行分区或至少加索引字段
- 记录 embedding 模型版本，方便回溯
- 对 deprecated 条目：默认不检索，但保留可追溯查询

---

## 10. Definition of Done（完成标准）
- [ ] 已生成 chunks 并写入存储
- [ ] 已生成 embeddings 并写入 pgvector
- [ ] 已构建/更新元数据索引
- [ ] 已输出 build report
- [ ] 若启用评测：已输出评测指标与推荐

---

## 11. 多 Embedding 治理（P1）

### 11.1 模型并存策略
- 同一 `doc/chunk` 允许多 embedding 模型并存。
- 必须记录：`embedding_model_profile_id`, `embedding_dim`, `is_primary`。
- 发布前要通过 `primary` 与 `candidate` 对照评测。

### 11.2 发布门禁
- `recall_at_k < 阈值` 或 `constraint_conflict_rate > 阈值` 时禁止 promote。
- 评测通过后才允许触发：`kb.rollout.promoted`。

### 11.3 关键事件
- `rag.chunking.started`
- `rag.embedding.completed`
- `rag.index.ready`
- `rag.eval.completed`

### 11.4 与 13 的衔接
- 13 审核通过提案后，必须触发增量 re-embed。
- 评测报告回传 13 作为“是否推广/回滚”依据。
