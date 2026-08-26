# 14_PERSONA_STYLE_PACK_MANAGER.md
# Persona Style Pack Manager（导演/摄影等人格风格包管理 Skill 模板｜中文版）

## 0. 文档定位
本 Skill 定义 AinerN2D 的“人格化风格包（Persona Style Pack）”管理能力，
用于实现你说的：`导演小李 / 导演小王` 等不同专业人格携带各自 RAG + 风格参数执行，产生可控差异化风格效果。

该模块负责：
- Persona（人格）定义、继承、版本化
- Style DNA（结构化风格参数轴）
- Persona 与 Role Pack / RAG Recipe 的绑定
- Persona 的启用、对比、A/B 测试准备

> 本模块不直接生成镜头，不直接执行渲染；它输出“可被调用的风格人格配置”。

---

## 术语对齐声明（固定模板）
- 本文统一运行对象命名：`run / job / stage / event / artifact`。
- `run`：一次端到端业务运行；`job`：run 内原子执行单元；`stage`：run 阶段状态。
- `event`：跨模块事实消息，统一采用 `EventEnvelope`；`artifact`：可回溯产物元数据。
- `worker.*.completed` 为执行明细事件，不替代 `job.succeeded / job.failed` 主状态事件。
- `step` 仅表示内部步骤序号，不作为运行态主对象或事件前缀。
- 必带治理字段：`tenant_id / project_id / trace_id / correlation_id / idempotency_key / schema_version`。

## 1. Workflow Goal（目标）
实现以下能力：
1. 定义多个人格风格包（导演小李/小王…）
2. 支持继承关系（公共规则 → 流派 → 人格）
3. 为人格配置 Style DNA（数值偏好轴）
4. 绑定对应 RAG Recipe / Critic 阈值 / Prompt偏置
5. 版本化与回滚（persona_version）
6. 在运行时可被 `10_PROMPT_PLANNER`、`15_CREATIVE_CONTROL_POLICY`、`17_AB_TEST` 调用

---

## 2. Concepts（核心概念）

### 2.1 Persona Pack
一个可执行的风格人格包，包含：
- 基础角色（director / cinematographer / editor ...）
- 继承链
- Style DNA
- RAG Recipe Overrides
- Policy Overrides
- Critic Threshold Overrides（可选）

### 2.2 Style DNA（结构化风格轴）
用于稳定表达风格差异（不能只依赖文本RAG），例如：
- cut_density（切镜密度）
- motion_aggressiveness（镜头运动激进度）
- dialogue_patience（对白耐心）
- atmospheric_hold_preference（氛围停留偏好）
- impact_alignment_priority（击打点对齐优先级）
- symmetry_preference（构图对称偏好）

### 2.3 Persona Version
人格包版本，供 run 追溯：
- `persona_pack_id`
- `persona_version`

---

## 3. Inputs（输入）
### 3.1 前端输入（用户/策划）
- 新建/编辑 Persona Pack
- 选择 base role（director/cinematographer）
- 选择继承父包（可多个）
- 设置 Style DNA 数值轴
- 绑定 RAG Recipe Override / Policy Override
- 发布版本 / 回滚

### 3.2 系统输入（可选）
- `11_RAG_KB_MANAGER` 当前可用 role packs / kb_version
- `15_CREATIVE_CONTROL_POLICY` 可覆盖字段列表
- `17_EXPERIMENT_AB_TEST_ORCHESTRATOR` 实验结果反馈
- feature_flags:
  - enable_persona_inheritance
  - enable_style_dna
  - enable_persona_ab_compare

---

## 4. Outputs（输出）
### 4.1 主输出文件
- `persona_pack_manifest.json`

### 4.2 运行时输出（供下游调用）
- `resolved_persona_profile.json`（含继承展开结果）
- `persona_style_dna.json`
- `persona_rag_recipe_override.json`
- `persona_policy_override.json`

---

## 5. Data Contract（数据契约示例）

### 5.1 Persona Pack（示例）
```json
{
  "persona_pack_id": "director_xiaoli",
  "persona_version": "1.2.0",
  "base_role": "director",
  "inherits_from": ["director_common_v1", "wuxia_action_school_v2"],
  "display_name": "导演小李",
  "status": "active",
  "style_dna": {
    "cut_density": 0.85,
    "motion_aggressiveness": 0.82,
    "dialogue_patience": 0.32,
    "atmospheric_hold_preference": 0.24,
    "impact_alignment_priority": 0.93,
    "spatial_readability_priority": 0.76
  },
  "rag_recipe_override": {
    "director_top_k": 4,
    "cinematographer_top_k": 8,
    "editor_top_k": 6
  },
  "policy_override": {
    "prefer_microshots_in_high_motion": true,
    "max_dialogue_hold_ms_in_action": 900
  },
  "critic_threshold_override": {
    "motion_readability_min": 0.78
  }
}
```

### 5.2 Resolved Persona（继承展开后）
```json
{
  "persona_pack_id": "director_xiaoli",
  "persona_version": "1.2.0",
  "resolved_from": ["director_common_v1", "wuxia_action_school_v2", "director_xiaoli@1.2.0"],
  "base_role": "director",
  "resolved_style_dna": {},
  "resolved_policy": {},
  "resolved_rag_recipe_override": {}
}
```

---

## 6. Branching Logic（分支流程与判断）

### [PS1] Create / Edit Persona（创建/编辑人格）
#### Trigger
用户保存 Persona
#### Actions
1. 校验 base_role、继承链、数值轴范围（0~1）
2. 校验 override 字段是否合法
3. 标记 `persona_status = draft` 或 `stale_eval`
#### Output
- persona draft 保存成功

---

### [PS2] Resolve Inheritance（继承展开）
#### Trigger
预览/发布/运行时使用 Persona
#### Actions
1. 按继承顺序加载父包（公共 -> 流派 -> 人格）
2. 合并 Style DNA（子覆盖父）
3. 合并 policy/rag overrides
4. 检测冲突（例如相互矛盾阈值）
#### Output
- `resolved_persona_profile.json`
- conflicts（如有）

---

### [PS3] Preview Style Effect（风格预览，可选）
#### Trigger
用户在前端做 Persona 对比
#### Actions
1. 给定同一 shot DSL / prompt seed
2. 用不同 persona 只跑 planner/prompt preview（可不真正渲染）
3. 展示差异（镜头切分倾向、prompt差异、帧率建议差异）
#### Output
- persona compare preview

---

### [PS4] Publish Persona Version（发布人格版本）
#### Trigger
用户点击发布
#### Actions
1. 生成 persona_version
2. 冻结 manifest
3. 输出 `persona_pack_manifest.json`
4. 可触发 17 的基准评测（建议）
#### Output
- 发布成功 + persona_version

---

## 7. State Machine（状态机）
States:
- INIT
- EDITING_PERSONA
- RESOLVING_INHERITANCE
- PREVIEWING_STYLE
- READY_TO_PUBLISH
- PUBLISHING
- ACTIVE
- FAILED

---

## 8. Integration Points（接入点）
- `10_PROMPT_PLANNER`: 注入 persona_style_dna + rag_recipe_override
- `15_CREATIVE_CONTROL_POLICY`: 注入 policy_override（软约束层）
- `17_AB_TEST`: 人格对比实验
- `16_CRITIC`: 使用 persona critic 阈值做评测解释

---

## 9. Definition of Done（完成标准）
- [ ] 支持 Persona Pack 创建/编辑/继承/版本化
- [ ] 支持 Style DNA 与 RAG/Policy Override
- [ ] 支持 resolved persona 输出
- [ ] 支持被 10/15/17 调用
