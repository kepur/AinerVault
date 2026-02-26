# SKILL 落地实现进度跟踪

> **本文档是所有 AI Agent 接力实现 SKILL 的唯一进度基线。**
> 每次 AI 实现/修改任意 SKILL 后，**必须**更新本文档对应行的状态和备注。
> 任何 AI 接手前，**必须**先读本文档了解全局进度，再选取 `NOT_STARTED` 或 `PARTIAL` 状态的 SKILL 开始。

---

## 0. 状态枚举

| 状态 | 含义 |
|------|------|
| `NOT_STARTED` | 尚未开始编码 |
| `PARTIAL` | 有基础骨架/部分逻辑，但未满足 Definition of Done |
| `SERVICE_READY` | Service 层 + DTO 已就绪，核心 execute() 可调用 |
| `INTEGRATION_READY` | 已与 Orchestrator 集成，可被 pipeline 调度 |
| `TESTED` | 单元测试通过，E2E 验证完成 |
| `DONE` | 全部 Definition of Done 满足，已合入主线 |

---

## 1. 总览

| # | SKILL | 状态 | 所属服务 | Service 类 | 上次更新 | 更新者 |
|---|-------|------|---------|-----------|---------|--------|
| 01 | Story Ingestion & Normalization | `SERVICE_READY` | studio-api | `StoryIngestionService` | 2026-02-26 | Copilot |
| 02 | Language Context Router | `SERVICE_READY` | studio-api | `LanguageContextService` | 2026-02-26 | Copilot |
| 03 | Story→Scene→Shot Planner | `SERVICE_READY` | studio-api | `SceneShotPlanService` | 2026-02-26 | Copilot |
| 04 | Entity Extraction & Structuring | `SERVICE_READY` | studio-api | `EntityExtractionService` | 2026-02-26 | Copilot |
| 05 | Audio Asset Planner | `SERVICE_READY` | studio-api | `AudioAssetPlanService` | 2026-02-27 | Copilot |
| 06 | Audio Timeline Composer | `SERVICE_READY` | composer | `AudioTimelineService` | 2026-02-27 | Copilot |
| 07 | Entity Canonicalization & Cultural Binding | `SERVICE_READY` | studio-api | `CanonicalizationService` | 2026-02-27 | Copilot |
| 08 | Asset Matcher | `SERVICE_READY` | studio-api | `AssetMatcherService` | 2026-02-27 | Copilot |
| 09 | Visual Render Planner | `SERVICE_READY` | studio-api | `VisualRenderPlanService` | 2026-02-27 | Copilot |
| 10 | Prompt Planner | `SERVICE_READY` | studio-api | `PromptPlannerService` | 2026-02-27 | Copilot |
| 11 | RAG KB Manager | `SERVICE_READY` | studio-api | `RagKBManagerService` | 2026-02-27 | Copilot |
| 12 | RAG Pipeline & Embedding | `SERVICE_READY` | studio-api | `RagEmbeddingService` | 2026-02-27 | Copilot |
| 13 | Feedback Evolution Loop | `SERVICE_READY` | studio-api | `FeedbackLoopService` | 2026-02-27 | Copilot |
| 14 | Persona & Style Pack Manager | `SERVICE_READY` | studio-api | `PersonaStyleService` | 2026-02-27 | Copilot |
| 15 | Creative Control Policy | `SERVICE_READY` | studio-api | `CreativeControlService` | 2026-02-27 | Copilot |
| 16 | Critic Evaluation Suite | `SERVICE_READY` | studio-api | `CriticEvaluationService` | 2026-02-27 | Copilot |
| 17 | Experiment & A/B Test | `SERVICE_READY` | studio-api | `ExperimentService` | 2026-02-27 | Copilot |
| 18 | Failure Recovery & Degradation | `SERVICE_READY` | studio-api | `FailureRecoveryService` | 2026-02-27 | Copilot |
| 19 | Compute-Aware Shot Budgeter | `SERVICE_READY` | studio-api | `ComputeBudgetService` | 2026-02-27 | Copilot |
| 20 | Shot DSL Compiler & Prompt Backend | `SERVICE_READY` | composer | `DslCompilerService` | 2026-02-27 | Copilot |

---

## 2. SKILL → 代码文件映射

> AI Agent 实现某个 SKILL 时，修改的文件**必须**在下方对应区域内，不得越界。

### SKILL 01: Story Ingestion & Normalization
- **规格文档**: `SKILL_01_STORY_INGESTION_NORMALIZATION.md`
- **Service**: `code/apps/ainern2d-studio-api/app/services/skills/skill_01_story_ingestion.py`
- **DTO**: `code/shared/ainern2d_shared/schemas/skills/skill_01.py`
- **依赖模块**: `modules/entiry_core/normalizer.py`, `modules/entiry_core/extractor.py`
- **DB 表**: `documents`, `document_segments`, `content_chapters`
- **状态机**: `INIT → PRECHECKING → NORMALIZING → PARSING_STRUCTURE → DETECTING_LANGUAGE → QUALITY_CHECKING → READY_FOR_ROUTING | REVIEW_REQUIRED | FAILED`
- **输入事件**: `task.submitted`（首个 SKILL，由 Orchestrator 触发）
- **输出事件**: `skill.01.completed` → 触发 SKILL 02
- **Definition of Done**:
  - [ ] `normalized_story.json` 输出契约完整（document_meta + language_detection + structure + segments[] + quality_report）
  - [ ] 状态机全路径覆盖（含 REVIEW_REQUIRED 分支）
  - [ ] 幂等性：相同 idempotency_key 不重复处理
  - [ ] 错误时 error_code 符合 `ainer_error_code.md`

### SKILL 02: Language Context Router
- **规格文档**: `SKILL_02_LANGUAGE_CONTEXT_ROUTER.md`
- **Service**: `code/apps/ainern2d-studio-api/app/services/skills/skill_02_language_context.py`
- **DTO**: `code/shared/ainern2d_shared/schemas/skills/skill_02.py`
- **依赖模块**: `modules/entiry_core/normalizer.py`, `modules/entiry_core/continuity.py`
- **DB 表**: `language_routes`, `culture_mappings`
- **状态机**: `INIT → DETECTING → CULTURE_ANALYZING → ROUTING_DECISION → READY_FOR_PLANNING | FAILED`
- **输入事件**: `skill.01.completed`
- **输出事件**: `skill.02.completed` → 触发 SKILL 03 + SKILL 04（并行）
- **Definition of Done**:
  - [ ] 输出 `language_route.json`（language_code + culture_candidates + kb_suggestions）
  - [ ] 支持多语言路由（zh-CN/en-US/ja-JP 至少）
  - [ ] 幂等性 + error_code 规范

### SKILL 03: Story→Scene→Shot Planner
- **规格文档**: `SKILL_03_STORY_SCENE_SHOT_PLANNER.md`
- **Service**: `code/apps/ainern2d-studio-api/app/services/skills/skill_03_scene_shot_plan.py`
- **DTO**: `code/shared/ainern2d_shared/schemas/skills/skill_03.py`
- **依赖模块**: `modules/planner/shot_plan.py`
- **DB 表**: `scenes`, `shots`, `shot_entities`
- **状态机**: `INIT → SEGMENTING_SCENES → SPLITTING_SHOTS → TIMING_ESTIMATION → ENTITY_HINT → READY_FOR_PARALLEL_EXECUTION | FAILED`
- **输入事件**: `skill.02.completed`
- **输出事件**: `skill.03.completed` → 触发 SKILL 05 + SKILL 07（并行）
- **Definition of Done**:
  - [ ] 输出 `shot_plan.json`（scenes[] + shots[] + timing + entity_hints[]）
  - [ ] 每个 shot 有 shot_id/scene_id/duration_hint/entity_refs
  - [ ] 支持自定义镜头数量上限（creative_control 约束）

### SKILL 04: Entity Extraction & Structuring
- **规格文档**: `SKILL_04_ENTITY_EXTRACTION_STRUCTURING.md`
- **Service**: `code/apps/ainern2d-studio-api/app/services/skills/skill_04_entity_extraction.py`
- **DTO**: `code/shared/ainern2d_shared/schemas/skills/skill_04.py`
- **依赖模块**: `modules/entiry_core/extractor.py`, `modules/entiry_core/normalizer.py`
- **DB 表**: `entities`, `entity_aliases`, `entity_relationships`
- **状态机**: `INIT → EXTRACTING → CLASSIFYING → LINKING → DEDUP → READY_FOR_CANONICALIZATION | FAILED`
- **输入事件**: `skill.02.completed`（与 SKILL 03 并行）
- **输出事件**: `skill.04.completed` → 触发 SKILL 07
- **Definition of Done**:
  - [ ] 输出结构化实体列表（characters/locations/props/clothing）
  - [ ] 每个实体有 canonical_name + aliases[] + entity_type + first_appearance
  - [ ] 去重逻辑正确（同一角色不同称呼归并）

### SKILL 05: Audio Asset Planner
- **规格文档**: `SKILL_05_AUDIO_ASSET_PLANNER.md`
- **Service**: `code/apps/ainern2d-studio-api/app/services/skills/skill_05_audio_asset_plan.py`
- **DTO**: `code/shared/ainern2d_shared/schemas/skills/skill_05.py`
- **依赖模块**: `modules/planner/production_scheduler.py`
- **DB 表**: `audio_tasks`, `audio_assets`
- **状态机**: `INIT → CLASSIFYING_AUDIO → SCHEDULING_TTS → SCHEDULING_BGM → SCHEDULING_SFX → READY_FOR_AUDIO_EXECUTION | FAILED`
- **输入事件**: `skill.03.completed`
- **输出事件**: `skill.05.completed` → 触发 Worker-Audio 执行
- **Definition of Done**:
  - [ ] 输出 `audio_task_plan.json`（tts_tasks[] + bgm_tasks[] + sfx_tasks[] + ambience_tasks[]）
  - [ ] 每个任务有 shot_id + asset_ref + priority + timing_hint

### SKILL 06: Audio Timeline Composer
- **规格文档**: `SKILL_06_AUDIO_TIMELINE_COMPOSER.md`
- **Service**: `code/apps/ainern2d-composer/app/services/skills/skill_06_audio_timeline.py`
- **DTO**: `code/shared/ainern2d_shared/schemas/skills/skill_06.py`
- **依赖模块**: `timeline/assembler.py`, `timeline/validator.py`
- **DB 表**: `timeline_tracks`, `timeline_events`, `audio_artifacts`
- **状态机**: `INIT → COLLECTING_RESULTS → ALIGNING → COMPOSING → VALIDATING → READY_FOR_VISUAL_RENDER_PLANNING | FAILED`
- **输入事件**: Worker-Audio 全部完成后
- **输出事件**: `skill.06.completed` → 触发 SKILL 09
- **Definition of Done**:
  - [ ] 输出 `audio_event_manifest.json`（tracks[] + timing_anchors[] + total_duration）
  - [ ] 时间轴对齐精度 ≤ 50ms
  - [ ] 支持轨道优先级和音量自动调节

### SKILL 07: Entity Canonicalization & Cultural Binding
- **规格文档**: `SKILL_07_ENTITY_CANONICALIZATION_CULTURAL_BINDING.md`
- **Service**: `code/apps/ainern2d-studio-api/app/services/skills/skill_07_canonicalization.py`
- **DTO**: `code/shared/ainern2d_shared/schemas/skills/skill_07.py`
- **依赖模块**: `modules/entiry_core/world_pach_builder.py`, `modules/entiry_core/continuity.py`
- **DB 表**: `entity_canonical`, `culture_bindings`, `entity_variants`
- **状态机**: `INIT → CANONICALIZING → CANONICAL_READY → CULTURE_ROUTING → CULTURE_BOUND → VARIANT_MAPPING → VARIANTS_READY → CONFLICT_CHECK → READY_FOR_ASSET_MATCH | FAILED`
- **输入事件**: `skill.04.completed` + `skill.03.completed`
- **输出事件**: `skill.07.completed` → 触发 SKILL 08
- **Definition of Done**:
  - [ ] 每个实体有 canonical_form + culture_variants[] + visual_tags[]
  - [ ] 冲突检测：同一文化下无重名实体
  - [ ] 连续性校验：跨场景实体外观一致

### SKILL 08: Asset Matcher
- **规格文档**: `SKILL_08_ASSET_MATCHER.md`
- **Service**: `code/apps/ainern2d-studio-api/app/services/skills/skill_08_asset_matcher.py`
- **DTO**: `code/shared/ainern2d_shared/schemas/skills/skill_08.py`
- **依赖模块**: `modules/asset-knowledge/retrieval.py`, `modules/asset-knowledge/bybrid_search.py`
- **DB 表**: `asset_candidates`, `asset_matches`, `knowledge_entries`
- **状态机**: `INIT → PRECHECKING → PRECHECK_READY → PRIORITIZING → RETRIEVING_CANDIDATES → SCORING_RANKING → READY_FOR_PROMPT_PLANNER | FAILED`
- **输入事件**: `skill.07.completed`
- **输出事件**: `skill.08.completed` → 触发 SKILL 09 + SKILL 10
- **Definition of Done**:
  - [ ] 输出 `asset_manifest.json`（entity→asset_candidate[] 映射）
  - [ ] 每个 candidate 有 score + source + confidence
  - [ ] 支持 RAG hybrid search（向量 + 关键词）

### SKILL 09: Visual Render Planner
- **规格文档**: `SKILL_09_VISUAL_RENDER_PLANNER.md`
- **Service**: `code/apps/ainern2d-studio-api/app/services/skills/skill_09_visual_render_plan.py`
- **DTO**: `code/shared/ainern2d_shared/schemas/skills/skill_09.py`
- **依赖模块**: `modules/planner/budget_degrade.py`
- **DB 表**: `render_plans`, `shot_render_configs`
- **状态机**: `INIT → PRECHECKING → PRECHECK_READY → AUDIO_FEATURES_READY → STRATEGY_READY → SHOT_LEVEL_PLANNING → READY_FOR_RENDER_EXECUTION | FAILED`
- **输入事件**: `skill.06.completed` + `skill.08.completed`
- **输出事件**: `skill.09.completed` → 触发 SKILL 10 + SKILL 19
- **Definition of Done**:
  - [ ] 输出 `render_plan.json`（shots[] 含 mode/fps/resolution/priority/fallback_chain）
  - [ ] 受 compute_budget 约束（SKILL 19 输出）
  - [ ] 每个 shot 有 i2v/v2v 模式选择和回退链

### SKILL 10: Prompt Planner
- **规格文档**: `SKILL_10_PROMPT_PLANNER.md`
- **Service**: `code/apps/ainern2d-studio-api/app/services/skills/skill_10_prompt_planner.py`
- **DTO**: `code/shared/ainern2d_shared/schemas/skills/skill_10.py`
- **依赖模块**: `modules/asset-knowledge/embedding.py`, `modules/asset-knowledge/ingest.py`
- **DB 表**: `prompt_plans`, `shot_prompts`, `model_variants`
- **状态机**: `INIT → PRECHECKING → PRECHECK_READY → GLOBAL_CONSTRAINTS_READY → SHOT_LAYERING → MICROSHOT_LAYERING → MODEL_VARIANTS → PRESET_MAPPING → FALLBACK_PREP → ASSEMBLY → READY_FOR_PROMPT_EXECUTION | FAILED`
- **输入事件**: `skill.08.completed` + `skill.09.completed`
- **输出事件**: `skill.10.completed` → 触发 SKILL 20（DSL 编译）
- **Definition of Done**:
  - [ ] 输出 `prompt_plan.json`（global_constraints + shot_prompt_plans[] + model_variants[]）
  - [ ] 支持多模型变体（ComfyUI / SDXL / Flux）
  - [ ] Persona 风格注入（SKILL 14 输出）

### SKILL 11: RAG KB Manager
- **规格文档**: `SKILL_11_RAG_KB_MANAGER.md`
- **Service**: `code/apps/ainern2d-studio-api/app/services/skills/skill_11_rag_kb_manager.py`
- **DTO**: `code/shared/ainern2d_shared/schemas/skills/skill_11.py`
- **依赖模块**: `modules/asset-knowledge/ingest.py`
- **DB 表**: `knowledge_bases`, `kb_versions`, `kb_entries`
- **状态机**: `INIT → CREATING → VALIDATING → INDEXING → READY_TO_RELEASE → ACTIVE_VERSION_READY | FAILED`
- **输入事件**: 用户手动触发 或 `skill.13.completed`（反馈循环）
- **输出事件**: `skill.11.completed` → 触发 SKILL 12
- **Definition of Done**:
  - [ ] KB 版本管理（创建/发布/回滚）
  - [ ] 入库条目验证（格式/重复/质量）
  - [ ] 支持增量更新（不重建全量索引）

### SKILL 12: RAG Pipeline & Embedding
- **规格文档**: `SKILL_12_RAG_PIPELINE_EMBEDDING.md`
- **Service**: `code/apps/ainern2d-studio-api/app/services/skills/skill_12_rag_embedding.py`
- **DTO**: `code/shared/ainern2d_shared/schemas/skills/skill_12.py`
- **依赖模块**: `modules/asset-knowledge/embedding.py`
- **DB 表**: `rag_chunks`, `rag_embeddings`, `rag_indexes`
- **状态机**: `INIT → CHUNKING → EMBEDDING → INDEXING → QUALITY_CHECK → INDEX_READY | FAILED`
- **输入事件**: `skill.11.completed`
- **输出事件**: `skill.12.completed`（索引可用于 SKILL 08 检索）
- **Definition of Done**:
  - [ ] 向量化完成（pgvector 1536 维）
  - [ ] 分块策略可配置（size/overlap）
  - [ ] 索引质量报告（覆盖率/碎片率）

### SKILL 13: Feedback Evolution Loop
- **规格文档**: `SKILL_13_FEEDBACK_EVOLUTION_LOOP.md`
- **Service**: `code/apps/ainern2d-studio-api/app/services/skills/skill_13_feedback_loop.py`
- **DTO**: `code/shared/ainern2d_shared/schemas/skills/skill_13.py`
- **依赖模块**: `modules/observer/aduit.py`
- **DB 表**: `feedback_entries`, `improvement_proposals`, `kb_evolution_triggers`
- **状态机**: `INIT → CAPTURING → ABSTRACTING → PROPOSAL_READY → APPROVAL → COMPLETED | FAILED`
- **输入事件**: 用户反馈 或 `skill.16.completed`（评审结果）
- **输出事件**: `skill.13.completed` → 可触发 SKILL 11（KB 更新）
- **Definition of Done**:
  - [ ] 反馈采集（用户评分 + 文本 + 标注区域）
  - [ ] 抽象化为可执行改进提案
  - [ ] 审批流程（自动/人工）

### SKILL 14: Persona & Style Pack Manager
- **规格文档**: `SKILL_14_PERSONA_STYLE_PACK_MANAGER.md`
- **Service**: `code/apps/ainern2d-studio-api/app/services/skills/skill_14_persona_style.py`
- **DTO**: `code/shared/ainern2d_shared/schemas/skills/skill_14.py`
- **依赖模块**: `modules/planner/creative_policy.py`
- **DB 表**: `personas`, `style_packs`, `persona_rag_bindings`
- **状态机**: `INIT → DEFINING → BINDING_RAG → VERSIONING → READY_TO_PUBLISH | FAILED`
- **输入事件**: 用户配置 或 项目创建时
- **输出事件**: `skill.14.completed`（供 SKILL 10/15 使用）
- **Definition of Done**:
  - [ ] Persona 定义（voice_style + visual_style + narrative_tone）
  - [ ] RAG 绑定（Persona → KB 子集）
  - [ ] 版本管理 + 发布/草稿状态

### SKILL 15: Creative Control Policy
- **规格文档**: `SKILL_15_CREATIVE_CONTROL_POLICY.md`
- **Service**: `code/apps/ainern2d-studio-api/app/services/skills/skill_15_creative_control.py`
- **DTO**: `code/shared/ainern2d_shared/schemas/skills/skill_15.py`
- **依赖模块**: `modules/planner/creative_policy.py`
- **DB 表**: `creative_policies`, `policy_constraints`, `constraint_overrides`
- **状态机**: `INIT → AGGREGATING → CONFLICT_RESOLVING → POLICY_READY | FAILED`
- **输入事件**: SKILL 14 输出 + 项目设置
- **输出事件**: `skill.15.completed`（供 SKILL 09/10/19/20 使用）
- **Definition of Done**:
  - [ ] 输出 `creative_control_stack`（hard_constraints[] + soft_constraints[] + exploration_range）
  - [ ] 冲突解决（hard > soft > exploration）
  - [ ] 支持运行时覆盖（用户手动调节）

### SKILL 16: Critic Evaluation Suite
- **规格文档**: `SKILL_16_CRITIC_EVALUATION_SUITE.md`
- **Service**: `code/apps/ainern2d-studio-api/app/services/skills/skill_16_critic_evaluation.py`
- **DTO**: `code/shared/ainern2d_shared/schemas/skills/skill_16.py`
- **依赖模块**: `modules/observer/metrics_writer.py`
- **DB 表**: `evaluation_results`, `dimension_scores`, `fix_recommendations`
- **状态机**: `INIT → ANALYZING → SCORING → DECISION → COMPLETED | FAILED`
- **输入事件**: compose 完成后
- **输出事件**: `skill.16.completed` → 可触发 SKILL 13（反馈循环）
- **Definition of Done**:
  - [ ] 多维度评分（视觉一致性/音频同步/叙事连贯/风格匹配）
  - [ ] 问题定位（具体 shot_id + 维度 + 严重性）
  - [ ] 修复建议（具体到哪个 SKILL 需要重跑）

### SKILL 17: Experiment & A/B Test Orchestrator
- **规格文档**: `SKILL_17_EXPERIMENT_AB_TEST_ORCHESTRATOR.md`
- **Service**: `code/apps/ainern2d-studio-api/app/services/skills/skill_17_experiment.py`
- **DTO**: `code/shared/ainern2d_shared/schemas/skills/skill_17.py`
- **依赖模块**: `modules/orchestrator/service.py`
- **DB 表**: `experiments`, `experiment_variants`, `experiment_results`
- **状态机**: `INIT → SETUP → EXECUTING → ANALYZING → COMPLETED | FAILED`
- **输入事件**: 用户创建实验
- **输出事件**: `skill.17.completed`（实验结论 + 推荐变体）
- **Definition of Done**:
  - [ ] 实验定义（benchmark_case + variants[] + evaluation_dimensions[]）
  - [ ] 并行执行多变体
  - [ ] 自动排名 + 推荐晋升

### SKILL 18: Failure Recovery & Degradation Policy
- **规格文档**: `SKILL_18_FAILURE_RECOVERY_DEGRADATION_POLICY.md`
- **Service**: `code/apps/ainern2d-studio-api/app/services/skills/skill_18_failure_recovery.py`
- **DTO**: `code/shared/ainern2d_shared/schemas/skills/skill_18.py`
- **依赖模块**: `modules/orchestrator/recovery.py`
- **DB 表**: `recovery_decisions`, `degradation_logs`
- **状态机**: `INIT → ERROR_DETECTION → DECISION → EXECUTING_RECOVERY → COMPLETED | FAILED`
- **输入事件**: `job.failed` 或任何 SKILL 失败
- **输出事件**: `skill.18.completed`（恢复动作：retry/degrade/skip）
- **Definition of Done**:
  - [ ] 决策矩阵（error_code × stage → action）
  - [ ] 降级策略（质量降级/跳过非关键步骤/回退模型）
  - [ ] 重试上限 + 熔断机制

### SKILL 19: Compute-Aware Shot Budgeter
- **规格文档**: `SKILL_19_COMPUTE_AWARE_SHOT_BUDGETER.md`
- **Service**: `code/apps/ainern2d-studio-api/app/services/skills/skill_19_compute_budget.py`
- **DTO**: `code/shared/ainern2d_shared/schemas/skills/skill_19.py`
- **依赖模块**: `modules/planner/budget_degrade.py`
- **DB 表**: `compute_budgets`, `shot_compute_plans`
- **状态机**: `INIT → ANALYZING_LOAD → ALLOCATING → OPTIMIZING → COMPUTE_PLAN_READY | FAILED`
- **输入事件**: `skill.03.completed` + 实时资源状态
- **输出事件**: `skill.19.completed`（供 SKILL 09 使用）
- **Definition of Done**:
  - [ ] 输出 `compute_plan.json`（shots[] 含 fps/resolution/priority/gpu_tier）
  - [ ] 受当前集群资源约束
  - [ ] 支持动态重分配（worker 节点变化时）

### SKILL 20: Shot DSL Compiler & Prompt Backend
- **规格文档**: `SKILL_20_SHOT_DSL_COMPILER_PROMPT_BACKEND.md`
- **Service**: `code/apps/ainern2d-composer/app/services/skills/skill_20_dsl_compiler.py`
- **DTO**: `code/shared/ainern2d_shared/schemas/skills/skill_20.py`
- **依赖模块**: `ffmpeg/commands.py`, `timeline/assembler.py`
- **DB 表**: `compiled_prompts`, `compiler_traces`
- **状态机**: `INIT → VALIDATING_DSL → ENRICHING_CONTEXT → COMPILING → MULTI_CANDIDATE → EXPORTING_TRACE → COMPILED_READY | FAILED`
- **输入事件**: `skill.10.completed` + `skill.15.completed` + `skill.19.completed`
- **输出事件**: `skill.20.completed` → 触发 Worker-Video/Worker-LLM 实际执行
- **Definition of Done**:
  - [ ] 输出 `compiled_prompt_bundle.json` + `compiler_trace_report.json`
  - [ ] 支持多后端编译（ComfyUI / SDXL / Flux）
  - [ ] 支持多候选生成（A/B 场景）

---

## 3. SKILL 执行流水线（DAG 依赖关系）

```
task.submitted
    │
    ▼
 [SKILL 01] Story Ingestion
    │
    ▼
 [SKILL 02] Language Context Router
    │
    ├──────────────────┐
    ▼                  ▼
 [SKILL 03]         [SKILL 04]
 Scene/Shot Plan    Entity Extraction
    │                  │
    ├─────┐            │
    ▼     ▼            ▼
 [SKILL 05]  ┌──→ [SKILL 07] Canonicalization ←─┘
 Audio Plan  │        │
    │        │        ▼
    ▼        │   [SKILL 08] Asset Matcher
 Worker-Audio│        │
    │        │        ├──────────┐
    ▼        │        ▼          ▼
 [SKILL 06]  │   [SKILL 09]  [SKILL 10]
 Audio       │   Visual Plan  Prompt Plan
 Timeline    │        │          │
    │        │        ▼          ▼
    └────────┘   [SKILL 20] DSL Compiler
                      │
                      ▼
                 Worker-Video / Worker-LLM 执行
                      │
                      ▼
                 [SKILL 06 再次] 最终合成
                      │
                      ▼
                 Composer 输出
                      │
                      ▼
                 [SKILL 16] Critic Evaluation
                      │
                      ▼
                 [SKILL 13] Feedback Loop (可选)

並行支撑 SKILLs（不在主流水线中，按需触发）:
 [SKILL 11] RAG KB Manager      ← 用户/SKILL13 触发
 [SKILL 12] RAG Embedding       ← SKILL11 触发
 [SKILL 14] Persona Style Pack  ← 项目创建时
 [SKILL 15] Creative Control    ← 项目创建时
 [SKILL 17] Experiment A/B      ← 用户触发
 [SKILL 18] Failure Recovery    ← 任何 SKILL 失败时
 [SKILL 19] Compute Budgeter   ← SKILL03 完成后
```

---

## 4. AI Agent 接力规则

### 4.1 接手前必读
1. 本文档（了解全局进度）
2. `START_HERE_FOR_AGENTS.md`（强制阅读顺序）
3. 目标 SKILL 的规格文档（`SKILL_XX_*.md`）
4. `code/docs/architecture/agent-coding-framework-guideline.md`（代码模板）
5. `ainer_contracts.md`（DTO 契约）
6. `ainer_error_code.md`（错误码规范）

### 4.2 实现标准流程
```
1. 选取一个 NOT_STARTED 或 PARTIAL 的 SKILL
2. 读取该 SKILL 的规格文档（Definition of Done）
3. 创建/完善 DTO: shared/schemas/skills/skill_XX.py
4. 创建/完善 Service: services/skills/skill_XX_*.py
5. Service 必须实现 execute(input_dto, context) → output_dto
6. 更新本文档：状态 → SERVICE_READY / INTEGRATION_READY
7. 运行 py_compile 验证语法
8. 提交 git commit
```

### 4.3 代码规范检查清单
- [ ] Service 类继承 `BaseSkillService`
- [ ] `execute()` 方法签名：`(self, input: SkillXXInput, ctx: SkillContext) → SkillXXOutput`
- [ ] 所有 DB 操作通过 Repository 层
- [ ] 日志使用 `loguru`（不用 print/logging）
- [ ] 时间使用 `ainern2d_shared.utils.time.utcnow()`
- [ ] 重试使用 `ainern2d_shared.utils.retry.retry_with_backoff`
- [ ] 错误码符合 `ainer_error_code.md`
- [ ] 幂等性检查（idempotency_key）
- [ ] 状态机转换记录到 `workflow_events`

### 4.4 更新本文档规范
修改完代码后，**必须**更新第 1 节总览表中对应 SKILL 的：
- `状态` 列 → 新状态
- `上次更新` 列 → 当前日期
- `更新者` 列 → AI 名称或 Agent ID

---

## 5. 框架基础设施状态

| 组件 | 状态 | 路径 |
|------|------|------|
| ORM 模型 (57 表) | ✅ 完成 | `shared/ainer_db_models/` |
| Alembic 基线迁移 | ✅ 完成 | `apps/alembic/versions/6f66885e0588_init_baseline.py` |
| Pydantic 基础 DTO | ✅ 完成 | `shared/schemas/` (8 文件) |
| RabbitMQ 队列 | ✅ 完成 | `shared/queue/` (3 文件) |
| 工具库 | ✅ 完成 | `shared/utils/` (3 文件) |
| 遥测 | ✅ 完成 | `shared/telemetry/` (3 文件) |
| 配置 | ✅ 完成 | `shared/config/` (2 文件) |
| 存储 | ✅ 完成 | `shared/storage/` (2 文件) |
| DB Session + Repos | ✅ 完成 | `shared/db/` (4 文件) |
| SKILL DTO schemas | 🔄 待创建 | `shared/schemas/skills/` |
| SKILL Service 层 | 🔄 待创建 | `apps/*/app/services/skills/` |
| SKILL 注册表 | 🔄 待创建 | `apps/ainern2d-studio-api/app/services/skill_registry.py` |
| BaseSkillService | 🔄 待创建 | `shared/services/base_skill.py` |

---

## 6. 变更日志

| 日期 | 操作 | 影响 SKILL | 更新者 |
|------|------|-----------|--------|
| 2026-02-26 | 初始创建文档，标记所有 SKILL 为 PARTIAL | ALL | Copilot |
| 2026-02-26 | 完成 modules/ 层所有 66 个空文件实现 | ALL | Copilot |
| 2026-02-26 | SKILL 03 execute() 全量实现：5步状态机，场景切分+镜头规划+时长估算+hints导出，DTO 完整 | 03 | Copilot |
| 2026-02-26 | SKILL 04 execute() 全量实现：5步状态机，正则实体抽取+结构化+alias去重+scene/shot关联，DTO 完整 | 04 | Copilot |
