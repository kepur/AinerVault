# 10_PROMPT_PLANNER.md
# Prompt Planner（提示词规划 Skill 模板｜中文版）

## 0. 文档定位
本 Skill 用于在“实体文化绑定（07）+ 素材匹配（08）+ 视觉渲染规划（09）”完成后，
为每个镜头（shot）或微镜头（micro-shot）生成可执行的提示词规划结果（Prompt Plan）。

该模块负责将以下信息进行结构化融合：
- 文化约束（culture constraints）
- 实体与素材锚点（asset anchors）
- 镜头目标与动作复杂度（shot goal / motion complexity）
- 渲染策略（frame budget / i2v_mode / quality priority）
- 模型能力与后端执行限制（backend capability / presets）

最终输出供下游模块使用：
- ComfyUI / I2V Executors
- 图像生成 Worker / 视频生成 Worker
- Consistency Checker
- Composer（用于记录提示词版本与可追溯性）

> 本模块输出“提示词计划（Prompt Plan）”，不是最终执行结果。

---

## 术语对齐声明（固定模板）
- 本文统一运行对象命名：`run / job / stage / event / artifact`。
- `run`：一次端到端业务运行；`job`：run 内原子执行单元；`stage`：run 阶段状态。
- `event`：跨模块事实消息，统一采用 `EventEnvelope`；`artifact`：可回溯产物元数据。
- `worker.*.completed` 为执行明细事件，不替代 `job.succeeded / job.failed` 主状态事件。
- `step` 仅表示内部步骤序号，不作为运行态主对象或事件前缀。
- 必带治理字段：`tenant_id / project_id / trace_id / correlation_id / idempotency_key / schema_version`。

## 1. Workflow Goal（目标）
为每个 shot / micro-shot 生成：
1. 分层提示词结构（Prompt Layers）
2. 模型类型适配版本（T2I / I2V / 首尾帧 / 多关键帧）
3. 负面约束（Negative Prompts / 禁忌项）
4. 控制参数建议（风格强度、一致性锚点、参考素材引用、质量参数）
5. 与 ComfyUI / 执行器的字段映射信息
6. 回退/降级提示词方案（当素材不足或后端不支持时）

---

## 2. Scope（范围）

### 包含
- 分层提示词规划（文化层、实体层、镜头层、动作层、质量层等）
- 正向提示词与负向约束生成
- 模型类型适配（T2I / I2V / start_end / start_mid_end / multi_keyframe）
- 素材锚点与提示词融合规则
- 风格一致性与角色一致性提示（prompt anchors）
- 与渲染策略（09）联动的参数映射
- 输出结构化 `prompt_plan.json`

### 不包含
- 实际模型推理执行
- 最终视频合成
- 素材检索（由 08 完成）
- 音频重规划（由音频流程完成）
- 低层工作流节点编排（由执行器或 ComfyUI preset mapping 完成）

---

## 3. Inputs（输入）

### 3.1 必需输入
- `entity_canonicalization_result.json`（来自 07）
  - `selected_culture_pack`
  - `culture_constraints`
  - `entity_variant_mapping[]`

- `asset_match_result.json`（来自 08）
  - `entity_asset_matches[]`
  - `asset_manifest`

- `visual_render_plan.json`（来自 09）
  - `shot_render_plans[]`
  - `microshot_render_plans[]`
  - `resource_strategy`

- `shot_plan.json`
  - 场景/镜头目标、镜头类型、叙事目的、角色出场信息

### 3.2 可选输入
- `story_context`
  - 章节摘要、段落语义、对白摘要、情绪曲线
- `character_consistency_profile`
  - 角色固定描述、禁忌变化、发型服饰锚点
- `style_mode`
  - 写实 / 动画 / 国潮 / 赛博 / 影视化 / 插画 等
- `model_target`
  - `t2i`, `i2v`, `video_model`, `hybrid`
- `backend_capability`
  - 支持的模型、LoRA、Control类型、最大上下文、提示词长度限制
- `comfyui_preset_catalog`
  - 预设映射规则（preset_id -> 期望字段）
- `quality_profile`
  - `preview` / `standard` / `final`
- `user_overrides`
  - 指定风格、禁止某些元素、指定角色形象、指定镜头语言等
- `feature_flags`
  - `enable_prompt_layer_export`
  - `enable_model_specific_variants`
  - `enable_negative_prompt_auto_expand`
  - `enable_prompt_fallback_variants`

---

## 4. Outputs（输出）

### 4.1 主输出文件
- `prompt_plan.json`

### 4.2 输出内容必须包含
1. `status`
2. `prompt_plan_summary`
3. `global_prompt_constraints`
4. `shot_prompt_plans[]`
5. `microshot_prompt_plans[]`（如有）
6. `model_variants[]`（按模型/模式适配）
7. `preset_mapping_hints`
8. `fallback_prompt_actions[]`
9. `warnings[]`
10. `review_required_items[]`

---

## 5. Core Concepts（核心概念）

### 5.1 Prompt Layers（提示词分层）
将提示词拆成多个语义层，避免大段混乱文本导致 AI 或后端执行不稳定。
推荐层级：
- Base Layer（基础画面层）
- Cultural Layer（文化语境层）
- Entity Layer（实体/角色/场景/道具层）
- Shot Layer（镜头语言层）
- Motion Layer（动作/节奏层）
- Lighting & Mood Layer（光影氛围层）
- Quality Layer（质量与细节层）
- Negative Constraint Layer（负面约束层）
- Consistency Anchor Layer（一致性锚点层）

### 5.2 Prompt Plan（提示词计划）
面向执行器的结构化提示词数据，不只是单个字符串，而是包含：
- 分层内容
- 拼接顺序
- 针对不同模型的变体版本
- 与 preset 的字段映射

### 5.3 Prompt Assembly（提示词组装）
根据模型目标和后端能力，把分层提示词组装成最终执行文本或字段集合。

---

## 6. Prompt Layer Architecture（提示词层架构）

### 6.1 推荐层级顺序（默认）
1. `base`
2. `cultural`
3. `entity`
4. `shot`
5. `motion`
6. `lighting_mood`
7. `quality`
8. `consistency_anchor`
9. `negative_constraints`（通常分开存，不并入正向字符串）

> 说明：不同模型可调整层级顺序，但必须记录在输出中。

### 6.2 各层职责（建议）

#### Base Layer（基础层）
定义基本场景目的与画面主语义，不涉及太多风格细节。
示例内容：
- “一个江湖客栈大堂中的对峙场景”
- “海边空镜，风雨氛围，远景建立镜头”

#### Cultural Layer（文化层）
来自 07 的 `selected_culture_pack + culture_constraints`，用于保证文化一致性。
示例内容：
- 中式武侠客栈木结构、灯笼照明、汉字招牌风格
- 避免现代霓虹、避免西式啤酒龙头吧台

#### Entity Layer（实体层）
来自 08 的素材锚点 + 变体映射，描述角色/场景/道具/服饰细节。
示例内容：
- 主角服饰、武器类型、桌椅材质、背景人群类型
- 引用角色一致性锚点、场景参考图、LoRA标签等

#### Shot Layer（镜头层）
来自 shot_plan / 09，描述镜头构图与拍法。
示例内容：
- 建立镜头 / 中景 / 特写
- 低机位 / 跟拍 / 侧向构图 / 强透视
- 画面主焦点与景别

#### Motion Layer（动作层）
来自 09 的动作复杂度、micro-shot 拆分、i2v模式建议。
示例内容：
- 快速连击、挥刀、闪避、冲撞
- 慢速风吹帘动、海浪起伏、雨幕飘动
- 与音频打击点对齐的动作强调（仅计划性表达）

#### Lighting & Mood Layer（光影氛围层）
描述光照、色温、气氛、情绪。
示例内容：
- 冷色雨夜、暖色灯笼火光、低照度高对比
- 压迫感、紧张感、史诗感、宁静感

#### Quality Layer（质量层）
根据 `quality_profile + visual_render_plan` 决定细节级别与清晰度倾向。
示例内容：
- 高细节、写实纹理、电影感、动作可读性优先
- 预览版可简化背景细节

#### Consistency Anchor Layer（一致性锚点层）
用于保证角色/场景跨镜头一致。
可包含：
- `character_anchor_id`
- `scene_anchor_id`
- 固定服饰关键描述
- 固定发型/配色/道具身份标记

#### Negative Constraint Layer（负面约束层）
防止文化错位、风格漂移、结构崩坏。
示例内容：
- 避免现代招牌、避免西式吧台、避免多余肢体、避免面部畸形
- 避免错误武器制式、避免时代错配道具

---

## 7. Prompt Generation Principles（提示词生成原则）

### 7.1 总原则
1. **先保证语义正确与文化一致，再追求华丽细节**
2. 提示词内容应服务于镜头目标（shot goal），不是堆砌美术词汇
3. 高动作镜头优先强调动作可读性与关键姿态，而非静态极致细节
4. 空镜/氛围镜头可提高环境与光影描述权重
5. 关键实体必须引用一致性锚点，减少跨镜头漂移
6. 输出结构化层而不是单段文本，便于调试与降级

### 7.2 约束原则
- 不把渲染帧预算写成最终视频 fps
- 不把素材匹配结果硬编码成不可替代的唯一描述（保留变体空间）
- 不跳过负面约束层（尤其文化/时代/人体结构）
- 信息不足时必须显式输出 warning/fallback

---

## 8. Model-Specific Prompt Variants（模型适配变体）

### 8.1 目标模式（示例）
- `T2I`（文生图）
- `I2V_START_END`（首尾帧图生视频）
- `I2V_START_MID_END`
- `I2V_MULTI_KEYFRAME`
- `VIDEO_TEXT_DRIVEN`（直接文生视频模型）
- `HYBRID`（T2I关键帧 + I2V补帧）

### 8.2 适配原则
#### T2I
- 强调静态构图、主体、文化细节、光影
- 动作层仅描述关键姿态与画面瞬间，不要过度描述连续运动

#### I2V（Start-End）
- 需要明确起始状态与结束状态的视觉连续性
- 减少冲突动作指令（避免同时要求多段复杂路径）
- 强调“缓动/镜头过渡/主体变化方向”

#### I2V（Start-Mid-End / Multi-Keyframe）
- 可描述阶段性动作变化
- 可输出关键帧提示组（frame_0 / frame_mid / frame_end）
- 更适合高动作镜头和微镜头连击段

#### 直接文生视频（Video Model）
- 强调动作连续性、镜头语言、节奏
- 需要控制长度与内容密度，避免单段过载
- 结合 09 输出的 `motion_level` 与 `beat_alignment_strength`

### 8.3 输出要求
每个 shot / micro-shot 可输出一个或多个 `model_variants`，按实际后端需要选择。

---

## 9. Branching Logic（分支流程与判断）

### [P1] 预检查分支（Precheck）
#### Trigger
- 收到 07/08/09 输出，准备生成提示词计划

#### Actions
1. 检查 07/08/09 状态是否允许继续
2. 检查 shot / micro-shot 是否有对应素材锚点（至少部分）
3. 读取 `selected_culture_pack`, `culture_constraints`
4. 读取 `global_render_profile`, `quality_profile`, `model_target`
5. 读取 `backend_capability` 与 `preset_catalog`（如有）

#### Output
- `precheck_status`
- `blocking_issues[]`

---

### [P2] 全局约束构建分支（Global Constraint Build）
#### Trigger
- 预检查通过

#### Actions
1. 构建全局正向约束（风格/题材/画面统一要求）
2. 构建全局负面约束（文化禁忌/时代禁忌/通用错误项）
3. 构建全局一致性锚点（角色、主场景、主要色彩倾向等）
4. 生成 `global_prompt_constraints`

#### Output
- `global_prompt_constraints`

---

### [P3] 镜头级 Prompt Layer 生成分支（Shot Layer Build）
#### Trigger
- 对每个 shot 进行提示词层生成

#### Actions
1. 从 shot_plan 获取镜头目的与构图信息
2. 从 07 获取文化层约束
3. 从 08 获取实体与素材锚点
4. 从 09 获取动作/节奏/帧预算/I2V模式策略
5. 生成各层 prompt fragments（不是一次性拼成大串）
6. 生成该 shot 的负面约束与一致性锚点层

#### Output
- `shot_prompt_layers[]`

---

### [P4] 微镜头 Prompt Layer 生成分支（Micro-shot Layer Build）
#### Trigger
- 存在 `microshot_render_plans[]`

#### Actions
1. 继承父 shot 的基础层、文化层、实体层
2. 根据 micro-shot 的时间段与对齐点强化动作层
3. 调整镜头层（更短、更明确的关键动作构图）
4. 根据 `frame_budget / i2v_mode` 生成更适配的层结构
5. 生成微镜头专属 negative constraints（防动作崩坏）

#### Output
- `microshot_prompt_layers[]`

---

### [P5] 模型适配变体生成分支（Model Variant Build）
#### Trigger
- Shot / micro-shot 层结构已完成

#### Actions
1. 根据 `model_target` 和 `backend_capability` 生成适配版本
2. 设定各模型的层拼接顺序与字段限制
3. 生成：
   - `positive_prompt`
   - `negative_prompt`
   - `keyframe_prompts`（如多关键帧）
   - `parameter_hints`
4. 记录 token/长度/复杂度估计（可选）

#### Output
- `model_variants[]`

---

### [P6] Preset Mapping Hint 生成分支（ComfyUI/执行器映射提示）
#### Trigger
- 已有模型适配变体

#### Actions
1. 根据 `comfyui_preset_catalog` 或执行器 schema 输出字段映射建议
2. 标注哪些层映射到：
   - 主提示词
   - 负提示词
   - LoRA / style nodes
   - control/reference inputs
   - keyframe prompt slots
3. 若后端不支持某模式，生成 fallback mapping

#### Output
- `preset_mapping_hints`

---

### [P7] 回退与降级分支（Fallback & Degrade）
#### Trigger
- 素材缺失、后端限制、提示词过长、模式不支持

#### Actions
1. 简化非关键实体层描述
2. 降级动作层复杂度（尤其低负载或后端不支持时）
3. 从 `multi_keyframe` 降到 `start_mid_end` 或 `start_end`
4. 将细节信息转为“风格提示”而非硬性实体指令
5. 记录 `fallback_prompt_actions[]`

#### Output
- `fallback_prompt_actions[]`
- 更新后的 prompt plans

---

### [P8] 清单组装分支（Prompt Plan Assembly）
#### Trigger
- 所有 shot/micro-shot 提示词计划完成

#### Actions
1. 汇总 shot / micro-shot prompt plans
2. 汇总模型变体索引
3. 输出全局约束与 preset mapping hints
4. 标记 review_required 项（关键镜头提示词冲突、长度超限等）

#### Output
- `prompt_plan.json`

---

## 10. Concurrency & Dependency（并发与依赖）

### 10.1 串行依赖（推荐）
1. Precheck
2. Global Constraint Build
3. Shot Layer Build
4. Micro-shot Layer Build（可选）
5. Model Variant Build
6. Preset Mapping Hint Build
7. Fallback & Degrade
8. Prompt Plan Assembly

### 10.2 可并行优化
在全局约束确定后，可并行处理：
- 各 shot 的 Layer Build
- 各 micro-shot 的 Layer Build
- 各项模型变体生成
最终统一汇总并做长度/兼容检查。

### 10.3 严禁提前执行
- 未完成 07/08/09 的有效输出前，不得定稿 prompt plan
- 未生成负面约束层，不得标记关键镜头 ready
- 未记录 fallback，不得静默删减关键描述

---

## 11. Prompt Layer Composition Rules（分层拼接规则）

### 11.1 正向提示词拼接（默认建议）
`base + cultural + entity + shot + motion + lighting_mood + quality + consistency_anchor`

### 11.2 负向提示词拼接（默认建议）
`global_negative + culture_negative + anatomy_negative + era_conflict_negative + model_specific_negative`

### 11.3 关键规则
- 文化负面约束必须早于通用负面约束定义（逻辑上）
- 动作层不应与镜头层发生明显冲突（例如“静态特写”同时写“高速追逐全景”）
- 高动作微镜头应减少冗长环境描述，突出关键动作与读图重点
- 低动作镜头可弱化动作层，强化氛围与构图

---

## 12. Prompt Quality Heuristics（提示词质量启发式）

### 12.1 按镜头类型调整权重
#### 空镜 / 建立镜头
- 场景与氛围层权重更高
- 动作层简化
- 光影与材质细节可提高

#### 对话镜头
- 人物实体层 + 镜头层 + 氛围层重要
- 动作层以表情/轻动作为主
- 保持角色一致性锚点

#### 打斗 / 高动作镜头
- 动作层 + 镜头层 + 一致性层优先
- 环境层保留关键空间信息即可，避免过度冗长
- 强调动作可读性、关键姿态、方向关系

### 12.2 按负载档位调整策略
#### LOW_LOAD
- 简化非关键实体描述
- 控制提示词长度
- 提高复用型一致性锚点权重

#### MEDIUM_LOAD
- 平衡层级细节与执行稳定性

#### HIGH_LOAD
- 允许关键镜头更精细的动作/构图分层
- 可输出多候选变体供执行器或导演层选择

---

## 13. Negative Prompt Strategy（负面约束策略）

### 13.1 分层负面约束（推荐）
- `global_negative`
  - 通用错误（畸形、低清晰度、错误肢体等）
- `culture_negative`
  - 文化/时代错位元素（现代霓虹、西式吧台、错误招牌文字等）
- `entity_negative`
  - 错误武器类型、错误服饰制式、错误角色特征
- `motion_negative`
  - 动作崩坏、残影混乱、关键动作不可读（视模型适配）
- `model_specific_negative`
  - 针对特定模型常见问题

### 13.2 注意事项
- 负面提示不宜无限堆叠，避免抑制过强导致画面贫瘠
- 对低动作镜头与高动作镜头使用不同负面模板
- 文化负面约束优先于纯审美负面约束

---

## 14. Consistency Anchor Rules（一致性锚点规则）

### 14.1 角色一致性锚点（Character Anchor）
建议字段：
- `character_anchor_id`
- `identity_keywords`
- `fixed_traits`（发型/服饰主色/武器身份）
- `avoid_trait_drift`（避免漂移项）

### 14.2 场景一致性锚点（Scene Anchor）
建议字段：
- `scene_anchor_id`
- `architecture_traits`
- `lighting_baseline`
- `material_traits`
- `signage_rules`

### 14.3 使用原则
- 同一 scene 内镜头优先继承相同场景锚点
- 同一角色跨镜头优先继承角色锚点
- 微镜头默认继承父 shot 锚点，只做局部动作层增强

---

## 15. Integration with Visual Render Plan（与 09 的联动规则）

### 15.1 必须读取的字段（来自 09）
- `motion_level`
- `motion_complexity_score`
- `frame_budget`
- `i2v_mode`
- `criticality`
- `beat_alignment_strength`
- `split_into_microshots`

### 15.2 联动映射示例
- `LOW_MOTION + frame_budget=8`
  - 简化动作层，强化氛围/构图层
- `HIGH_MOTION + i2v_mode=start_mid_end`
  - 输出分阶段动作提示（start/mid/end）
- `criticality=critical + degrade_allowed=false`
  - 禁止自动删减关键动作描述
- `beat_alignment_strength=high`
  - 在动作层加入“打击瞬间/动作峰值”导向描述（保持简洁）

---

## 16. Integration with ComfyUI Presets（与 ComfyUI 预设衔接）

### 16.1 本模块输出映射提示，不直接生成节点图
推荐输出：
- `preset_id_hint`
- `positive_prompt_field`
- `negative_prompt_field`
- `style_lora_refs`
- `reference_image_refs`
- `keyframe_prompt_slots`
- `control_hints`

### 16.2 示例映射逻辑（概念）
- `start_end` 模式：
  - `frame_0_prompt` <- base+culture+entity+shot
  - `frame_end_prompt` <- base+culture+entity+shot+motion(end_state)
  - `negative_prompt` <- merged_negative
- `start_mid_end` 模式：
  - 额外输出 `frame_mid_prompt`
- `multi_keyframe`：
  - 输出 `keyframe_prompts[]` + 每段动作重点

### 16.3 后端能力不足时
- 输出 `fallback_preset_id_hint`
- 降级 `i2v_mode`
- 记录 `fallback_prompt_actions`

---

## 17. Output Contract（输出契约）

### 17.1 顶层结构（示例）
```json
{
  "version": "1.0",
  "status": "ready_for_prompt_execution",
  "prompt_plan_summary": {
    "total_shots": 32,
    "total_microshots": 14,
    "model_variants_generated": 58,
    "fallback_prompt_actions": 6,
    "review_required": 2
  },
  "global_prompt_constraints": {},
  "shot_prompt_plans": [],
  "microshot_prompt_plans": [],
  "model_variants": [],
  "preset_mapping_hints": {},
  "fallback_prompt_actions": [],
  "warnings": [],
  "review_required_items": []
}
```

### 17.2 `global_prompt_constraints`（建议字段）
- `selected_culture_pack`
- `global_positive_fragments[]`
- `global_negative_fragments[]`
- `style_mode`
- `quality_profile`
- `global_consistency_anchors`
- `user_overrides_applied[]`

### 17.3 `shot_prompt_plans[]`（每个镜头）
每项至少包含：
- `shot_id`
- `scene_id`
- `criticality`
- `prompt_layers`
- `negative_layers`
- `consistency_anchors`
- `derived_from`
  - `asset_match_refs[]`
  - `visual_render_plan_ref`
- `assembly_rules`
- `warnings[]`

#### `prompt_layers`（建议结构）
- `base[]`
- `cultural[]`
- `entity[]`
- `shot[]`
- `motion[]`
- `lighting_mood[]`
- `quality[]`
- `consistency_anchor[]`

#### `negative_layers`
- `global_negative[]`
- `culture_negative[]`
- `entity_negative[]`
- `motion_negative[]`
- `model_specific_negative[]`（可留空）

### 17.4 `microshot_prompt_plans[]`
每项至少包含：
- `microshot_id`
- `parent_shot_id`
- `criticality`
- `inherits_from_shot_layers`（bool）
- `overrides`
  - `motion`
  - `shot`
  - `quality`（如有）
- `prompt_layers`
- `negative_layers`
- `alignment_points[]`

### 17.5 `model_variants[]`
每项至少包含：
- `variant_id`
- `target_type`（shot/microshot）
- `target_id`
- `model_mode`（T2I / I2V_START_END / I2V_START_MID_END / ...）
- `positive_prompt`
- `negative_prompt`
- `keyframe_prompts[]`（如适用）
- `parameter_hints`
  - `style_strength`
  - `motion_strength`
  - `guidance_hint`
  - `quality_priority`
- `length_estimate`
- `preset_mapping_ref`

### 17.6 `preset_mapping_hints`（建议结构）
- `default_mappings`
- `per_model_mode_mappings`
- `fallback_mappings`

### 17.7 `fallback_prompt_actions[]`
每项至少包含：
- `target_type`
- `target_id`
- `action`
  - `simplify_entity_layer`
  - `reduce_motion_complexity`
  - `drop_optional_detail`
  - `downgrade_model_mode`
  - `use_generic_cultural_fragments`
- `reason_tags[]`
- `before_summary`
- `after_summary`

---

## 18. Decision Table（关键判断表）

### D1. 是否允许生成最终 Prompt Plan
| 条件 | 动作 |
|---|---|
| 07/08/09 均为可继续状态 | 继续 |
| 08 缺关键素材但允许占位/回退 | 继续并标记风险 |
| 09 只有 preview render plan | 生成 preview prompt plan（不可标最终） |
| 缺少关键输入（08 或 09） | REVIEW_REQUIRED / FAILED |

### D2. 是否生成 micro-shot 专用提示词
| 条件 | 动作 |
|---|---|
| 存在 microshot_render_plans | 为每个 micro-shot 生成专用层或继承+覆写 |
| 无 micro-shot | 仅生成 shot 级提示词 |
| 用户禁用 micro-shot 提示词细化 | 继承父 shot，减少独立生成 |

### D3. 模型模式降级
| 条件 | 动作 |
|---|---|
| 后端支持目标模式 | 按目标模式输出 |
| 不支持 multi_keyframe | 降级为 start_mid_end 或 start_end |
| 不支持 I2V | 输出 T2I关键帧计划 + 标记执行器后续处理 |
| 提示词长度超限 | 启动层级压缩 / 删减非关键细节 |

### D4. 关键镜头提示词冲突处理
| 条件 | 动作 |
|---|---|
| 层间描述轻微冲突 | 自动修正并记录 warning |
| 文化层与实体层冲突 | 以文化绑定结果优先，必要时 REVIEW_REQUIRED |
| 镜头层与动作层强冲突 | 优先镜头目标 + 动作可读性，重新平衡 |

---

## 19. State Machine（状态机）

States:
- INIT
- PRECHECKING
- PRECHECK_READY
- BUILDING_GLOBAL_CONSTRAINTS
- GLOBAL_CONSTRAINTS_READY
- BUILDING_SHOT_PROMPT_LAYERS
- BUILDING_MICROSHOT_PROMPT_LAYERS
- BUILDING_MODEL_VARIANTS
- BUILDING_PRESET_MAPPING_HINTS
- FALLBACK_PROCESSING
- ASSEMBLING_PROMPT_PLAN
- REVIEW_REQUIRED
- READY_FOR_PROMPT_EXECUTION
- FAILED

Transitions:
- INIT -> PRECHECKING
- PRECHECKING -> PRECHECK_READY
- PRECHECK_READY -> BUILDING_GLOBAL_CONSTRAINTS
- BUILDING_GLOBAL_CONSTRAINTS -> GLOBAL_CONSTRAINTS_READY
- GLOBAL_CONSTRAINTS_READY -> BUILDING_SHOT_PROMPT_LAYERS
- BUILDING_SHOT_PROMPT_LAYERS -> BUILDING_MICROSHOT_PROMPT_LAYERS（若有微镜头）
- BUILDING_SHOT_PROMPT_LAYERS -> BUILDING_MODEL_VARIANTS（若无微镜头）
- BUILDING_MICROSHOT_PROMPT_LAYERS -> BUILDING_MODEL_VARIANTS
- BUILDING_MODEL_VARIANTS -> BUILDING_PRESET_MAPPING_HINTS
- BUILDING_PRESET_MAPPING_HINTS -> FALLBACK_PROCESSING（若需要）
- BUILDING_PRESET_MAPPING_HINTS -> ASSEMBLING_PROMPT_PLAN（若无需回退）
- FALLBACK_PROCESSING -> ASSEMBLING_PROMPT_PLAN
- ASSEMBLING_PROMPT_PLAN -> READY_FOR_PROMPT_EXECUTION
- ASSEMBLING_PROMPT_PLAN -> REVIEW_REQUIRED（关键冲突/长度超限无法自动修复）
- 任意状态 -> FAILED（不可恢复错误）

---

## 20. Example Mini Output（简化示例）
```json
{
  "version": "1.0",
  "status": "ready_for_prompt_execution",
  "prompt_plan_summary": {
    "total_shots": 2,
    "total_microshots": 1,
    "model_variants_generated": 3,
    "fallback_prompt_actions": 0,
    "review_required": 0
  },
  "global_prompt_constraints": {
    "selected_culture_pack": "cn_wuxia",
    "global_positive_fragments": ["cinematic wuxia atmosphere", "cultural consistency with ancient Chinese inn setting"],
    "global_negative_fragments": ["modern neon signage", "western pub taps", "modern typography"],
    "style_mode": "realistic_cinematic",
    "quality_profile": "final",
    "global_consistency_anchors": {
      "scene_anchor_ids": ["SC11_INN_HALL"],
      "character_anchor_ids": ["CHAR_LEAD_01"]
    },
    "user_overrides_applied": []
  },
  "shot_prompt_plans": [
    {
      "shot_id": "S27",
      "scene_id": "SC11",
      "criticality": "critical",
      "prompt_layers": {
        "base": ["a fast-paced duel sequence inside a wuxia inn hall"],
        "cultural": ["ancient Chinese wuxia inn interior, wooden beams, lantern-lit environment"],
        "entity": ["lead swordsman in dark jianghu outfit", "Chinese straight sword (jian)", "wooden tables and pillars"],
        "shot": ["dynamic medium-wide action shot", "strong directional composition"],
        "motion": ["rapid sword exchange, readable combat poses, impact-driven movement"],
        "lighting_mood": ["warm lantern highlights, dramatic contrast, tense atmosphere"],
        "quality": ["high action readability", "cinematic detail priority"],
        "consistency_anchor": ["character_anchor:CHAR_LEAD_01", "scene_anchor:SC11_INN_HALL"]
      },
      "negative_layers": {
        "global_negative": ["extra limbs", "deformed anatomy", "blurry details"],
        "culture_negative": ["modern bar counter", "western beer taps", "neon sign"],
        "entity_negative": ["katana shape mismatch", "modern tactical outfit"],
        "motion_negative": ["unreadable overlapping poses"],
        "model_specific_negative": []
      },
      "consistency_anchors": ["CHAR_LEAD_01", "SC11_INN_HALL"],
      "derived_from": {
        "asset_match_refs": ["E01", "E03"],
        "visual_render_plan_ref": "S27"
      },
      "assembly_rules": {
        "positive_order": ["base", "cultural", "entity", "shot", "motion", "lighting_mood", "quality", "consistency_anchor"],
        "negative_order": ["global_negative", "culture_negative", "entity_negative", "motion_negative"]
      },
      "warnings": []
    }
  ],
  "microshot_prompt_plans": [
    {
      "microshot_id": "S27A",
      "parent_shot_id": "S27",
      "criticality": "critical",
      "inherits_from_shot_layers": true,
      "overrides": {
        "motion": ["single impact moment, sword clash at peak hit timing, clear contact pose"],
        "shot": ["tight dynamic action framing centered on weapon clash"],
        "quality": ["impact readability first"]
      },
      "prompt_layers": {},
      "negative_layers": {},
      "alignment_points": [91540]
    }
  ],
  "model_variants": [
    {
      "variant_id": "PV_S27_I2V_SME",
      "target_type": "shot",
      "target_id": "S27",
      "model_mode": "I2V_START_MID_END",
      "positive_prompt": "a fast-paced duel sequence inside a wuxia inn hall, ancient Chinese wuxia inn interior, wooden beams, lantern-lit environment, lead swordsman in dark jianghu outfit, Chinese straight sword, dynamic medium-wide action shot, rapid sword exchange, readable combat poses, warm lantern highlights, cinematic detail, character consistency anchor",
      "negative_prompt": "modern neon signage, western pub taps, extra limbs, deformed anatomy, unreadable overlapping poses",
      "keyframe_prompts": [
        {"slot": "start", "prompt": "combat stance before clash, tension rising"},
        {"slot": "mid", "prompt": "clear sword clash impact moment, sparks/impact emphasis if style allows"},
        {"slot": "end", "prompt": "follow-through recovery pose, maintain spatial continuity"}
      ],
      "parameter_hints": {
        "style_strength": "medium_high",
        "motion_strength": "high",
        "guidance_hint": "stable_subject_priority",
        "quality_priority": "high"
      },
      "length_estimate": {
        "positive_chars": 358,
        "negative_chars": 122
      },
      "preset_mapping_ref": "i2v_start_mid_end_action_v1"
    }
  ],
  "preset_mapping_hints": {
    "default_mappings": {
      "positive_prompt_field": "prompt",
      "negative_prompt_field": "negative_prompt"
    },
    "per_model_mode_mappings": {
      "I2V_START_MID_END": {
        "preset_id_hint": "i2v_start_mid_end_action_v1",
        "keyframe_prompt_slots": ["start", "mid", "end"],
        "reference_image_refs": ["scene_anchor", "character_anchor"]
      }
    },
    "fallback_mappings": {}
  },
  "fallback_prompt_actions": [],
  "warnings": [],
  "review_required_items": []
}
```

---

## 21. Recommended File Split（建议拆分文件）
后续复杂后可拆分为：
- `10.1_PROMPT_LAYER_SCHEMA.md`
- `10.2_MODEL_VARIANT_RULES.md`
- `10.3_NEGATIVE_PROMPT_POLICY.md`
- `10.4_COMFYUI_PRESET_MAPPING_INTERFACE.md`
- `10.5_PROMPT_FALLBACK_POLICY.md`

当前阶段可先保留为单文件。

---

## 22. Definition of Done（完成标准）
满足以下条件才视为本 Skill 完成：
- [ ] 已完成 07/08/09 输入预检查
- [ ] 已生成 `global_prompt_constraints`
- [ ] 所有 shot 已生成分层提示词计划
- [ ] 存在 micro-shot 时已生成专用提示词或继承覆写计划
- [ ] 已生成至少一种模型适配变体（符合后端能力）
- [ ] 已输出 `preset_mapping_hints`
- [ ] 已应用（或明确跳过）fallback/degrade 策略
- [ ] 已输出 `prompt_plan.json`
- [ ] 状态明确为 `READY_FOR_PROMPT_EXECUTION` / `REVIEW_REQUIRED` / `FAILED`
- [ ] 输出结构满足契约，便于下游执行器直接消费

---

## 23. RAG Recipe 执行补充（P0）
- 每次 prompt 生成前必须执行 recipe 检索：
  1. role 过滤（如 cinematographer/gaffer/art_director/director）
  2. tags 过滤（culture_pack/genre/motion_level/shot_type）
  3. 向量检索 top-k
  4. hard constraints 优先合并

### 23.1 必须写回字段
- `kb_version_id`
- `recipe_id`
- `retrieved_item_ids[]`
- `constraint_conflict_flags[]`

### 23.2 失败降级策略
- 检索不可用时回退到 `baseline_prompt_policy`。
- 检索冲突时优先保留 `hard_constraint` 并标记 `review_required`。
