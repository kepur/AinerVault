# Skill Online Deployment（SKILL_01~20）

## 1. 目标
- 明确每个 Skill 的执行模块、运行节点（CPU/GPU）、依赖中间件、上线检查与回滚动作。

## 2. 环境模式

### 2.1 DEV-MOCK
- Mac 本地控制面 + 中间件。
- video/audio/lipsync 使用 mock worker。

### 2.2 DEV-REMOTE-GPU
- Mac 本地控制面 + 远端 GPU worker。
- 队列与对象存储建议走 VPN 内网。

### 2.3 PROD
- CPU 服务器：控制面+数据面。
- GPU 服务器：执行面。

## 3. Skill 部署矩阵

| Skill | 核心模块 | 运行节点 | 依赖 | 输入 | 输出 | 上线前检查 | 回滚动作 |
|---|---|---|---|---|---|---|---|
| SKILL_01 | gateway/ingestion | CPU | postgres,redis | raw story | normalized_story | 字段校验+幂等 | 回退到上版校验规则 |
| SKILL_02 | language router | CPU | postgres,rag | normalized_story | language_context_routing | culture/tag 过滤有效 | 回退默认 culture route |
| SKILL_03 | story planner | CPU | postgres,rabbitmq | normalized_story/context | shot_plan | shot 序号连续 | 回退上版 planner 模板 |
| SKILL_04 | entity extract | CPU/LLM | postgres | story+shot | entity_pack | entity 去重率 | 回退抽取策略版本 |
| SKILL_05 | audio asset plan | CPU | postgres,rag | shot_plan/entity | audio_plan | 轨道冲突检查 | 回退到基础音轨模板 |
| SKILL_06 | timeline composer | CPU | postgres,minio | audio results | timeline_final | 时序一致性通过 | 回退至 provisional timeline |
| SKILL_07 | cultural binding | CPU | rag,postgres | entity_pack | canonical_result | hard/soft constraints 完整 | 回退到默认文化包 |
| SKILL_08 | asset matcher | CPU | pgvector,minio | canonical_result | asset_match_result | 召回分数达阈值 | 回退旧匹配器阈值 |
| SKILL_09 | visual render plan | CPU | queue,rag | timeline_final | visual_render_plan | motion/degrade 策略有效 | 回退至 standard profile |
| SKILL_10 | prompt planner | CPU/LLM | rag,postgres | 07/08/09 | prompt_plan | 写入 kb_version/recipe_id | 回退到上版 recipe |
| SKILL_11 | kb manager | CPU | postgres,minio | item/edit/release | kb_release_manifest | 版本差异与审核通过 | 切回旧 kb_version |
| SKILL_12 | rag pipeline | CPU+GPU(可选) | pgvector,queue | release_manifest | index_build_report | recall/conflict 达标 | 回滚索引版本 |
| SKILL_13 | feedback evolution | CPU | postgres,queue | feedback events | proposal/release action | proposal 审核闭环 | 暂停自动入库，改人工审核 |
| SKILL_14 | persona style pack | CPU | postgres,rag | persona config | resolved_persona_profile | style_dna/override 合法 | 切回上版 persona |
| SKILL_15 | creative control policy | CPU | postgres,rag | 06/07/14 outputs | creative_control_stack | hard/soft/explore 分层完整 | 回退到默认 policy |
| SKILL_16 | critic evaluation suite | CPU+GPU(可选) | minio,postgres | render outputs | critic_report | critic 评分与门禁通过 | 降级为人工审核 |
| SKILL_17 | experiment orchestrator | CPU | postgres,queue | variants + benchmark | experiment_report | 实验统计完整可复现 | 停止自动推广 |
| SKILL_18 | failure recovery policy | CPU | queue,postgres | failure events | recovery_decision | 降级阶梯可执行 | 强制 manual_review |
| SKILL_19 | compute-aware budgeter | CPU | queue,metrics | 03/06/15 outputs | shot_compute_budget_plan | 总预算不超限 | 回退全局预算档位 |
| SKILL_20 | shot dsl compiler | CPU | rag,policy registry | shot_dsl + 10 outputs | compiled_prompt_bundle | traceability 字段完整 | 回退 baseline compiler |

## 4. 上线流水线（通用）
1. 预检查（配置、依赖、模型可达性）
2. 灰度发布（10%-30%-100%）
3. 验收（参照 `e2e-handoff-test-matrix.md`）
4. 观察窗口（30-60 分钟）
5. 失败触发回滚

## 5. 关键门禁
- 必须记录：`tenant_id/project_id/trace_id/correlation_id/idempotency_key/schema_version`。
- Prompt 相关链路必须记录：`kb_version_id`、`recipe_id`。
- 增强链路必须记录：`persona_version`、`creative_policy_version`、`compute_budget_policy_version`、`compiler_template_version`、`critic_suite_version`。
- 失败路径必须记录：`error_code`、`retryable`。
