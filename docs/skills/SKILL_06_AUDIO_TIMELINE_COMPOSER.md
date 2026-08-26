# 06_AUDIO_TIMELINE_COMPOSER.md
# Audio Timeline Composer（音频时间线合成与回填 Skill 模板｜中文版）

## 0. 文档定位
本 Skill 承接 `05_AUDIO_ASSET_PLANNER.md` 的音频任务规划，以及各音频执行器产出的实际结果（尤其 TTS 实际时长），
完成最终音频时间线编排、轨道对齐、混合策略规划，并输出 `timeline_final.json` 与 `audio_event_manifest.json`。

> 本模块输出“最终音频时间线计划/合成结果契约”，供 09 视觉渲染规划使用。

---

## 术语对齐声明（固定模板）
- 本文统一运行对象命名：`run / job / stage / event / artifact`。
- `run`：一次端到端业务运行；`job`：run 内原子执行单元；`stage`：run 阶段状态。
- `event`：跨模块事实消息，统一采用 `EventEnvelope`；`artifact`：可回溯产物元数据。
- `worker.*.completed` 为执行明细事件，不替代 `job.succeeded / job.failed` 主状态事件。
- `step` 仅表示内部步骤序号，不作为运行态主对象或事件前缀。
- 必带治理字段：`tenant_id / project_id / trace_id / correlation_id / idempotency_key / schema_version`。

## 1. Workflow Goal（目标）
完成以下关键动作：
- 回填 TTS 实际时长到 shot/scene 时间线
- 对齐 BGM / SFX / Ambience 到最终时间轴
- 生成统一音频轨道结构（dialogue / ambience / sfx / bgm）
- 输出最终时间线（timeline_final）
- 输出音频事件清单（audio_event_manifest）供 09 做动作复杂度分析
- 输出混音/合成建议（非必须实际渲染）

---

## 2. Inputs（输入）
### 2.1 必需输入
- `audio_plan.json`（来自 05）
- 音频执行结果（TTS/BGM/SFX/Ambience）
  - 实际路径/引用
  - 实际时长
  - 可选峰值/节拍分析数据
- `shot_plan.json`（来自 03）

### 2.2 可选输入
- `entity_extraction_result.json`（来自 04）
- `mix_profile`
- `backend_audio_composer_capability`
- `feature_flags`
  - `enable_peak_analysis_import`
  - `enable_beat_detection_import`
  - `enable_auto_ducking_plan`

---

## 3. Outputs（输出）
### 3.1 主输出文件
- `timeline_final.json`
- `audio_event_manifest.json`

### 3.2 必需字段
#### timeline_final
- `status`
- `final_duration_ms`
- `tracks`
- `scene_timeline`
- `shot_timeline`
- `mix_hints`
- `warnings[]`

#### audio_event_manifest
- `events[]`
- `summary`
- `analysis_hints_for_visual_render`

---

## 4. Track Model（轨道模型建议）
推荐轨道（可扩展）：
1. `dialogue`
2. `ambience`
3. `sfx`
4. `bgm`
5. `aux`（可选，过门/特殊效果）

---

## 5. Branching Logic（分支流程与判断）

### [C1] Precheck（预检查）
#### Actions
1. 检查 `audio_plan.status`
2. 检查关键音频执行结果是否齐全（尤其 TTS）
3. 检查音频文件时长元数据可用
4. 若缺关键结果，决定 REVIEW / 部分合成模式
#### Output
- `precheck_status`

---

### [C2] TTS Duration Backfill（TTS时长回填）
#### Actions
1. 将 TTS 实际时长回填到对白片段
2. 更新 shot/scene provisional timeline
3. 标记时长变化引起的后续偏移量
#### Output
- 更新后的内部时间轴
- `backfill_report`

---

### [C3] Track Placement（轨道放置与对齐）
#### Actions
1. 放置 dialogue 轨（以 TTS 实长为准）
2. 放置 ambience 轨（场景级铺底）
3. 放置 SFX 轨（事件级/候选点位精对齐）
4. 放置 BGM 轨（段落级/场景级）
5. 处理淡入淡出、重叠、间隙
#### Output
- `tracks`
- `scene_timeline`
- `shot_timeline`

---

### [C4] Event Manifest Build（音频事件清单构建）
#### Actions
1. 提取事件级列表（对白、SFX、峰值、节拍、转场）
2. 生成强度与密度统计
3. 为 09 输出视觉规划提示（高动作候选、平静段等）
#### Output
- `audio_event_manifest.json`

---

### [C5] Mix Hint Export（混音提示导出）
#### Actions
1. 输出 ducking 建议（对白期间压低 BGM）
2. 输出关键打击点强调建议
3. 输出氛围轨层次建议
#### Output
- `mix_hints`
- `warnings[]`

---

## 6. State Machine（状态机）
States:
- INIT
- PRECHECKING
- BACKFILLING_TTS_DURATIONS
- PLACING_TRACKS
- BUILDING_EVENT_MANIFEST
- EXPORTING_MIX_HINTS
- READY_FOR_VISUAL_RENDER_PLANNING
- REVIEW_REQUIRED
- FAILED

---

## 7. Output Contract（输出契约）

### 7.1 `timeline_final.json`（示例）
```json
{
  "version": "1.0",
  "status": "ready_for_visual_render_planning",
  "final_duration_ms": 47200,
  "tracks": {
    "dialogue": [
      {
        "clip_id": "DIA_001",
        "tts_task_id": "TTS_001",
        "start_ms": 3200,
        "end_ms": 4680,
        "speaker_id": "CHAR_LEAD_01",
        "audio_ref": "asset://tts/TTS_001.wav"
      }
    ],
    "ambience": [
      {
        "clip_id": "AMB_001",
        "start_ms": 0,
        "end_ms": 18000,
        "audio_ref": "asset://amb/AMB_001.wav",
        "fade_in_ms": 600,
        "fade_out_ms": 800
      }
    ],
    "sfx": [
      {
        "clip_id": "SFX_012_01",
        "sfx_task_id": "SFX_012",
        "start_ms": 22140,
        "end_ms": 22420,
        "event_type": "metal_hit",
        "audio_ref": "asset://sfx/SFX_012_hit.wav"
      }
    ],
    "bgm": [
      {
        "clip_id": "BGM_001",
        "start_ms": 0,
        "end_ms": 31500,
        "audio_ref": "asset://bgm/BGM_001.wav",
        "ducking_profile": "dialogue_priority"
      }
    ]
  },
  "scene_timeline": [],
  "shot_timeline": [],
  "mix_hints": {
    "ducking": [{"during_track": "dialogue", "target_track": "bgm", "gain_reduction_db": -6}],
    "impact_emphasis": [{"event_type": "metal_hit", "hint": "transient_clarity_priority"}]
  },
  "warnings": []
}
```

### 7.2 `audio_event_manifest.json`（示例）
```json
{
  "version": "1.0",
  "summary": {
    "dialogue_events": 14,
    "sfx_events": 29,
    "bgm_segments": 4,
    "ambience_segments": 5,
    "high_intensity_windows": 3
  },
  "events": [
    {
      "event_id": "AE_001",
      "event_type": "dialogue",
      "start_ms": 3200,
      "end_ms": 4680,
      "intensity": 0.4,
      "shot_id": "S02"
    },
    {
      "event_id": "AE_102",
      "event_type": "metal_hit",
      "start_ms": 22140,
      "end_ms": 22420,
      "intensity": 0.9,
      "shot_id": "S12",
      "transient_peak": true
    }
  ],
  "analysis_hints_for_visual_render": {
    "high_motion_candidate_shots": ["S12", "S13"],
    "low_motion_ambience_shots": ["S01"],
    "dialogue_heavy_shots": ["S02", "S03"]
  }
}
```

---

## 8. Decision Table（关键判断表）
| 条件 | 动作 |
|---|---|
| TTS 结果缺失 | 不可生成 final timeline，进入 REVIEW 或 partial mode |
| BGM/SFX 部分缺失 | 可生成 final timeline（带 placeholder/warning） |
| TTS 实长导致 scene 超长 | 回填并记录偏移；供后续模块按 final 时间处理 |
| 峰值/节拍分析不可用 | 仍输出 event manifest，但降低分析精度 |

---

## 9. Definition of Done（完成标准）
- [ ] 已完成 TTS 实长回填
- [ ] 已完成 dialogue / ambience / sfx / bgm 轨道对齐
- [ ] 已输出 `timeline_final.json`
- [ ] 已输出 `audio_event_manifest.json`
- [ ] 状态明确为 `READY_FOR_VISUAL_RENDER_PLANNING` / `REVIEW_REQUIRED` / `FAILED`
