# 18_FAILURE_RECOVERY_DEGRADATION_POLICY.md
# Failure Recovery & Degradation Policy（失败恢复与降级策略 Skill 模板｜中文版）

## 0. 文档定位
本 Skill 定义工业级流水线在失败场景下的恢复策略：
- 重试策略
- 降级策略
- 部分成功（partial success）状态
- 阻断条件（blocking failures）
- 修复任务接管（来自 16 Critic）

目的：让系统在真实生产中“尽可能产出可用结果”，而不是一处失败全盘崩溃。

---

## 术语对齐声明（固定模板）
- 本文统一运行对象命名：`run / job / stage / event / artifact`。
- `run`：一次端到端业务运行；`job`：run 内原子执行单元；`stage`：run 阶段状态。
- `event`：跨模块事实消息，统一采用 `EventEnvelope`；`artifact`：可回溯产物元数据。
- `worker.*.completed` 为执行明细事件，不替代 `job.succeeded / job.failed` 主状态事件。
- `step` 仅表示内部步骤序号，不作为运行态主对象或事件前缀。
- 必带治理字段：`tenant_id / project_id / trace_id / correlation_id / idempotency_key / schema_version`。

## 1. Workflow Goal（目标）
根据失败类型与任务阶段，输出：
- 恢复动作（retry/switch_backend/degrade/skip/manual_review）
- 恢复次数与退避策略
- 产出状态（success / success_with_degradation / partial_review_required / failed_blocking）
- 修复队列或人工审核队列

---

## 2. Inputs（输入）
### 2.1 必需输入
- 当前 stage/module（03/05/06/09/10/...）
- 失败事件（error_code / timeout / malformed_output / critic_issue）
- `creative_control_stack.json`（15）
- `compute_budget_policy`（19，可选）
- `critic_fix_queue.json`（16，可选）

### 2.2 可选输入
- backend capability matrix
- retry history
- asset availability
- feature_flags:
  - enable_partial_success
  - enable_backend_fallback
  - enable_degradation_ladder

---

## 3. Outputs（输出）
- `failure_recovery_decision.json`
- `degradation_trace.json`
- `manual_review_queue_item.json`（如需要）

---

## 4. Failure Classes（失败分类建议）
- infra_timeout
- model_timeout
- malformed_json
- invalid_timeline_alignment
- missing_audio_asset
- image_generation_failed
- i2v_generation_failed
- critic_major_issue
- critic_fatal_issue
- rag_conflict_unresolved
- budget_exceeded

---

## 5. Degradation Ladder（降级阶梯示例）
以视觉镜头生成为例：
1. 同参数重试
2. 换后端/换模型
3. 缩短时长
4. 降低帧率
5. 降低分辨率
6. 拆成更短微镜头重试
7. 静态图 + 动效（Ken Burns/轻微位移）
8. placeholder + 标记 manual review（最后兜底）

---

## 6. Branching Logic（分支流程与判断）

### [FR1] Classify Failure（失败分类）
#### Actions
1. 解析错误类型与来源模块
2. 检查是否可恢复（recoverable）
3. 检查是否触发 blocking 条件（例如 hard constraints 无法满足）
#### Output
- failure class + recoverability

---

### [FR2] Select Recovery Policy（选择恢复策略）
#### Actions
1. 查询失败策略矩阵（按 stage + error class）
2. 考虑预算与SLA限制（15/19）
3. 输出动作：
   - retry_same
   - retry_with_patch
   - switch_backend
   - degrade
   - skip_optional
   - manual_review
   - fail_blocking
#### Output
- recovery decision

---

### [FR3] Apply Degradation Ladder（应用降级阶梯）
#### Trigger
recovery decision = degrade
#### Actions
1. 按预定义阶梯逐级尝试
2. 每次记录 degrade_step 与效果
3. 达到可接受阈值则停止
4. 超限则转 manual review / fail
#### Output
- `degradation_trace.json`

---

### [FR4] Produce Final Status（产出最终状态）
#### Actions
1. 归类最终状态：
   - success
   - success_with_degradation
   - partial_review_required
   - failed_blocking
2. 构建审计记录，供 17/13 分析
#### Output
- `failure_recovery_decision.json`

---

## 7. Output Contract（示例）
```json
{
  "version": "1.0",
  "status": "success_with_degradation",
  "stage": "09_VISUAL_RENDER_PLANNER_EXEC",
  "failure_class": "i2v_generation_failed",
  "actions_taken": [
    {"step": 1, "action": "retry_same", "result": "failed"},
    {"step": 2, "action": "switch_backend", "result": "failed"},
    {"step": 3, "action": "degrade_fps_24_to_12", "result": "success"}
  ],
  "degradation_applied": true,
  "degradation_level": "medium",
  "hard_constraints_preserved": true,
  "manual_review_required": false
}
```

---

## 8. State Machine（状态机）
States:
- INIT
- CLASSIFYING_FAILURE
- SELECTING_POLICY
- APPLYING_RECOVERY
- APPLYING_DEGRADATION
- FINALIZING_STATUS
- COMPLETED
- FAILED

---

## 9. Definition of Done（完成标准）
- [ ] 失败可被分类并匹配策略
- [ ] 支持恢复与降级阶梯
- [ ] 能输出 success_with_degradation / partial_review_required 等工业级状态
- [ ] 结果可回流 13/17
