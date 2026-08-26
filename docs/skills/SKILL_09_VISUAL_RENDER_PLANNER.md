根据音频时间线 + 分镜语义 + 后端负载状态，生成“可执行的视觉渲染计划（帧预算、镜头时长、微镜头拆分、I2V模式、优先级、降级策略）”。

# 09_VISUAL_RENDER_PLANNER.md
# Visual Render Planner（音频驱动画面负载规划 Skill 模板｜中文版）

## 0. 文档定位
本 Skill 用于在“音频最终时间线完成后、图像/视频生成执行前”，
根据音频事件密度、对白时长、BGM节奏、SFX打击点、场景语义、分镜信息以及后端负载状态，
输出结构化的视觉渲染计划（Visual Render Plan）。

该模块是“编排/调度规划器”，不直接执行生成任务。

---

## 术语对齐声明（固定模板）
- 本文统一运行对象命名：`run / job / stage / event / artifact`。
- `run`：一次端到端业务运行；`job`：run 内原子执行单元；`stage`：run 阶段状态。
- `event`：跨模块事实消息，统一采用 `EventEnvelope`；`artifact`：可回溯产物元数据。
- `worker.*.completed` 为执行明细事件，不替代 `job.succeeded / job.failed` 主状态事件。
- `step` 仅表示内部步骤序号，不作为运行态主对象或事件前缀。
- 必带治理字段：`tenant_id / project_id / trace_id / correlation_id / idempotency_key / schema_version`。

## 1. Workflow Goal（目标）
为每个镜头（shot）或微镜头（micro-shot）生成可执行的渲染策略，包括但不限于：

- 镜头时间范围（start/end）
- 动作复杂度评分（motion complexity score）
- 动作等级（low / medium / high）
- 帧预算（frame budget，例如 8 / 12 / 24）
- I2V模式（首尾帧 / 首中尾帧 / 多关键帧）
- 是否拆分微镜头（micro-shot split）
- 计算优先级与质量优先级
- 降级策略（低负载/拥塞时）
- 与音频切点/打击点的对齐建议

最终输出供下游模块使用：
- Prompt Planner
- I2V Executor / ComfyUI Worker
- Composer / Timeline Assembler
- Queue Scheduler / Resource Orchestrator

---

## 2. Scope（范围）

### 包含
- 音频驱动的镜头复杂度分析
- 帧预算规划（compute-aware）
- 全局负载档位映射（LOW/MEDIUM/HIGH）
- 局部镜头覆写（高动作片段升级）
- 微镜头拆分（尤其打斗/追逐）
- 与后端能力/负载状态联动的降级策略
- 输出渲染计划 JSON 契约

### 不包含
- 最终提示词完整拼接（由 Prompt Planner 完成）
- 图像/视频生成执行（由 Render Workers 执行）
- 音频重规划（已假设 timeline_final 已完成）
- 最终视频合成（由 Composer 完成）

---

## 3. Inputs（输入）

### 3.1 必需输入
- `timeline_final.json`
  - 最终精确时间线（基于 TTS 真实时长）
- `audio_event_manifest.json`
  - 包含 TTS、SFX、BGM、Ambience 的时间事件与强度信息
- `shot_plan.json`
  - 场景/镜头规划（来自 Story/Scene Planner）
- `asset_match_result.json`（来自 08_ASSET_MATCHER）
  - 用于知道每个镜头可用的场景/角色/道具素材锚点
- `global_render_profile`
  - `LOW_LOAD` / `MEDIUM_LOAD` / `HIGH_LOAD`

### 3.2 可选输入
- `backend_capability`
  - GPU型号、可用工作流、支持的 I2V 模式、并发上限、建议帧预算
- `backend_load_status`
  - 当前队列长度、VRAM占用、平均耗时、拥塞等级
- `quality_profile`
  - `preview` / `standard` / `final`
- `user_overrides`
  - 用户指定某段必须高质量 / 固定帧预算 / 禁止拆镜
- `feature_flags`
  - `enable_compute_aware_planning`
  - `enable_microshot_split`
  - `enable_backend_auto_degrade`
  - `enable_audio_beat_alignment`
- `project_constraints`
  - 总预算限制、生成时长限制、交付时限等

---

## 4. Outputs（输出）

### 4.1 主输出文件
- `visual_render_plan.json`

### 4.2 输出内容必须包含
1. `status`
2. `global_render_profile`
3. `planning_summary`
4. `shot_render_plans[]`
5. `microshot_render_plans[]`（如有）
6. `resource_strategy`
7. `degrade_actions[]`（如触发）
8. `warnings[]`
9. `review_required_items[]`（如有）

---

## 5. Core Concepts（核心概念）

### 5.1 Shot（镜头）
由上游 `shot_plan` 定义的逻辑镜头，具有场景目的与时间范围。

### 5.2 Micro-shot（微镜头）
在高动作片段中，为了更好地对齐音频打击点/动作节奏而从一个 shot 内拆出的更短子镜头。
- 常见时长：0.3s ~ 1.0s（可配置）

### 5.3 Frame Budget（帧预算）
用于控制该镜头的 I2V 生成复杂度（如 8 / 12 / 24），是“生成预算”概念，
**不等同于最终输出视频帧率**。

### 5.4 Motion Complexity Score（动作复杂度评分）
基于音频事件密度 + 文本语义 + 镜头语境估算的动态强度分数（0~100），用于映射渲染策略。

### 5.5 Compute-aware Planning（算力感知规划）
在保证关键片段质量的前提下，考虑后端负载、队列拥塞与兼容性进行动态调度与降级。

---

## 6. Global Render Profiles（全局渲染负载档位）

### 6.1 档位定义
- `LOW_LOAD`（低负载）
- `MEDIUM_LOAD`（中负载）
- `HIGH_LOAD`（高负载）

### 6.2 默认映射（建议，可配置）
#### LOW_LOAD
- 默认帧预算：8
- 单镜头建议时长：2.5s ~ 6.0s
- 倾向：减少切镜、复用素材、低动作镜头优先
- 场景：空镜、海面、风景、缓慢对白、雨夜氛围

#### MEDIUM_LOAD
- 默认帧预算：12
- 单镜头建议时长：1.5s ~ 4.0s
- 倾向：平衡质量与负载
- 场景：普通叙事、走路、日常互动、常规对话

#### HIGH_LOAD
- 默认帧预算：24
- 单镜头建议时长：0.4s ~ 1.5s（高动作允许更短）
- 倾向：高频切镜、动作清晰度优先
- 场景：打斗、追逐、爆炸、连续击打、强节奏剪辑

### 6.3 重要说明
- 帧预算是“生成复杂度预算”，不是最终导出 FPS
- 最终导出 FPS 由下游合成/输出模块决定（例如 24fps）
- 全局档位是默认策略，允许被局部片段覆写

---

## 7. Motion Complexity Scoring（动作复杂度评分）

### 7.1 评分目标
为每个 shot（或候选微镜头）打分，用于判断：
- 是否需要拆分
- 该用多少帧预算
- 是否需要更紧密对齐音频切点
- 是否提升计算优先级

### 7.2 推荐输入特征（规则 + LLM辅助）
1. **语义动作强度（0~30）**
   - 打斗/追逐/爆炸/翻滚/跳跃 > 行走 > 静态对话 > 空镜
2. **SFX事件密度（0~25）**
   - 单位秒内事件数量越高分越高
3. **音频瞬态峰值密度（0~20）**
   - 金属碰撞/拳打/刀击等连续峰值越密集分越高
4. **BGM节拍强度与节奏变化（0~15）**
   - 强鼓点、快节拍、明显切点加分
5. **镜头内角色运动预估（0~10）**
   - 根据分镜语义和动作标注估计角色运动复杂度

### 7.3 分级建议
- `0-25` → `LOW_MOTION`
- `26-55` → `MEDIUM_MOTION`
- `56-100` → `HIGH_MOTION`

### 7.4 规则与 LLM 混合建议
- 基础评分由规则引擎完成（稳定）
- LLM 用于语义修正（导演化语境、特殊动作判断）
- 输出仅保留分数与原因标签，不输出冗长内部思维过程

---

## 8. Motion-to-Render Mapping（动作复杂度到渲染策略映射）

### 8.1 LOW_MOTION
建议策略：
- 可延长镜头时长
- 低帧预算（通常 8）
- I2V模式：`start_end`
- 优先慢推/慢摇/轻微动态（由下游执行器决定）
- 可复用场景/背景素材
- 对齐音频要求较宽松（避免过度切分）

适用示例：
- 海面空镜、风声雨声氛围镜头、静态对话、沉思特写

---

### 8.2 MEDIUM_MOTION
建议策略：
- 中等镜头时长
- 中帧预算（通常 12）
- I2V模式：`start_end` 或 `start_mid_end`
- 正常切镜频率
- 适度对齐对白停顿或 BGM 小节变化

适用示例：
- 行走、日常互动、轻动作、室内调度、常规叙事推进

---

### 8.3 HIGH_MOTION
建议策略：
- 缩短镜头时长（可能 <1s）
- 提高帧预算（通常 24）
- I2V模式：`start_mid_end` 或 `multi_keyframe`
- 更高频切镜
- 更精细对齐音频打击点/瞬态峰值/BGM强拍
- 优先保证动作可读性与节奏感

适用示例：
- 打斗、连续招式、追逐、轰击、刀铁碰撞、快节奏动作段

---

## 9. High-Motion Micro-shot Rule（高动作微镜头规则）

### 9.1 触发条件（满足任一即可）
- `motion_level == HIGH_MOTION`
- 连续打击/碰撞事件频率高（如 >2~3 次/秒，可配置）
- 音频瞬态峰值密度高且连续
- BGM节拍密度高且存在明显切点
- 分镜语义为连续连击/快速追逐/高速闪避
- 用户或导演策略要求“高动作细切”

### 9.2 拆分策略（建议）
- 单微镜头时长：`0.3s ~ 1.0s`（可配置）
- 每个微镜头至少有首尾关键帧；必要时增加中间关键帧
- 允许同一原始 shot 拆成多个 micro-shots
- 优先在音频打击点 / 峰值附近切分，避免切在语义动作中间（若可识别）

### 9.3 输出要求
- 保留原始 `parent_shot_id`
- 为每个微镜头生成独立计划项
- 标记 `split_reason_tags`
- 标记 `alignment_points`（如打击点、强拍点）

---

## 10. Backend-Aware Load Protection（后端负载保护）

### 10.1 目标
在后端拥塞、VRAM紧张或任务超时风险上升时，优先保护关键片段质量并控制总体负载。

### 10.2 触发信号（示例）
- GPU队列长度超过阈值
- VRAM占用持续高位
- 平均任务耗时超标
- 后端报告拥塞等级 `high`
- 当日预算/总任务预算接近上限

### 10.3 降级策略（建议）
1. **先降级 LOW_MOTION 片段**
   - 12 → 8 或 8 保持
   - 延长镜头时长、减少切镜
2. **再降级非关键 MEDIUM_MOTION 片段**
   - 24 → 12 或 12 → 8
3. **尽量保留关键 HIGH_MOTION 片段质量**
   - 高动作主段优先保留帧预算和切镜密度
4. **预览版优先策略**
   - 非关键镜头可转为 `preview_mode_render_plan`
5. **必要时限制并发**
   - 降低同时在跑的 I2V 数量，避免雪崩

### 10.4 禁止策略（除非用户允许）
- 无差别全局降级关键镜头
- 忽略用户指定高质量片段
- 在未记录 `degrade_actions` 的情况下静默降级

---

## 11. Branching Logic（分支流程与判断）

### [V1] 预检查分支（Precheck）
#### Trigger
- 收到音频最终时间线与分镜计划，准备生成渲染计划

#### Actions
1. 检查 `timeline_final.json` 是否可用（必须是 final，不是 provisional）
2. 检查 `shot_plan.json` 时间范围是否可对齐
3. 检查 `asset_match_result.json` 状态是否允许继续（`READY_FOR_PROMPT_PLANNER` 或系统允许预览）
4. 读取 `global_render_profile`
5. 读取 `backend_capability / backend_load_status`（如有）

#### Output
- `precheck_status`
- `blocking_issues[]`

---

### [V2] 音频特征聚合分支（Audio Feature Aggregation）
#### Trigger
- 预检查通过

#### Actions
1. 按 shot 时间窗口聚合音频事件：
   - TTS对白密度
   - SFX事件数/秒
   - 瞬态峰值密度
   - BGM节拍强度
   - Ambience强度/稳定性
2. 提取候选对齐点（beat hits / impact peaks / dialogue pauses）
3. 形成 `shot_audio_features[]`

#### Output
- `shot_audio_features[]`

---

### [V3] 动作复杂度评分分支（Motion Scoring）
#### Trigger
- 已有 shot 级音频特征 + 分镜语义信息

#### Actions
1. 规则引擎计算基础分
2. LLM/语义模块进行修正（可选）
3. 得到 `motion_complexity_score` 和 `motion_level`
4. 附加 `reasoning_tags`（如 `metal_hits_dense`, `sea_ambience`, `dialogue_heavy`）

#### Output
- `shot_motion_scores[]`

---

### [V4] 渲染策略映射分支（Render Strategy Mapping）
#### Trigger
- 已有 `motion_level` + `global_render_profile`

#### Actions
1. 基于全局档位生成默认策略（帧预算、I2V模式、时长建议）
2. 根据 `motion_level` 做局部覆写
3. 根据 `quality_profile` 调整质量倾向
4. 根据 `asset availability` 调整可执行策略（例如缺少多关键帧参考时降级 I2V 模式）

#### Output
- `shot_strategy_candidates[]`

---

### [V5] 微镜头拆分分支（Micro-shot Split）
#### Trigger
- shot 满足高动作拆分条件，且 `enable_microshot_split = true`

#### Actions
1. 根据音频对齐点切分候选子段
2. 约束每段时长（避免过短不可读）
3. 为每个 micro-shot 重新估计帧预算/I2V模式
4. 标记 parent-child 关系
5. 生成拆分原因与对齐点

#### Output
- `microshot_render_plans[]`
- 更新后的 `shot_render_plans[]`（标记已拆分）

---

### [V6] 后端负载保护与降级分支（Backend-Aware Degrade）
#### Trigger
- 存在 `backend_load_status` 且拥塞触发，或预算约束触发

#### Actions
1. 识别可降级片段（背景/低动作/非关键）
2. 应用降级策略（帧预算降低、减少切镜、简化I2V模式）
3. 保留关键片段质量（优先）
4. 记录所有降级动作与原因

#### Output
- `degrade_actions[]`
- 更新后的渲染计划

---

### [V7] 清单组装分支（Render Plan Assembly）
#### Trigger
- 所有镜头策略完成（含拆分与降级）

#### Actions
1. 汇总 shot 与 micro-shot 渲染计划
2. 生成 `resource_strategy`（并发、优先级、队列建议）
3. 标记需要人工确认的片段（如过度拆分、冲突策略）
4. 输出 `visual_render_plan.json`

#### Output
- `visual_render_plan.json`

---

## 12. Concurrency & Dependency（并发与依赖）

### 12.1 串行依赖（推荐）
1. Precheck
2. Audio Feature Aggregation
3. Motion Scoring
4. Render Strategy Mapping
5. Micro-shot Split（可选）
6. Backend-Aware Degrade（可选）
7. Render Plan Assembly

### 12.2 可并行优化
在统一上下文确定后，可并行处理：
- 各 shot 的音频特征聚合
- 各 shot 的 motion scoring
- 各 shot 的策略映射
最终在 micro-shot 和全局降级阶段汇总。

### 12.3 严禁提前执行
- 未拿到 `timeline_final` 不得生成最终 render plan
- 未完成 motion scoring 不得直接定帧预算
- 未记录降级动作不得静默修改关键参数

---

## 13. State Machine（状态机）

States:
- INIT
- PRECHECKING
- PRECHECK_READY
- AUDIO_FEATURES_AGGREGATING
- AUDIO_FEATURES_READY
- MOTION_SCORING
- MOTION_SCORED
- STRATEGY_MAPPING
- STRATEGY_READY
- MICROSHOT_SPLITTING
- DEGRADE_PROCESSING
- ASSEMBLING_RENDER_PLAN
- REVIEW_REQUIRED
- READY_FOR_RENDER_EXECUTION
- FAILED

Transitions:
- INIT -> PRECHECKING
- PRECHECKING -> PRECHECK_READY
- PRECHECK_READY -> AUDIO_FEATURES_AGGREGATING
- AUDIO_FEATURES_AGGREGATING -> AUDIO_FEATURES_READY
- AUDIO_FEATURES_READY -> MOTION_SCORING
- MOTION_SCORING -> MOTION_SCORED
- MOTION_SCORED -> STRATEGY_MAPPING
- STRATEGY_MAPPING -> STRATEGY_READY
- STRATEGY_READY -> MICROSHOT_SPLITTING（若启用且命中）
- STRATEGY_READY -> DEGRADE_PROCESSING（若无需拆分但需负载保护）
- MICROSHOT_SPLITTING -> DEGRADE_PROCESSING（若启用负载保护）
- MICROSHOT_SPLITTING -> ASSEMBLING_RENDER_PLAN（若无需负载保护）
- DEGRADE_PROCESSING -> ASSEMBLING_RENDER_PLAN
- ASSEMBLING_RENDER_PLAN -> READY_FOR_RENDER_EXECUTION
- ASSEMBLING_RENDER_PLAN -> REVIEW_REQUIRED（存在关键冲突/超阈值异常）
- 任意状态 -> FAILED（不可恢复错误）

---

## 14. Output Contract（输出契约）

### 14.1 顶层结构（示例）
```json
{
  "version": "1.0",
  "status": "ready_for_render_execution",
  "global_render_profile": "MEDIUM_LOAD",
  "planning_summary": {
    "total_shots": 32,
    "high_motion_shots": 8,
    "microshot_splits": 5,
    "total_microshots": 14,
    "degraded_shots": 6,
    "critical_segments_protected": 4
  },
  "resource_strategy": {
    "recommended_parallelism": 2,
    "queue_priority_mode": "critical_first",
    "preview_first": false
  },
  "shot_render_plans": [],
  "microshot_render_plans": [],
  "degrade_actions": [],
  "warnings": [],
  "review_required_items": []
}
14.2 shot_render_plans[]（镜头级计划）

每项至少包含：

shot_id

scene_id

start_ms

end_ms

duration_ms

motion_complexity_score

motion_level（LOW_MOTION / MEDIUM_MOTION / HIGH_MOTION）

audio_features

render_strategy

split_into_microshots（bool）

criticality（critical/important/normal/background）

reasoning_tags[]

warnings[]

14.3 audio_features（示例字段）

tts_density

sfx_events_per_sec

transient_peak_density

bgm_beat_intensity

ambience_intensity

alignment_points[]（时间点列表）

14.4 render_strategy（示例字段）

frame_budget（8/12/24...）

i2v_mode（start_end / start_mid_end / multi_keyframe）

target_shot_duration_ms

beat_alignment_strength（low/medium/high）

quality_priority（low/medium/high）

compute_priority（low/medium/high）

degrade_allowed（bool）

fallback_i2v_mode

backend_constraints_applied[]

14.5 microshot_render_plans[]（微镜头级计划）

每项至少包含：

microshot_id

parent_shot_id

start_ms

end_ms

duration_ms

split_reason_tags[]

alignment_points[]

motion_complexity_score

render_strategy

criticality

14.6 degrade_actions[]

每项至少包含：

target_type（shot / microshot / global）

target_id

action

reduce_frame_budget

simplify_i2v_mode

merge_microshots

reduce_parallelism

preview_mode_only

before

after

reason_tags[]

15. Decision Table（关键判断表）
D1. 是否允许生成最终渲染计划
条件	动作
timeline_final 可用 + shot_plan 可对齐	继续
只有 provisional timeline	禁止最终 render plan，可输出 preview plan（可选）
缺少关键输入（shot_plan 或 asset_match_result）	REVIEW_REQUIRED 或 FAILED
D2. 是否触发微镜头拆分
条件	动作
motion_level = HIGH_MOTION 且命中高动作规则	触发 micro-shot split
motion_level = MEDIUM_MOTION 且音频峰值密集	可选触发（看配置）
用户禁用拆分	不拆分，改为提高帧预算/对齐强度
D3. 帧预算映射（默认）
全局档位	LOW_MOTION	MEDIUM_MOTION	HIGH_MOTION
LOW_LOAD	8	8~12	12（关键段可 16/24 覆写）
MEDIUM_LOAD	8	12	24
HIGH_LOAD	12	16~24	24（关键段可更高配置）
D4. 后端拥塞时处理
条件	动作
后端拥塞高 + 非关键 LOW_MOTION	降级帧预算/延长镜头/减少切镜
后端拥塞高 + 关键 HIGH_MOTION	尽量保护，必要时仅降并发不降质量
用户指定该段高质量锁定	不降该段质量，记录其他段降级
16. Render Strategy Heuristics（渲染策略启发式）
16.1 I2V 模式选择建议

start_end

低动作、稳定氛围镜头、对白镜头

start_mid_end

中动作镜头、角色位移、轻打斗、常规运动

multi_keyframe

高动作镜头、复杂动作路径、快节奏连续招式

16.2 镜头时长建议

空镜/氛围镜：可长（2.5s+）

对话镜头：依据对白停顿与语义段落切

打斗镜头：短镜头 + 微镜头拆分更优

若打击点密集：宁可增加分镜密度，也不要用低预算硬拖长镜头

16.3 关键片段保护（推荐）

对以下片段提高质量优先级：

主角高光动作段

剧情转折关键镜头

首次登场场景（主角/核心场景）

强音画同步高潮段（BGM爆点 + SFX +动作）

17. Integration with ComfyUI / Executors（与执行器衔接建议）
17.1 本模块不直接生成 ComfyUI 工作流

但应输出足够字段让下游执行器映射：

frame_budget

i2v_mode

keyframe_count_hint

quality_priority

compute_priority

backend_constraints_applied

17.2 建议下游映射（示意）

frame_budget = 8 -> 轻量 workflow preset

frame_budget = 12 -> 标准 workflow preset

frame_budget = 24 -> 高质量/高动作 preset

multi_keyframe -> 启用多关键帧控制链路（若后端支持）

17.3 若后端不支持目标模式

自动降级到可用模式（记录 degrade_actions）

或标记 review_required_items

18. Prompting / Execution Constraints（给 AI 的执行约束）

不要把帧预算误当成最终视频 FPS

不要在没有 timeline_final 时输出“最终版”渲染计划

不要忽略后端拥塞状态进行大规模高负载规划

不要无记录地静默降级关键镜头

高动作镜头优先考虑微镜头拆分，而不是一味拉高帧预算

输出必须结构化，满足 visual_render_plan.json 契约

19. Example Mini Output（简化示例）
{
  "version": "1.0",
  "status": "ready_for_render_execution",
  "global_render_profile": "MEDIUM_LOAD",
  "planning_summary": {
    "total_shots": 2,
    "high_motion_shots": 1,
    "microshot_splits": 1,
    "total_microshots": 3,
    "degraded_shots": 0,
    "critical_segments_protected": 1
  },
  "resource_strategy": {
    "recommended_parallelism": 2,
    "queue_priority_mode": "critical_first",
    "preview_first": false
  },
  "shot_render_plans": [
    {
      "shot_id": "S12",
      "scene_id": "SC05",
      "start_ms": 42000,
      "end_ms": 46800,
      "duration_ms": 4800,
      "motion_complexity_score": 18,
      "motion_level": "LOW_MOTION",
      "audio_features": {
        "tts_density": 0.1,
        "sfx_events_per_sec": 0.2,
        "transient_peak_density": 0.1,
        "bgm_beat_intensity": 0.2,
        "ambience_intensity": 0.8,
        "alignment_points": [44100]
      },
      "render_strategy": {
        "frame_budget": 8,
        "i2v_mode": "start_end",
        "target_shot_duration_ms": 4800,
        "beat_alignment_strength": "low",
        "quality_priority": "medium",
        "compute_priority": "low",
        "degrade_allowed": true,
        "fallback_i2v_mode": "start_end",
        "backend_constraints_applied": []
      },
      "split_into_microshots": false,
      "criticality": "background",
      "reasoning_tags": ["sea_ambience", "low_sfx_density", "establishing_shot"],
      "warnings": []
    },
    {
      "shot_id": "S27",
      "scene_id": "SC11",
      "start_ms": 91300,
      "end_ms": 94600,
      "duration_ms": 3300,
      "motion_complexity_score": 84,
      "motion_level": "HIGH_MOTION",
      "audio_features": {
        "tts_density": 0.0,
        "sfx_events_per_sec": 3.4,
        "transient_peak_density": 2.8,
        "bgm_beat_intensity": 0.9,
        "ambience_intensity": 0.2,
        "alignment_points": [91540, 92110, 92890, 93620]
      },
      "render_strategy": {
        "frame_budget": 24,
        "i2v_mode": "start_mid_end",
        "target_shot_duration_ms": 3300,
        "beat_alignment_strength": "high",
        "quality_priority": "high",
        "compute_priority": "high",
        "degrade_allowed": false,
        "fallback_i2v_mode": "start_end",
        "backend_constraints_applied": ["critical_protection"]
      },
      "split_into_microshots": true,
      "criticality": "critical",
      "reasoning_tags": ["metal_hit_dense", "combo_attack", "fast_bgm"],
      "warnings": []
    }
  ],
  "microshot_render_plans": [
    {
      "microshot_id": "S27A",
      "parent_shot_id": "S27",
      "start_ms": 91300,
      "end_ms": 92000,
      "duration_ms": 700,
      "split_reason_tags": ["impact_peak_alignment", "combo_attack"],
      "alignment_points": [91540],
      "motion_complexity_score": 82,
      "render_strategy": {
        "frame_budget": 24,
        "i2v_mode": "start_mid_end",
        "target_shot_duration_ms": 700,
        "beat_alignment_strength": "high",
        "quality_priority": "high",
        "compute_priority": "high",
        "degrade_allowed": false,
        "fallback_i2v_mode": "start_end",
        "backend_constraints_applied": ["critical_protection"]
      },
      "criticality": "critical"
    }
  ],
  "degrade_actions": [],
  "warnings": [],
  "review_required_items": []
}
20. Integration Points（与上下游模块衔接）
上游依赖

音频工作流产物（timeline_final.json, audio_event_manifest.json）

08_ASSET_MATCHER.md 输出（素材可用性）

shot_plan.json（场景/镜头规划）

下游消费者

10_PROMPT_PLANNER.md（根据渲染策略拼接提示词/控制参数）

I2V Executor / ComfyUI Workers

Queue Scheduler / Orchestrator

Composer（用于时间线组装与最终合成）

21. Recommended Extensions（后续建议扩展）

后续可拆分为：

09.1_AUDIO_FEATURE_EXTRACTOR_RULES.md

09.2_MOTION_SCORING_MODEL.md

09.3_MICROSHOT_SPLIT_POLICY.md

09.4_BACKEND_DEGRADE_POLICY.md

09.5_COMFYUI_PRESET_MAPPING.md

22. Definition of Done（完成标准）

满足以下条件才视为本 Skill 完成：

 已确认使用 timeline_final（非 provisional）

 所有 shot 已完成音频特征聚合与动作复杂度评分

 已生成 shot 级渲染策略

 高动作片段已按规则评估是否拆分微镜头

 已应用（或明确跳过）后端负载保护策略

 已输出 visual_render_plan.json

 状态明确为 READY_FOR_RENDER_EXECUTION / REVIEW_REQUIRED / FAILED

 输出结构满足契约，便于下游执行器直接消费


---

## 你这条链现在已经很完整了（非常强）

你现在已经有这几块核心 skill 模板：

- `07_ENTITY_CANONICALIZATION_CULTURAL_BINDING.md`
- `08_ASSET_MATCHER.md`
- `09_VISUAL_RENDER_PLANNER.md` ✅

下一步最自然的就是：

### `10_PROMPT_PLANNER.md`
把这三者汇总：
- 文化约束（07）
- 素材锚点（08）
- 渲染策略/帧预算/微镜头（09）
→ 输出每个 shot / micro-shot 的最终提示词与控制参数（给 ComfyUI / 视频模型 / 图像模型）

---

## RAG 闭环衔接补充（P0）
- 本模块必须输出 `rag_retrieval_tags`：
  - `motion_level`
  - `shot_type`
  - `camera_move_type`
  - `degrade_level`
- 对高动作失败镜头输出 `feedback_anchor`，供 13 自动提案聚类。
- 若触发降级，记录 `degrade_reason` 与 `degrade_policy_id`，用于后续知识迭代。

