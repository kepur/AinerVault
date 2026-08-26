# 04_ENTITY_EXTRACTION_STRUCTURING.md
# Entity Extraction & Structuring（实体抽取与结构化 Skill 模板｜中文版）

## 0. 文档定位
本 Skill 承接 `03_STORY_SCENE_SHOT_PLANNER.md` 的 scene/shot 规划结果，
从故事文本、场景规划、镜头提示中抽取可用于后续文化绑定与素材匹配的实体，并输出结构化实体对象。

> 本模块负责“抽取与结构化”，不负责最终 canonicalization（07）与文化绑定。

---

## 术语对齐声明（固定模板）
- 本文统一运行对象命名：`run / job / stage / event / artifact`。
- `run`：一次端到端业务运行；`job`：run 内原子执行单元；`stage`：run 阶段状态。
- `event`：跨模块事实消息，统一采用 `EventEnvelope`；`artifact`：可回溯产物元数据。
- `worker.*.completed` 为执行明细事件，不替代 `job.succeeded / job.failed` 主状态事件。
- `step` 仅表示内部步骤序号，不作为运行态主对象或事件前缀。
- 必带治理字段：`tenant_id / project_id / trace_id / correlation_id / idempotency_key / schema_version`。

## 1. Workflow Goal（目标）
输出统一的实体抽取结果，包含：
- 人物（角色）
- 场景（地点/空间）
- 道具（物件/武器/交通工具等）
- 服饰（服装/配件）
- 音频事件候选（可选：风/雨/金属碰撞等）
- 实体与 scene/shot 的关联关系
- 实体重要性等级与首次出现信息

输出供下游：
- `07_ENTITY_CANONICALIZATION_CULTURAL_BINDING.md`
- `08_ASSET_MATCHER.md`（通过 07 后）
- 音频规划（可参考事件候选）

---

## 2. Inputs（输入）
### 2.1 必需输入
- `normalized_story.json`（来自 01）
- `shot_plan.json`（来自 03）

### 2.2 可选输入
- `language_context_routing.json`（来自 02）
- `story_context`
- `user_overrides`
- `feature_flags`
  - `enable_audio_event_candidate_extraction`
  - `enable_entity_alias_resolution`
  - `enable_confidence_scores`

---

## 3. Outputs（输出）
### 3.1 主输出文件
- `entity_extraction_result.json`

### 3.2 必需字段
1. `status`
2. `entity_summary`
3. `entities[]`
4. `entity_aliases[]`
5. `entity_scene_shot_links[]`
6. `audio_event_candidates[]`（如启用）
7. `warnings[]`
8. `review_required_items[]`

---

## 4. Entity Types（实体类型建议）
- `character`
- `scene_place`
- `prop`
- `costume`
- `vehicle`
- `creature`
- `symbol_signage`
- `fx_event_candidate`（可选）
- `audio_event_candidate`（可选）

---

## 5. Branching Logic（分支流程与判断）

### [E1] Precheck（预检查）
#### Actions
1. 检查 01/03 状态
2. 检查 shot_plan 是否存在最小结构（scene + shot）
3. 读取段落与镜头对应关系（若有）
#### Output
- `precheck_status`

---

### [E2] Candidate Extraction（实体候选抽取）
#### Actions
1. 从文本段落抽取实体候选
2. 从 shot/entity_hints 中补充实体候选
3. 从 audio_hints 中生成事件候选（可选）
4. 保留原文片段与来源位置
#### Output
- `raw_entity_candidates[]`

---

### [E3] Structuring & Typing（结构化与类型判定）
#### Actions
1. 为候选实体分配类型（character/prop/...）
2. 生成标准结构字段：
   - `entity_uid`
   - `surface_form`
   - `entity_type`
   - `attributes`
   - `source_refs`
3. 标记置信度与不确定项
#### Output
- `entities[]`

---

### [E4] Alias & Duplicate Handling（别名与去重）
#### Actions
1. 检测同一实体多种称呼（如“他/少侠/林某”）
2. 合并明显重复实体
3. 输出 alias 映射，不做文化层面的最终归一
#### Output
- `entity_aliases[]`

---

### [E5] Scene/Shot Linking（与场景镜头关联）
#### Actions
1. 将实体关联到 scene / shot
2. 标记首次出场、关键镜头出场
3. 生成实体重要性（critical/important/normal/background）
#### Output
- `entity_scene_shot_links[]`

---

## 6. State Machine（状态机）
States:
- INIT
- PRECHECKING
- EXTRACTING_CANDIDATES
- STRUCTURING_ENTITIES
- MERGING_ALIASES
- LINKING_TO_SCENES_SHOTS
- READY_FOR_CANONICALIZATION
- REVIEW_REQUIRED
- FAILED

---

## 7. Output Contract（输出契约）
```json
{
  "version": "1.0",
  "status": "ready_for_canonicalization",
  "entity_summary": {
    "total_entities": 18,
    "characters": 4,
    "scene_places": 3,
    "props": 6,
    "costumes": 3,
    "audio_event_candidates": 7
  },
  "entities": [
    {
      "entity_uid": "E01",
      "surface_form": "客栈大堂",
      "entity_type": "scene_place",
      "attributes": {
        "descriptors": ["木结构", "灯笼", "江湖客栈"]
      },
      "source_refs": [{"segment_id": "SEG_03"}],
      "confidence": 0.93
    }
  ],
  "entity_aliases": [
    {
      "alias_group_id": "A01",
      "canonical_hint": "主角A",
      "members": ["少侠", "他", "林某"]
    }
  ],
  "entity_scene_shot_links": [
    {
      "entity_uid": "E01",
      "scene_ids": ["SC01"],
      "shot_ids": ["S01", "S02"],
      "first_appearance_shot_id": "S01",
      "criticality": "important"
    }
  ],
  "audio_event_candidates": [
    {"event_type": "metal_hit", "source_shot_id": "S12", "confidence": 0.64}
  ],
  "warnings": [],
  "review_required_items": []
}
```

---

## 8. Definition of Done（完成标准）
- [ ] 已完成实体候选抽取与结构化
- [ ] 已处理基础 alias / 重复项
- [ ] 已关联到 scene/shot
- [ ] 已输出 `READY_FOR_CANONICALIZATION` / `REVIEW_REQUIRED` / `FAILED`
