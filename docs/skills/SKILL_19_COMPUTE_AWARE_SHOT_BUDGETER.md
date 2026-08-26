# 19_COMPUTE_AWARE_SHOT_BUDGETER.md
# Compute-Aware Shot Budgeter（镜头级算力预算器 Skill 模板｜中文版）

## 0. 文档定位
本 Skill 将“全局低/中/高负载档位”升级为“镜头级动态算力分配”：
- 根据动作强度、镜头类型、音频事件密度、GPU队列压力、SLA、预算
- 为每个 shot 分配帧率/分辨率/时长策略/后端优先级
- 输出 shot-level compute plan

该模块直接服务于：
- `09_VISUAL_RENDER_PLANNER`
- `18_FAILURE_RECOVERY_DEGRADATION_POLICY`

---

## 术语对齐声明（固定模板）
- 本文统一运行对象命名：`run / job / stage / event / artifact`。
- `run`：一次端到端业务运行；`job`：run 内原子执行单元；`stage`：run 阶段状态。
- `event`：跨模块事实消息，统一采用 `EventEnvelope`；`artifact`：可回溯产物元数据。
- `worker.*.completed` 为执行明细事件，不替代 `job.succeeded / job.failed` 主状态事件。
- `step` 仅表示内部步骤序号，不作为运行态主对象或事件前缀。
- 必带治理字段：`tenant_id / project_id / trace_id / correlation_id / idempotency_key / schema_version`。

## 1. Workflow Goal（目标）
实现每个镜头的动态算力规划，而不是只靠全局档位：
- 空镜、对白镜头 → 低负载
- 打斗、高动作镜头 → 高负载（但短时长）
- 在预算紧张时自动压缩次要镜头预算
- 在 SLA 紧时优先预览级方案

---

## 2. Inputs（输入）
### 2.1 必需输入
- `shot_plan.json`（03）
- `audio_event_manifest.json`（06）
- `creative_control_stack.json`（15）
- 全局负载档位（LOW/MEDIUM/HIGH）
- 当前资源状态（GPU queue / available VRAM / worker status）

### 2.2 可选输入
- 成本预算（项目剩余GPU分钟）
- 历史渲染统计（某类镜头耗时估计）
- 用户模式（preview / standard / final）
- feature_flags:
  - enable_shot_level_budget
  - enable_dynamic_fps
  - enable_backend_priority_assignment

---

## 3. Outputs（输出）
- `shot_compute_budget_plan.json`

### 3.1 每个 shot 规划字段（建议）
- render_priority
- target_fps
- target_resolution
- max_duration_ms (or segmentation policy)
- backend_preference
- retry_budget
- degrade_ladder_profile
- estimated_cost

---

## 4. Budgeting Factors（预算分配因素）
- 动作强度（来自 `audio_event_manifest`）
- shot_type（action/dialogue/establishing）
- criticality（来自 `shot_plan`）
- persona 风格偏好（14，经 15 软约束映射）
- SLA 与总预算（15）
- 当前资源压力（实时）

---

## 5. Branching Logic（分支流程与判断）

### [CB1] Analyze Shot Complexity（分析镜头复杂度）
#### Actions
1. 读取 shot_type、audio_event 密度、时长
2. 估计 motion complexity（low/medium/high）
3. 标记关键镜头 / 可降级镜头
#### Output
- complexity profile per shot

---

### [CB2] Allocate Budget（分配预算）
#### Actions
1. 根据全局档位设定 baseline（LOW=8, MEDIUM=12, HIGH=24）
2. 对高复杂度镜头上调预算（更高 fps/更短分段）
3. 对低复杂度镜头下调预算（降 fps/静态策略）
4. 保证总预算不超限（必要时压缩非关键镜头）
#### Output
- initial compute budget plan

---

### [CB3] Assign Backend & Retry Policy（分配后端与重试策略）
#### Actions
1. 为每个 shot 指定 backend preference（ComfyUI/Wan/Hunyuan 等）
2. 分配 retry_budget
3. 绑定降级阶梯 profile（给 18）
#### Output
- runtime-ready shot compute plan

---

### [CB4] SLA Rebalance（SLA重平衡）
#### Trigger
预览模式 / deadline 紧 / 资源拥堵
#### Actions
1. 优先关键镜头与首屏镜头
2. 次要镜头转低负载预览方案
3. 输出分阶段交付计划（preview first / final later）
#### Output
- staged delivery compute plan（可选）

---

## 6. Output Contract（示例）
```json
{
  "version": "1.0",
  "status": "compute_plan_ready",
  "global_profile": "HIGH",
  "budget_summary": {
    "max_gpu_minutes": 38,
    "estimated_gpu_minutes": 34.6
  },
  "shots": [
    {
      "shot_id": "S01",
      "complexity": "low",
      "render_priority": "normal",
      "target_fps": 8,
      "target_resolution": "720p",
      "backend_preference": ["comfyui_i2v"],
      "retry_budget": 1,
      "degrade_ladder_profile": "DL_LOW_MOTION_V1",
      "estimated_cost": {"gpu_sec": 18}
    },
    {
      "shot_id": "S27",
      "complexity": "high",
      "render_priority": "critical",
      "target_fps": 24,
      "segment_policy": "microshot_split_if_duration_gt_1000ms",
      "target_resolution": "720p",
      "backend_preference": ["wan_i2v", "comfyui_i2v"],
      "retry_budget": 3,
      "degrade_ladder_profile": "DL_HIGH_MOTION_V2",
      "estimated_cost": {"gpu_sec": 95}
    }
  ]
}
```

---

## 7. State Machine（状态机）
States:
- INIT
- ANALYZING_COMPLEXITY
- ALLOCATING_BUDGET
- ASSIGNING_BACKENDS
- REBALANCING_SLA
- COMPUTE_PLAN_READY
- FAILED

---

## 8. Definition of Done（完成标准）
- [ ] 为每个 shot 输出 compute plan（fps/分辨率/优先级/后端/重试预算）
- [ ] 总预算不超限或给出重平衡方案
- [ ] 结果可供 09 与 18 直接调用
