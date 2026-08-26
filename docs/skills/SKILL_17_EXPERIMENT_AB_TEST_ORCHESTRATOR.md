# 17_EXPERIMENT_AB_TEST_ORCHESTRATOR.md
# Experiment / A-B Test Orchestrator（实验与A/B编排 Skill 模板｜中文版）

## 0. 文档定位
本 Skill 用于将系统优化从“玄学调参”升级为“可追溯实验”：
- 对比 persona / RAG recipe / prompt policy / compute policy
- 批量运行基准样例
- 接入 Critic 打分与用户评分
- 选择更优配置并推动默认策略更新

---

## 术语对齐声明（固定模板）
- 本文统一运行对象命名：`run / job / stage / event / artifact`。
- `run`：一次端到端业务运行；`job`：run 内原子执行单元；`stage`：run 阶段状态。
- `event`：跨模块事实消息，统一采用 `EventEnvelope`；`artifact`：可回溯产物元数据。
- `worker.*.completed` 为执行明细事件，不替代 `job.succeeded / job.failed` 主状态事件。
- `step` 仅表示内部步骤序号，不作为运行态主对象或事件前缀。
- 必带治理字段：`tenant_id / project_id / trace_id / correlation_id / idempotency_key / schema_version`。

## 1. Workflow Goal（目标）
实现实验编排：
1. 定义实验变量（persona / recipe / policy / model）
2. 指定基准样例集（benchmark scenes）
3. 执行对照试验（A/B/n）
4. 收集 `16` Critic 结果 + 用户评分（可选）
5. 统计与排名
6. 输出推荐（promote / keep / rollback / further_test）

---

## 2. Inputs（输入）
### 2.1 必需输入
- benchmark case set（固定样例）
- variants（A/B/n配置）
  - persona_version
  - kb_version
  - rag_recipe_version
  - prompt_policy_version
  - compute_policy_version
  - model backend/version（可选）
- success criteria（评价标准）

### 2.2 可选输入
- 用户评分数据（真实任务）
- 成本数据（GPU分钟、失败率、重试次数）
- `16` critic reports
- feature_flags:
  - enable_multi_variant
  - enable_cost_weighted_ranking
  - enable_auto_promote

---

## 3. Outputs（输出）
- `experiment_run_manifest.json`
- `experiment_result_report.json`
- `promotion_recommendation.json`

---

## 4. Experiment Dimensions（实验维度）
常见维度：
- Persona（14）
- RAG Recipe（10/11/12）
- Creative Control Policy（15）
- Compute Budget Policy（19）
- Prompt Compiler Strategy（20）
- 模型版本/后端

建议一次实验主变量不超过 1~2 个，避免归因混乱。

---

## 5. Branching Logic（分支流程与判断）

### [AB1] Define Experiment（定义实验）
#### Actions
1. 生成 experiment_id
2. 固定 benchmark 样例集与评价标准
3. 注册 variants（A/B/n）
4. 锁定版本号（persona/kb/recipe/policy）
#### Output
- `experiment_run_manifest.json`

---

### [AB2] Execute Variants（执行实验）
#### Actions
1. 对每个 benchmark case × variant 执行生成流程（可子集）
2. 记录运行时间、失败/重试、成本
3. 调用 16 做 Critic 评估
#### Output
- raw experiment logs

---

### [AB3] Aggregate Metrics（聚合指标）
#### Actions
1. 计算质量指标（critic scores）
2. 计算效率指标（latency/cost/retry_rate）
3. 计算稳定性指标（failure_rate/partial_success_rate）
4. 若有用户评分，合并为综合分
#### Output
- aggregated metrics

---

### [AB4] Rank & Recommend（排序与推荐）
#### Actions
1. 按目标函数排序（质量优先 / 成本质量平衡）
2. 输出推荐：
   - promote_to_default
   - keep_as_optional_persona
   - rollback
   - need_more_tests
3. 写入版本建议
#### Output
- `promotion_recommendation.json`

---

## 6. Output Contract（示例）
```json
{
  "version": "1.0",
  "experiment_id": "EXP_20260226_01",
  "status": "completed",
  "variants": [
    {"variant_id": "A", "persona": "director_xiaoli@1.2.0", "compute_policy": "CP_V1"},
    {"variant_id": "B", "persona": "director_xiaowang@1.0.0", "compute_policy": "CP_V1"}
  ],
  "metrics": {
    "A": {"quality_score": 0.82, "cost_score": 0.63, "retry_rate": 0.18},
    "B": {"quality_score": 0.76, "cost_score": 0.71, "retry_rate": 0.09}
  },
  "recommendation": {
    "decision": "keep_both",
    "default_for": {"high_motion_wuxia": "A", "dialogue_scene": "B"},
    "notes": "A 动作段更强，B 稳定性更好"
  }
}
```

---

## 7. State Machine（状态机）
States:
- INIT
- DEFINING_EXPERIMENT
- EXECUTING_VARIANTS
- AGGREGATING_METRICS
- RANKING
- EXPORTING_RECOMMENDATION
- COMPLETED
- FAILED

---

## 8. Definition of Done（完成标准）
- [ ] 能定义并锁定实验版本组合
- [ ] 能执行 benchmark × variant
- [ ] 能聚合质量/成本/稳定性指标
- [ ] 能输出推荐（promote/rollback/keep）
