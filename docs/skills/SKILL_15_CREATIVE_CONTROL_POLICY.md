# 15_CREATIVE_CONTROL_POLICY.md
# Creative Control Policy（创作控制策略栈 Skill 模板｜中文版）

## 0. 文档定位
本 Skill 定义工业级创作系统的“控制栈”：
- 硬约束（不可违反）
- 软约束（尽量满足）
- 探索层（允许变体）
- 冲突解决策略

用于防止系统在引入多 Persona、多 RAG、多模型后“风格发散、质量失控”。

---

## 术语对齐声明（固定模板）
- 本文统一运行对象命名：`run / job / stage / event / artifact`。
- `run`：一次端到端业务运行；`job`：run 内原子执行单元；`stage`：run 阶段状态。
- `event`：跨模块事实消息，统一采用 `EventEnvelope`；`artifact`：可回溯产物元数据。
- `worker.*.completed` 为执行明细事件，不替代 `job.succeeded / job.failed` 主状态事件。
- `step` 仅表示内部步骤序号，不作为运行态主对象或事件前缀。
- 必带治理字段：`tenant_id / project_id / trace_id / correlation_id / idempotency_key / schema_version`。

## 1. Workflow Goal（目标）
把来自多个模块的约束统一到一个策略栈中：
- `07` 文化绑定约束
- `06` 音频时间线与时长约束
- `14` Persona 风格偏置
- 项目预算 / 算力预算 / 时长预算
- 安全与合规约束

输出 `creative_control_stack.json`，供：
- `09_VISUAL_RENDER_PLANNER`
- `10_PROMPT_PLANNER`
- `19_COMPUTE_AWARE_SHOT_BUDGETER`
- `18_FAILURE_RECOVERY_DEGRADATION_POLICY`

---

## 2. Inputs（输入）
### 2.1 必需输入
- `timeline_final.json`（来自 06）
- `audio_event_manifest.json`（来自 06）
- `07` 的 culture constraints（或其导出）
- `14` resolved persona profile（可选但强烈建议）
- 项目级约束（时长/预算/SLA）

### 2.2 可选输入
- 用户硬性要求（必须出现/禁止出现）
- 平台合规策略
- `19` compute budget suggestion（回流）
- feature_flags:
  - enable_policy_conflict_scan
  - enable_exploration_band
  - enable_persona_soft_constraints

---

## 3. Outputs（输出）
- `creative_control_stack.json`
- `constraint_conflict_report.json`（如有冲突）

### 3.1 结构分层（必须）
1. `hard_constraints`
2. `soft_constraints`
3. `exploration_policy`
4. `conflict_resolution_policy`

---

## 4. Constraint Sources（约束来源）
- **Hard Constraints（硬约束）**
  - 音频最终时长 / 时间锚点（06）
  - 文化绑定不可违背项（07）
  - 连续性关键项（来自 16/资产一致性系统）
  - 算力上限 / SLA上限
  - 安全合规

- **Soft Constraints（软约束）**
  - Persona Style DNA（14）
  - 风格偏好（导演/摄影/灯光）
  - 用户审美偏好
  - 参考作品风格方向

- **Exploration Policy（探索层）**
  - 候选数量
  - 随机度区间
  - 可变动的镜头参数范围
  - 哪些 shot 允许实验、哪些必须稳定

---

## 5. Branching Logic（分支流程与判断）

### [CC1] Collect Constraints（收集约束）
#### Actions
1. 收集 06/07/14/项目预算的约束
2. 标注来源和优先级
3. 转换为统一格式
#### Output
- raw constraints set

---

### [CC2] Build Control Stack（构建控制栈）
#### Actions
1. 将约束分层到 hard / soft / exploration
2. 将 persona 偏好映射到 soft constraints
3. 生成 exploration band（比如可允许 2~4 候选）
#### Output
- `creative_control_stack.json`

---

### [CC3] Conflict Detection（冲突检测）
#### Actions
1. 检查 hard-hard 冲突（必须阻断）
2. 检查 hard-soft 冲突（hard 优先）
3. 检查 soft-soft 冲突（按 persona / project weight 解决）
4. 输出 conflict report
#### Output
- `constraint_conflict_report.json`

---

### [CC4] Export Runtime Policy（导出运行时策略）
#### Actions
1. 给 `09/10/19` 输出可执行策略字段
2. 标记不可突破边界
3. 标记允许探索的段落/镜头
#### Output
- runtime policy export

---

## 6. Output Contract（输出契约示例）
```json
{
  "version": "1.0",
  "status": "policy_ready",
  "hard_constraints": {
    "final_duration_ms": 47200,
    "culture_binding": {
      "must_follow_signage_language": "zh",
      "forbid_modern_electric_props": true
    },
    "sla_budget": {
      "max_gpu_minutes": 38,
      "preview_deadline_sec": 600
    }
  },
  "soft_constraints": {
    "persona_id": "director_xiaoli",
    "style_dna": {
      "cut_density": 0.85,
      "impact_alignment_priority": 0.93
    }
  },
  "exploration_policy": {
    "candidate_generation": {
      "enabled": true,
      "default_candidates_per_key_shot": 3
    },
    "allowed_variation_fields": ["camera_movement", "shot_duration_micro_variation", "lighting_intensity"],
    "stable_shots": ["S01", "S02"]
  },
  "conflict_resolution_policy": {
    "hard_over_soft": true,
    "soft_tie_breaker": "persona_weight_then_project_default"
  }
}
```

---

## 7. State Machine（状态机）
States:
- INIT
- COLLECTING_CONSTRAINTS
- BUILDING_STACK
- DETECTING_CONFLICTS
- EXPORTING_RUNTIME_POLICY
- POLICY_READY
- FAILED

---

## 8. Definition of Done（完成标准）
- [ ] 约束已按 hard/soft/exploration 分层
- [ ] 冲突已检测并出报告
- [ ] 输出可被 09/10/19 直接消费的 runtime policy
