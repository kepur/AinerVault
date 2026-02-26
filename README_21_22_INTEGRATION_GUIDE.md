# README_21_22_INTEGRATION_GUIDE.md
# 21~22 接入 01~22 的工程落地说明

本文用于把 `SKILL_21` 与 `SKILL_22` 接入当前 01~22 主链，目标是让其他 AI/开发者可直接按文档落地，不跑偏。

新增模块：
- `21_ENTITY_REGISTRY_CONTINUITY_MANAGER`
- `22_PERSONA_DATASET_INDEX_MANAGER`

---

## 1. 模块定位（先定边界）

### 1.1 SKILL 21 定位
`21` 不是替代 `04/07/08`，而是补“长期身份与连续性主档案层”：
- 把 `04` 抽取结果绑定到稳定 `entity_id`
- 管理跨 shot/scene/chapter 的 continuity anchors
- 为 `07/08/10/16` 输出可复用的一致性基线

### 1.2 SKILL 22 定位
`22` 不是替代 `11/12/14`，而是补“Dataset/Index/Persona 组装与谱系层”：
- `11/12` 负责 KB 与向量索引能力
- `14` 负责 style DNA / persona pack
- `22` 负责三者组合、版本升级、分叉谱系、预览

---

## 2. 推荐插入点（主链）

核心插入：
- `04 -> 21 -> 07`
- `11 + 12 + 14 -> 22 -> 10/15/17`

升级后推荐主链（01~22）：
1. `01` Story Ingestion
2. `02` Language Context Router
3. `03` Story->Scene->Shot Planner
4. `04` Entity Extraction
5. `21` Entity Registry & Continuity Manager
6. `05` Audio Asset Planner
7. `06` Audio Timeline Composer
8. `07` Entity Canonicalization + Cultural Binding
9. `08` Asset Matcher
10. `11` RAG KB Manager
11. `12` RAG Pipeline Embedding
12. `14` Persona Style Pack Manager
13. `22` Persona Dataset & Index Manager
14. `15` Creative Control Policy
15. `19` Compute-Aware Shot Budgeter
16. `09` Visual Render Planner
17. `10` Prompt Planner
18. `20` Shot DSL Compiler
19. 执行渲染（workers）
20. `16` Critic Evaluation
21. `18` Failure Recovery & Degradation
22. `13` Feedback Evolution Loop
23. `17` Experiment A/B Orchestrator

---

## 3. SKILL 21 接入规范

### 3.1 上下游契约
上游输入：
- `04` 的实体抽取结果
- `03` 的 `shot_plan`

下游输出消费者：
- `07`：固定 `entity_id` + alias/anchor 后再做 canonicalization/cultural binding
- `08`：按 continuity anchors 进行素材选择
- `10`：按角色/场景/道具锚点生成 prompt
- `16`：对 continuity rules 做评审基线

### 3.2 最小必交付字段（MVP）
- `resolved_entities[]`（source_uid -> entity_id）
- `entity_instance_links[]`（entity_id 与 shot_id/scene_id 绑定）
- `continuity_anchors[]`（角色、场景、道具一致性锚点）
- `review_required_items[]`

### 3.3 DB 落地映射（基于现有 shared models）
优先复用现有表：
- `entities`
- `entity_aliases`
- `entity_states`
- `relationships`

建议新增（若当前能力不足）：
- `entity_instance_links`（实体与 shot/scene 实例关系）
- `entity_continuity_profiles`（连续性规则与 anchor 档案）

说明：
- 新增系统级表必须进 `code/shared/ainern2d_shared/ainer_db_models/`
- 必须用新 Alembic revision，禁止改基线迁移

---

## 4. SKILL 22 接入规范

### 4.1 上下游契约
上游输入：
- `11`（KB 版本与条目）
- `12`（embedding/index 产物）
- `14`（persona style pack）

下游输出消费者：
- `10`：明确当前 run 使用哪个 persona + dataset/index/style
- `15`：策略栈按 persona profile 选择 policy override
- `17`：A/B/C 实验按 persona lineage 进行变量编排
- `13`：反馈能回流到具体分支（A v2 / B v1 等）

### 4.2 最小必交付字段（MVP）
- `datasets[]`
- `indexes[]`
- `personas[]`（包含 dataset/index/style_pack 绑定）
- `lineage_graph`
- `preview_retrieval_plan`

### 4.3 DB 落地映射（基于现有 shared models）
优先复用现有表：
- `rag_collections`
- `kb_versions`
- `rag_documents`
- `rag_embeddings`
- `persona_packs`
- `persona_pack_versions`
- `creative_policy_stacks`
- `experiment_runs/experiment_arms/experiment_observations`

建议新增（若当前能力不足）：
- `persona_dataset_bindings`
- `persona_index_bindings`
- `persona_lineage_edges`
- `persona_runtime_manifests`

---

## 5. 编排与代码接入清单（必须改）

为让 21/22 真正“接入”而不是只在文档存在，需要至少完成：
1. `JobType` 增加 `skill_21` / `skill_22` 对应 job type。
2. DAG 默认序列插入 21（在 04 后）和 22（在 14 后）。
3. studio/composer dispatcher 增加 job_type -> skill_id 映射。
4. `SkillRegistry` 注册 `skill_21` / `skill_22` service。
5. shared schemas 新增 `skill_21.py` / `skill_22.py` DTO。
6. 为 21/22 增加单测与链路集成测试（至少覆盖 happy path + review_required）。

---

## 6. 事件/错误码/治理约束（防跑偏）

必须遵守现有治理文档：
- 事件：运行主线只用 `run.*` / `job.*`，新增事件先登记 `ainer_event_types.md`
- 错误码：仅使用 `ainer_error_code.md` 已定义域（如 `REQ/RAG/PLAN/ORCH/...`）
- 所有输入输出必须携带治理字段：
  `tenant_id/project_id/trace_id/correlation_id/idempotency_key/schema_version`

---

## 7. 最小接入方案（推荐）

### Phase A: 先上 21（实体一致性）
- 固定人物/场景/道具 `entity_id`
- 建立 shot 实例 link
- 输出 continuity anchors 给 `10`

### Phase B: 再上 22（导演人格组装）
- Dataset 管理
- Index 选择与绑定
- Persona 绑定 dataset/index/style_pack
- Persona Preview（输入 query 查看召回来源）

---

## 8. 一句总结
- `21` 让“世界与角色”具备可追溯的长期一致性。
- `22` 让“导演 A/B/C”成为可升级、可分支、可预览的工业级运行对象。

---

## 9. 历史文档处理状态（已执行）
为避免 AI 读取旧口径导致跑偏，历史审计快照与旧接入说明已完成物理删除并清理引用。
