# 21_ENTITY_REGISTRY_CONTINUITY_MANAGER.md
# Entity Registry & Continuity Manager（实体注册表与连续性管理 Skill 模板｜中文版）

## 0. 文档定位
本 Skill 用于解决工业级一致性问题：
- 人物 ID 固定
- 场景 ID 固定
- 道具 ID 固定
- 世界模型中的 canonical identity 长期稳定
- 跨章节 / 跨 scene / 跨 shot / 跨任务的连续性维护

该模块承接 `04_ENTITY_EXTRACTION_STRUCTURING.md`，并在 `07_ENTITY_CANONICALIZATION_CULTURAL_BINDING.md` 之前工作。
它是人物一致性、场景一致性、道具一致性的“主档案层 / Continuity Bible”。

---

## 1. Workflow Goal（目标）
实现以下核心能力：
1. 对抽取出来的实体做“已有实体链接（entity linking）”
2. 若命中已有实体，则绑定固定 `entity_id`
3. 若未命中，则创建新实体主档案
4. 维护 Character / Scene / Prop 的 Continuity Profile
5. 输出一致性锚点，供后续 `08/10/16` 使用
6. 支持世界模型转换后的 identity 保持（world_model_id -> entity_id）

---

## 2. Concepts（核心概念）

### 2.1 Canonical Entity ID（本体固定ID）
长生命周期身份，不随镜头变化：
- `CHAR_0001`
- `SCENE_0007`
- `PROP_0012`

### 2.2 Instance ID（镜头实例ID）
同一实体在某个 shot 中的实例：
- `SHOT_S27_CHAR_0001_INST_01`
- `SHOT_S27_PROP_0012_INST_02`

### 2.3 Continuity Profile（连续性主档案）
用于保持一致性的档案，包含：
- 视觉锚点
- 名称/别名
- 服装/发型/武器/空间布局
- 连续性规则
- 允许变化与禁止变化项

### 2.4 Entity Linking（实体链接）
判断当前抽取到的实体是否已存在于注册表中，避免重复创建。

---

## 3. Inputs（输入）

### 3.1 必需输入
- `entity_extraction_result.json`（来自 04）
- `shot_plan.json`（来自 03）

### 3.2 可选输入
- `normalized_story.json`（来自 01）
- `language_context_routing.json`（来自 02）
- `world_model_context`（如果你有世界模型转换层）
- `existing_entity_registry`
- `feature_flags`
  - enable_entity_linking
  - enable_instance_tracking
  - enable_continuity_rules
  - enable_world_model_link

---

## 4. Outputs（输出）
### 4.1 主输出文件
- `entity_registry_resolution.json`

### 4.2 输出内容必须包含
1. `status`
2. `registry_actions[]`
3. `resolved_entities[]`
4. `created_entities[]`
5. `entity_instance_links[]`
6. `continuity_profiles[]`
7. `link_conflicts[]`
8. `warnings[]`
9. `review_required_items[]`

---

## 5. Branching Logic（分支流程与判断）

### [ER1] Precheck（预检查）
#### Trigger
收到 04 抽取结果
#### Actions
1. 检查 `entity_extraction_result.status`
2. 加载现有 entity registry
3. 检查 shot_plan 最小结构
#### Output
- `precheck_status`

---

### [ER2] Entity Linking（实体链接）
#### Trigger
预检查通过
#### Actions
1. 对每个 extracted entity 做链接尝试
2. 匹配信号可包含：
   - 名称/别名相似度
   - 已有 world_model_id
   - 场景关系/所属角色
   - 特征签名（武器/服装/地点特征）
3. 输出：
   - linked_to_existing = true/false
   - confidence
   - matched_entity_id
4. 低置信度进入 review
#### Output
- `resolved_entities[]`
- `link_conflicts[]`

---

### [ER3] Entity Creation（新建实体）
#### Trigger
实体未命中已有 registry
#### Actions
1. 生成新 `entity_id`
2. 写入基础 registry entry
3. 生成初始 continuity profile（如果信息足够）
#### Output
- `created_entities[]`

---

### [ER4] Instance Tracking（实例追踪）
#### Trigger
实体已解决（链接或新建）
#### Actions
1. 为每个 scene/shot 出场生成 instance link
2. 记录首次出场、当前状态、归属关系
3. 将角色-道具-场景关系写入 continuity graph
#### Output
- `entity_instance_links[]`

---

### [ER5] Continuity Profile Update（连续性主档案更新）
#### Trigger
实体已绑定
#### Actions
1. 若已有 continuity profile：增量更新
2. 若无：创建 profile
3. 写入 anchor / rules / allowed variations
4. 记录是否需要人工确认（例如人物形象描述不足）
#### Output
- `continuity_profiles[]`

---

### [ER6] Export Continuity Anchors（导出一致性锚点）
#### Trigger
完成 registry 绑定后
#### Actions
1. 输出给 `08_ASSET_MATCHER` 的固定 scene/prop/character anchors
2. 输出给 `10_PROMPT_PLANNER` 的 consistency anchors
3. 输出给 `16_CRITIC` 的 continuity rules baseline
#### Output
- continuity exports

---

## 6. Output Contract（示例）
```json
{
  "version": "1.0",
  "status": "continuity_ready",
  "registry_actions": {
    "linked_existing": 5,
    "created_new": 2,
    "review_needed": 1
  },
  "resolved_entities": [
    {
      "source_entity_uid": "E01",
      "linked_to_existing": true,
      "matched_entity_id": "CHAR_0001",
      "confidence": 0.94
    }
  ],
  "created_entities": [
    {
      "source_entity_uid": "E12",
      "new_entity_id": "PROP_0043",
      "entity_type": "prop"
    }
  ],
  "entity_instance_links": [
    {
      "instance_id": "SHOT_S27_CHAR_0001_INST_01",
      "entity_id": "CHAR_0001",
      "shot_id": "S27",
      "scene_id": "SC05"
    }
  ],
  "continuity_profiles": [],
  "link_conflicts": [],
  "warnings": [],
  "review_required_items": []
}
```

---

## 7. Integration Points（接入点）
- 上游：`04_ENTITY_EXTRACTION_STRUCTURING`
- 下游：
  - `07_ENTITY_CANONICALIZATION_CULTURAL_BINDING`
  - `08_ASSET_MATCHER`
  - `10_PROMPT_PLANNER`
  - `16_CRITIC_EVALUATION_SUITE`

---

## 8. Definition of Done（完成标准）
- [ ] 实体可链接已有 registry 或创建新 entity_id
- [ ] 人物/场景/道具具备固定 canonical ID
- [ ] 可生成 shot/scene 实例关系
- [ ] 可输出 continuity anchors 给后续模块
