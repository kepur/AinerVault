# 16_CRITIC_EVALUATION_SUITE.md
# Critic Evaluation Suite（多评审智能体评测套件 Skill 模板｜中文版）

## 0. 文档定位
本 Skill 定义“生成后质检与艺术评审”机制：
- 多 Critic Agent 对生成结果进行结构化评分
- 定位问题 shot / scene
- 给出修复建议
- 决定自动重试、降级、人工审核

该模块是工业级质量保证层，连接：
- 生成结果（图片/视频/音频/时间线）
- `18_FAILURE_RECOVERY_DEGRADATION_POLICY`
- `13_FEEDBACK_EVOLUTION_LOOP`
- `17_AB_TEST`（评测打分）

---

## 术语对齐声明（固定模板）
- 本文统一运行对象命名：`run / job / stage / event / artifact`。
- `run`：一次端到端业务运行；`job`：run 内原子执行单元；`stage`：run 阶段状态。
- `event`：跨模块事实消息，统一采用 `EventEnvelope`；`artifact`：可回溯产物元数据。
- `worker.*.completed` 为执行明细事件，不替代 `job.succeeded / job.failed` 主状态事件。
- `step` 仅表示内部步骤序号，不作为运行态主对象或事件前缀。
- 必带治理字段：`tenant_id / project_id / trace_id / correlation_id / idempotency_key / schema_version`。

## 1. Workflow Goal（目标）
提供结构化评审结果：
- 多维评分（连续性/运镜/灯光/美术/音画同步/节奏/文化）
- 严重级别（fatal/major/minor）
- 问题定位（scene_id/shot_id/时间范围）
- 修复建议（可自动/需人工）
- 总体放行决策（pass / retry / degrade / manual_review）

---

## 2. Inputs（输入）
### 2.1 必需输入
- 生成结果引用（视频/图像/音频）
- `timeline_final.json`（06）
- `audio_event_manifest.json`（06）
- `shot_plan.json`（03）
- `creative_control_stack.json`（15）

### 2.2 可选输入
- `resolved_persona_profile.json`（14）
- `07` 文化约束摘要
- `10` prompt plan（用于 traceability critic）
- `20` shot dsl（如存在）
- feature_flags:
  - enable_visual_critic
  - enable_audio_visual_sync_critic
  - enable_prompt_traceability_critic
  - enable_auto_fix_suggestions

---

## 3. Critic Agents（建议评审智能体）
- Continuity Critic（连续性）
- Cinematography Critic（摄影/运镜）
- Lighting Critic（灯光）
- Art Style Consistency Critic（美术风格一致性）
- Audio-Visual Sync Critic（音画同步）
- Pacing Critic（节奏）
- Cultural Accuracy Critic（文化准确性）
- Prompt Traceability Critic（提示词偏航/策略偏离）

---

## 4. Outputs（输出）
- `critic_evaluation_report.json`
- `critic_fix_queue.json`（可选，给 18/修复模块）

### 4.1 必需字段
- overall decision
- per_critic scores
- issues[]
- severity
- auto_fix_recommendations
- human_review_required

---

## 5. Branching Logic（分支流程与判断）

### [CR1] Precheck（预检查）
#### Actions
1. 检查结果产物是否齐全
2. 检查引用与时间线是否一致
3. 选择启用的 critics（根据 feature_flags 和任务类型）
#### Output
- critic plan

---

### [CR2] Run Critics（执行评审）
#### Actions
1. 并行运行各 Critic（可异步）
2. 每个 Critic 输出结构化结果：
   - score
   - issue list
   - severity
   - evidence refs（scene/shot/time）
3. 聚合分数
#### Output
- raw critic outputs

---

### [CR3] Aggregate Decision（聚合决策）
#### Actions
1. 根据 fatal/major/minor 规则做放行判断
2. 若 fatal：进入 retry/degrade/manual_review
3. 若 major：可自动修复或局部重试
4. 若 minor：记录并放行（可选）
#### Output
- overall decision

---

### [CR4] Build Fix Queue（构建修复队列）
#### Actions
1. 将可自动修复问题转换为 fix tasks
2. 标记修复类型：
   - prompt_patch
   - re-render-shot
   - re-time-sfx
   - downgrade-shot
   - manual-review
3. 输出给 18
#### Output
- `critic_fix_queue.json`

---

### [CR5] Feedback & Evolution Hooks（反馈与进化挂钩）
#### Actions
1. 将 recurring issue 写入统计（供 13）
2. 将评分结果写入实验记录（供 17）
3. 对人格包评估差异（供 14/17）
#### Output
- metrics hooks

---

## 6. Output Contract（示例）
```json
{
  "version": "1.0",
  "status": "evaluation_complete",
  "overall_decision": "retry_partial",
  "summary_scores": {
    "continuity": 0.81,
    "cinematography": 0.67,
    "lighting": 0.74,
    "audio_visual_sync": 0.88,
    "pacing": 0.71,
    "cultural_accuracy": 0.92
  },
  "issues": [
    {
      "issue_id": "CI_001",
      "critic": "cinematography",
      "severity": "major",
      "scene_id": "SC05",
      "shot_id": "S27",
      "time_range_ms": [22100, 23200],
      "category": "motion_readability",
      "message": "击打点动作可读性不足，镜头停留过长。",
      "auto_fix_possible": true,
      "recommended_fix_type": "re-render-shot"
    }
  ],
  "auto_fix_recommendations": [
    {
      "fix_id": "FIX_001",
      "target_shot_id": "S27",
      "action": "increase_microshot_density_and_align_impact_peaks"
    }
  ],
  "human_review_required": false
}
```

---

## 7. State Machine（状态机）
States:
- INIT
- PRECHECKING
- RUNNING_CRITICS
- AGGREGATING_DECISION
- BUILDING_FIX_QUEUE
- EXPORTING_HOOKS
- COMPLETED
- FAILED

---

## 8. Definition of Done（完成标准）
- [ ] 多 Critic 可并行执行并输出结构化评分
- [ ] 生成 overall decision（pass/retry/degrade/manual_review）
- [ ] 生成 fix queue（如启用）
- [ ] 结果可回流 13 与 17
