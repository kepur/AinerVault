# 03_STORY_SCENE_SHOT_PLANNER.md
# Story → Scene → Shot Planner（故事到场景到镜头规划 Skill 模板｜中文版）

## 0. 文档定位
本 Skill 承接 `01`（故事规范化）与 `02`（语言/上下文路由）输出，
将文本内容按叙事与视听表达需求拆解为：
- 场景（Scene）
- 镜头（Shot）
- 初步镜头目的与时长估计
- 角色/场景/动作出场关系
- 音频与视觉规划提示（供后续 07/08/09 使用）

> 本模块是“叙事规划与镜头草案层”，不是最终音频时间线，也不是最终渲染计划。

---

## 术语对齐声明（固定模板）
- 本文统一运行对象命名：`run / job / stage / event / artifact`。
- `run`：一次端到端业务运行；`job`：run 内原子执行单元；`stage`：run 阶段状态。
- `event`：跨模块事实消息，统一采用 `EventEnvelope`；`artifact`：可回溯产物元数据。
- `worker.*.completed` 为执行明细事件，不替代 `job.succeeded / job.failed` 主状态事件。
- `step` 仅表示内部步骤序号，不作为运行态主对象或事件前缀。
- 必带治理字段：`tenant_id / project_id / trace_id / correlation_id / idempotency_key / schema_version`。

## 1. Workflow Goal（目标）
把章节/段落级故事内容转换为结构化的 Scene/Shot 计划，输出：
- 场景列表与边界（scene segmentation）
- 每个场景的叙事功能（推进剧情/对白/动作/氛围）
- 镜头列表与镜头目的（建立/对话/特写/动作/转场）
- 初步时长估计（provisional timing）
- 实体需求提示（供 07/08）
- 音频事件预判提示（对白密集/风雨/打斗/金属碰撞等，供 09 前置参考）

---

## 2. Inputs（输入）
### 2.1 必需输入
- `normalized_story.json`（来自 01）
- `language_context_routing.json`（来自 02）

### 2.2 可选输入
- `story_context`（章节摘要、人物关系）
- `user_overrides`
  - 指定镜头风格、节奏、是否偏长镜头
- `project_defaults`
  - 默认镜头长度范围、默认镜头语言偏好
- `feature_flags`
  - `enable_provisional_timing`
  - `enable_audio_event_pre_hints`
  - `enable_parallel_task_grouping`

---

## 3. Outputs（输出）
### 3.1 主输出文件
- `shot_plan.json`

### 3.2 必需字段
1. `status`
2. `scene_plan[]`
3. `shot_plan[]`
4. `provisional_timeline`
5. `entity_extraction_hints`
6. `audio_pre_hints`
7. `parallel_task_groups`
8. `warnings[]`
9. `review_required_items[]`

---

## 4. Planning Principles（规划原则）
1. 先按叙事语义切场景，再切镜头
2. 镜头服务叙事目标，不为切而切
3. 高动作段可预判后续需要更细镜头密度（供 09 进一步拆微镜头）
4. 对白真实时长未确定前，仅输出 provisional timing
5. 为后续 07/08/09 预留结构化提示，不在本模块做过深实现细节

---

## 5. Branching Logic（分支流程与判断）

### [S1] Precheck（预检查）
#### Actions
1. 检查 01/02 状态是否允许继续
2. 检查文本结构是否足够进行 scene 分解
3. 读取 culture/planner hints（来自 02）
#### Output
- `precheck_status`

---

### [S2] Scene Segmentation（场景切分）
#### Actions
1. 按地点变化、时间变化、叙事目的变化切分 scene
2. 为每个 scene 标注：
   - `scene_goal`（叙事目的）
   - `scene_type`（对白/动作/氛围/过渡）
   - `scene_location_hint`
   - `emotion_tone`
3. 输出 scene 边界和关联文本范围
#### Output
- `scene_plan[]`

---

### [S3] Shot Planning（镜头规划）
#### Actions
1. 对每个 scene 生成镜头序列（shot list）
2. 标注镜头类型：
   - establishing / wide / medium / close-up / insert / action / transition
3. 标注镜头目的：
   - 交代空间 / 展现动作 / 强化情绪 / 承接对白 / 节奏过渡
4. 生成初步时长估计（provisional）
5. 标记关键镜头与关键角色出场
#### Output
- `shot_plan[]`

---

### [S4] Provisional Timing（初步时长估计）
#### Actions
1. 根据对白段落长度、动作密度、氛围镜头需求估计时长
2. 输出 scene/shot 级 provisional 时间线
3. 标注“需 TTS 实长回填”的镜头
#### Output
- `provisional_timeline`

---

### [S5] Entity & Audio Hints Export（实体与音频预判提示导出）
#### Actions
1. 提取实体需求提示（人物/场景/道具/服饰）
2. 提取音频预判提示：
   - 对白密集
   - 风/雨/海浪
   - 打斗/金属碰撞
   - 环境乐需求
3. 为后续并发任务分组（例如实体抽取、音频规划、素材匹配准备）
#### Output
- `entity_extraction_hints`
- `audio_pre_hints`
- `parallel_task_groups`

---

## 6. Parallel Task Grouping（并发任务分组建议）
在本模块输出后，可并发启动（示例）：
- Group A: 实体抽取 / 规范化准备（→ 07）
- Group B: TTS / 对白规划
- Group C: SFX/BGM/Ambience 初步规划
- Group D: 素材库预热检索（可选）

> 最终以 TTS 实长回填后再进入正式音频总线与 09。

---

## 7. State Machine（状态机）
States:
- INIT
- PRECHECKING
- SEGMENTING_SCENES
- PLANNING_SHOTS
- ESTIMATING_TIMING
- EXPORTING_HINTS
- READY_FOR_PARALLEL_EXECUTION
- REVIEW_REQUIRED
- FAILED

---

## 8. Output Contract（输出契约）
```json
{
  "version": "1.0",
  "status": "ready_for_parallel_execution",
  "scene_plan": [
    {
      "scene_id": "SC01",
      "scene_goal": "establish_location_and_tension",
      "scene_type": "atmosphere_dialogue",
      "scene_location_hint": "wuxia_inn_hall",
      "emotion_tone": "tense",
      "source_range": {"segment_start": 0, "segment_end": 4}
    }
  ],
  "shot_plan": [
    {
      "shot_id": "S01",
      "scene_id": "SC01",
      "shot_type": "establishing",
      "shot_goal": "establish_inn_space",
      "criticality": "important",
      "provisional_duration_ms": 3500,
      "characters_present": [],
      "entity_hints": ["inn hall", "lanterns", "wooden tables"],
      "audio_hints": ["wind ambience", "indoor crowd murmur low"]
    }
  ],
  "provisional_timeline": {
    "total_duration_estimate_ms": 28600,
    "is_final": false,
    "requires_tts_backfill": true
  },
  "entity_extraction_hints": {
    "focus_entities": ["characters", "scene architecture", "weapons", "costumes"],
    "culture_hint_from_router": "cn_wuxia"
  },
  "audio_pre_hints": [
    {"scene_id": "SC01", "hint": "dialogue_heavy"},
    {"scene_id": "SC02", "hint": "metal_hit_possible"}
  ],
  "parallel_task_groups": [
    {"group_id": "G_A", "tasks": ["entity_extraction_prepare"]},
    {"group_id": "G_B", "tasks": ["tts_planning", "dialogue_speaker_split"]},
    {"group_id": "G_C", "tasks": ["sfx_bgm_ambience_planning"]}
  ],
  "warnings": [],
  "review_required_items": []
}
```

---

## 9. Decision Table（关键判断表）
| 条件 | 动作 |
|---|---|
| 文本主要为对白且场景变化少 | 减少场景切分，增加对话镜头规划 |
| 连续动作描述密集 | 提高镜头密度，并标记后续 09 高动作候选 |
| 文本信息不足以明确空间 | 输出 `scene_location_hint=unknown` + warning |
| 仅有大纲无细节 | 输出粗粒度 scene/shot 草案，标记 review |

---

## 10. Definition of Done（完成标准）
- [ ] 已完成 scene 切分
- [ ] 已完成 shot 级规划与初步时长估计
- [ ] 已导出实体提示与音频预判提示
- [ ] 已输出并发任务分组建议
- [ ] 状态明确为 `READY_FOR_PARALLEL_EXECUTION` / `REVIEW_REQUIRED` / `FAILED`
