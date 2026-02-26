# Ideal DB Model Blueprint（01~22 闭环）

## 1. 目标
- 面向新项目理想态，不做历史兼容约束。
- 以 `run / job / stage / event / artifact` 作为唯一主运行对象语义。
- 覆盖 01~22 全链路：输入、编排、执行、合成、观测、RAG 进化、治理增强。

## 2. 核心域模型分层
- 身份域：`tenants/users/projects/*members/service_accounts`
- 内容域：`novels/chapters/scenes/shots/dialogues/prompt_plans/timeline_segments/artifacts`
- 编排执行域：`execution_requests/render_runs/jobs/job_attempts/job_dependencies/workflow_events/run_stage_transitions/run_checkpoints/run_patch_records/compensation_records/dlq_events`
- 知识域：`entities/entity_aliases/entity_canonicalizations/cultural_bindings/relationships/story_events/entity_states/asset_candidates`
- 路由计费域：`model_providers/model_profiles/route_decisions/cost_ledgers`
- RAG 进化域：`rag_collections/kb_versions/rag_documents/rag_embeddings/feedback_events/kb_proposals/rag_eval_reports/kb_rollouts`
- 治理增强域（14~22）：`persona_packs/persona_pack_versions/creative_policy_stacks/shot_compute_budgets/shot_dsl_compilations/critic_evaluations/recovery_policies/recovery_executions/experiment_runs/experiment_arms/experiment_observations/entity_instance_links/entity_continuity_profiles/entity_preview_variants/character_voice_bindings/persona_dataset_bindings/persona_index_bindings/persona_lineage_edges/persona_runtime_manifests`

## 3. 闭环主链映射
1) `execution_requests` 创建请求
2) `render_runs` 建立运行上下文
3) `jobs + job_dependencies` 驱动执行 DAG
4) `workflow_events + run_stage_transitions` 记录状态机推进
5) `prompt_plans/timeline_segments/artifacts` 汇聚内容与产物
6) `critic_evaluations + recovery_executions` 质量门与降级策略
7) `feedback_events -> kb_proposals -> rag_eval_reports -> kb_rollouts` 完成 RAG 进化回路
8) `experiment_*` 形成策略优化飞轮

## 4. 强制约束
- 所有共享模型统一携带：`tenant_id/project_id/trace_id/correlation_id/idempotency_key/error_code/version/created_at/updated_at/deleted_at`。
- 运行态事件必须落 `workflow_events`，并具备 `event_version/producer/occurred_at`。
- 执行成功/失败以 `job.succeeded/job.failed` 语义为准，`worker.*.completed` 仅作明细追踪。
