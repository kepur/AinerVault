# 05_AUDIO_ASSET_PLANNER.md
# Audio Asset Planner（音频规划 Skill 模板｜中文版）

## 0. 文档定位
本 Skill 承接 `03_STORY_SCENE_SHOT_PLANNER.md` 的镜头规划与音频预判提示，
以及（可选）`04_ENTITY_EXTRACTION_STRUCTURING.md` 的音频事件候选，
负责规划 TTS / BGM / SFX / Ambience 的生成与匹配任务，但此时仍是“规划层”，不做最终混音。

> 本模块输出音频任务清单与初步时间规划，供执行器与 06 使用。

---

## 术语对齐声明（固定模板）
- 本文统一运行对象命名：`run / job / stage / event / artifact`。
- `run`：一次端到端业务运行；`job`：run 内原子执行单元；`stage`：run 阶段状态。
- `event`：跨模块事实消息，统一采用 `EventEnvelope`；`artifact`：可回溯产物元数据。
- `worker.*.completed` 为执行明细事件，不替代 `job.succeeded / job.failed` 主状态事件。
- `step` 仅表示内部步骤序号，不作为运行态主对象或事件前缀。
- 必带治理字段：`tenant_id / project_id / trace_id / correlation_id / idempotency_key / schema_version`。

## 1. Workflow Goal（目标）
输出：
- TTS 任务规划（按角色/对白片段）
- BGM 规划（场景级/段落级）
- SFX 规划（事件级）
- Ambience 规划（场景级环境音）
- 音频任务依赖关系
- 初步时间线（provisional）
- 并发执行组（TTS/SFX/BGM可并行部分）

后续：
- 06 执行音频合成与时间线回填
- 09 使用最终音频时间线做视觉渲染规划

---

## 2. Inputs（输入）
### 2.1 必需输入
- `shot_plan.json`（来自 03）
- `global_audio_profile`（LOW/MEDIUM/HIGH 或 preview/standard/final）

### 2.2 可选输入
- `entity_extraction_result.json`（来自 04）
- `voice_cast_profile`
- `music_style_profile`
- `backend_audio_capability`
- `user_overrides`
- `feature_flags`
  - `enable_sfx_auto_density`
  - `enable_ambience_scene_layers`
  - `enable_parallel_audio_groups`

---

## 3. Outputs（输出）
### 3.1 主输出文件
- `audio_plan.json`

### 3.2 必需字段
1. `status`
2. `tts_plan[]`
3. `bgm_plan[]`
4. `sfx_plan[]`
5. `ambience_plan[]`
6. `audio_task_dag`
7. `provisional_audio_timeline`
8. `parallel_audio_groups[]`
9. `warnings[]`

---

## 4. Planning Principles（规划原则）
1. TTS 实长优先决定最终对白时间线（后续 06 回填）
2. BGM/SFX/Ambience 在当前阶段做“预铺设规划”
3. 高动作镜头预留更密集 SFX 槽位，但不在本阶段定最终精确点位
4. 场景连续时可复用 ambience/BGM motif，减少重复生成与负载
5. 输出 DAG，明确哪些任务必须等待 TTS 结果

---

## 5. Branching Logic（分支流程与判断）

### [A1] Precheck（预检查）
#### Actions
1. 检查 03 状态
2. 读取 scene/shot 与 audio_hints
3. 读取音频全局档位与后端能力
#### Output
- `precheck_status`

---

### [A2] TTS Planning（对白语音规划）
#### Actions
1. 按 scene/shot 拆分对白片段
2. 分配 speaker（角色）
3. 生成 TTS task（文本、角色、情绪、语速建议）
4. 标记必须先执行（影响最终时长）
#### Output
- `tts_plan[]`

---

### [A3] BGM Planning（背景音乐规划）
#### Actions
1. 按场景情绪与叙事功能规划 BGM 段
2. 标注风格、强度、入点/出点（provisional）
3. 高动作段可标记节奏增强
#### Output
- `bgm_plan[]`

---

### [A4] SFX / Ambience Planning（音效/环境音规划）
#### Actions
1. 根据 shot `audio_hints` 和实体事件候选规划 SFX
2. 根据 scene 类型规划 ambience（风/雨/海浪/室内人声底噪等）
3. 标注密度等级（low/medium/high）
#### Output
- `sfx_plan[]`
- `ambience_plan[]`

---

### [A5] Audio DAG & Parallel Groups（任务依赖与并发分组）
#### Actions
1. 构建音频任务 DAG：
   - TTS → 时间线回填（06）
   - BGM/SFX/Ambience 可先生成或匹配，再在 06 精确对齐
2. 输出并发组
3. 标记关键依赖
#### Output
- `audio_task_dag`
- `parallel_audio_groups[]`
- `provisional_audio_timeline`

---

## 6. State Machine（状态机）
States:
- INIT
- PRECHECKING
- PLANNING_TTS
- PLANNING_BGM
- PLANNING_SFX_AMBIENCE
- BUILDING_AUDIO_DAG
- READY_FOR_AUDIO_EXECUTION
- REVIEW_REQUIRED
- FAILED

---

## 7. Output Contract（输出契约）
```json
{
  "version": "1.0",
  "status": "ready_for_audio_execution",
  "tts_plan": [
    {
      "tts_task_id": "TTS_001",
      "scene_id": "SC01",
      "shot_id": "S02",
      "speaker_id": "CHAR_LEAD_01",
      "text": "你终于来了。",
      "emotion_hint": "tense_low",
      "speed_hint": "normal",
      "must_complete_before_final_timeline": true
    }
  ],
  "bgm_plan": [
    {
      "bgm_task_id": "BGM_001",
      "scene_id": "SC01",
      "mood": "tense_wuxia",
      "intensity": "medium",
      "provisional_start_ref": "SC01_START",
      "provisional_end_ref": "SC01_END"
    }
  ],
  "sfx_plan": [
    {
      "sfx_task_id": "SFX_012",
      "shot_id": "S12",
      "event_type": "metal_hit",
      "density_hint": "high",
      "timing_mode": "provisional_anchor_then_refine"
    }
  ],
  "ambience_plan": [
    {
      "amb_task_id": "AMB_001",
      "scene_id": "SC01",
      "ambience_type": "indoor_inn_murmur_wind_leak",
      "layering_hint": "low_medium"
    }
  ],
  "audio_task_dag": {
    "nodes": ["TTS_001", "BGM_001", "SFX_012", "AMB_001", "AUDIO_TIMELINE_FINALIZE"],
    "edges": [
      ["TTS_001", "AUDIO_TIMELINE_FINALIZE"],
      ["BGM_001", "AUDIO_TIMELINE_FINALIZE"],
      ["SFX_012", "AUDIO_TIMELINE_FINALIZE"],
      ["AMB_001", "AUDIO_TIMELINE_FINALIZE"]
    ]
  },
  "provisional_audio_timeline": {
    "is_final": false,
    "requires_tts_duration_backfill": true
  },
  "parallel_audio_groups": [
    {"group_id": "PA1", "tasks": ["TTS_001"]},
    {"group_id": "PA2", "tasks": ["BGM_001", "AMB_001"]},
    {"group_id": "PA3", "tasks": ["SFX_012"]}
  ],
  "warnings": []
}
```

---

## 8. Definition of Done（完成标准）
- [ ] 已生成 TTS/BGM/SFX/Ambience 规划
- [ ] 已输出音频任务 DAG 与并发分组
- [ ] 已标记 TTS 实长回填依赖
- [ ] 状态明确为 `READY_FOR_AUDIO_EXECUTION` / `REVIEW_REQUIRED` / `FAILED`
