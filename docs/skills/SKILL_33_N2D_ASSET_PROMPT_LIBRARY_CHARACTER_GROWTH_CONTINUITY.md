# SKILL 33 — 素材提示词库与角色成长一致性
# N2D Asset Prompt Library & Character Growth Continuity

## 0. 文档定位

本 Skill 在已有 Entity Registry (21) + Asset Matcher (08) + Prompt Planner (10) + Asset Library (29) 基础上，
引入四层结构化语义资产模型，将人物从"静态 prompt 文案"改造为：

1. **Character Core** — 角色本体不可变特征（承接 EntityContinuityProfile.anchors_json）
2. **Character Stage** — 角色成长阶段（按章节范围驱动外貌/气质/服装/道具变化）
3. **Shot State Override** — 镜头级状态覆盖（脏污/伤痕/出汗/特殊表情等临时状态）
4. **Prompt Snapshot** — 实际拼装留档（与 PromptPlan 区分，snapshot 是已生成的不可变快照）

核心原则：
- Entity 仍然是 canonical root，不另建平行系统
- Character Core 优先从 EntityContinuityProfile.anchors_json / rules_json 承接
- 服装/表情/动作/道具/场景/氛围必须资产化（SemanticAsset），不塞自然语言
- Stage 不覆盖 Core，Override 不污染 Stage

## 1. Workflow Goal

### 输入
- entity_registry_resolution.json（来自 21）
- entity_canonicalization_result.json（来自 07）
- shot_plan.json（来自 03）
- chapter.script_json / chapter.world_model_json
- 现有 EntityContinuityProfile
- 现有 SemanticAsset / CharacterStageProfile / PromptSnapshot
- optional user_overrides

### 输出
- prompt_asset_context.json

### 输出结构
```json
{
  "status": "READY_FOR_ASSET_MATCH_AND_PROMPT_PLANNER",
  "character_core_profiles": [],
  "character_stage_profiles": [],
  "semantic_assets": [],
  "shot_asset_bindings": [],
  "prompt_snapshot_seeds": [],
  "consistency_rules": [],
  "warnings": [],
  "review_required_items": []
}
```

## 2. 状态机

```
INIT → PRECHECKING → CORE_BUILDING → STAGE_RESOLVING → ASSET_ASSEMBLING
  → SHOT_BINDING → SNAPSHOT_SEED_EXPORTING
  → READY_FOR_ASSET_MATCH_AND_PROMPT_PLANNER | REVIEW_REQUIRED | FAILED
```

## 3. 数据模型

### 3.1 semantic_assets
结构化语义资产表，把 costume / expression / action / prop / scene / mood_camera / prompt_template 做成独立资产。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | String(64) PK | |
| tenant_id | String(64) | |
| project_id | String(64) | |
| novel_id | String(64) FK | |
| entity_id | String(64) FK nullable | 关联实体 |
| asset_type | String(32) | costume/expression/action/prop/scene/mood_camera/prompt_template |
| canonical_name | String(256) | |
| aliases_json | JSONB | |
| tags_json | JSONB | |
| status | String(32) | draft/active/archived |
| structured_json | JSONB | 类型相关结构化字段 |
| prompt_json | JSONB | 正向提示词片段 |
| negative_prompt_json | JSONB | 负向提示词片段 |
| version | String(32) | |
| is_active | Boolean | |
| meta_json | JSONB | |

### 3.2 character_stage_profiles
角色成长阶段表。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | String(64) PK | |
| tenant_id / project_id | String(64) | |
| novel_id | String(64) FK | |
| entity_id | String(64) FK | 角色实体 |
| stage_name | String(128) | |
| chapter_start | Integer | 起始章节号 |
| chapter_end | Integer nullable | 结束章节号 |
| appearance_override_json | JSONB | 外貌覆盖 |
| temperament_override_json | JSONB | 气质覆盖 |
| default_costume_asset_id | String(64) FK nullable | 默认服装资产 |
| default_prop_asset_ids_json | JSONB | 默认道具资产 |
| emotional_baseline_json | JSONB | 情感基线 |
| status_tags_json | JSONB | |
| notes | Text | |
| meta_json | JSONB | |

### 3.3 shot_asset_bindings
镜头级资产绑定表。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | String(64) PK | |
| tenant_id / project_id | String(64) | |
| run_id | String(64) FK nullable | |
| chapter_id | String(64) FK | |
| scene_id | String(64) FK nullable | |
| shot_id | String(64) FK | |
| entity_id | String(64) FK nullable | |
| binding_role | String(32) | subject/background/prop/scene/mood |
| stage_profile_id | String(64) FK nullable | |
| selected_asset_ids_json | JSONB | 选中的语义资产 ID 列表 |
| state_override_json | JSONB | 镜头级覆盖（脏污/伤痕等） |
| prompt_snapshot_id | String(64) FK nullable | |
| meta_json | JSONB | |

### 3.4 prompt_snapshots
Prompt 快照表（区别于 PromptPlan）。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | String(64) PK | |
| tenant_id / project_id | String(64) | |
| run_id | String(64) FK nullable | |
| chapter_id | String(64) FK | |
| scene_id | String(64) FK nullable | |
| shot_id | String(64) FK | |
| entity_id | String(64) FK nullable | |
| source_type | String(32) | manual/auto/regenerate |
| source_id | String(64) nullable | |
| merged_prompt_text | Text | 合并后正向提示词 |
| merged_negative_prompt_text | Text | 合并后负向提示词 |
| merged_json | JSONB | 分层 JSON |
| generation_params_json | JSONB | 生成参数 |
| consistency_hash | String(128) | 一致性哈希 |
| regenerate_parent_snapshot_id | String(64) FK nullable | 父快照 |
| meta_json | JSONB | |

## 4. 与现有模块的衔接

- **21 (EntityRegistry)**: Entity 仍是 canonical root，Core 从 EntityContinuityProfile 承接
- **08 (AssetMatcher)**: 消费更细粒度的 SemanticAsset 作为匹配目标
- **10 (PromptPlanner)**: 消费 core + stage + override + scene + mood_camera + snapshot seed
- **29 (AssetLibrary)**: 管理页承接 SemanticAsset / StageProfile / Binding / Snapshot 的 CRUD

## 5. 一致性规则

- forbidden: 服装/道具/场景不得出现列表中的元素
- must_not: 角色不得出现列表中的外貌变化
- 命中 forbidden / must_not → status = REVIEW_REQUIRED

## 6. Definition of Done

- [ ] 四张新表创建，Alembic 迁移通过
- [ ] DTO 完整
- [ ] Service 状态机实现
- [ ] API CRUD 闭环
- [ ] 最小前端可操作
- [ ] 与 21/08/10/29 兼容接线
