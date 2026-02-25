# 08_ASSET_MATCHER.md
# Asset Matcher（素材匹配 Skill 模板｜中文版）

## 0. 文档定位
本 Skill 用于承接 `Entity Canonicalization + Cultural Binding` 的输出结果，
在指定文化包、时代、题材、风格约束下，为人物/场景/道具/服饰/声音事件等实体匹配可用素材资源。

该模块的输出是“**素材匹配计划与候选结果**”，供后续：
- Prompt Planner（提示词规划）
- Visual Render Planner（视觉渲染规划）
- Audio Planner / SFX Planner（音频规划）
- Generation Workers（生成执行器）
消费使用。

---

## 术语对齐声明（固定模板）
- 本文统一运行对象命名：`run / job / stage / event / artifact`。
- `run`：一次端到端业务运行；`job`：run 内原子执行单元；`stage`：run 阶段状态。
- `event`：跨模块事实消息，统一采用 `EventEnvelope`；`artifact`：可回溯产物元数据。
- `worker.*.completed` 为执行明细事件，不替代 `job.succeeded / job.failed` 主状态事件。
- `step` 仅表示内部步骤序号，不作为运行态主对象或事件前缀。
- 必带治理字段：`tenant_id / project_id / trace_id / correlation_id / idempotency_key / schema_version`。

## 1. Workflow Goal（目标）
根据以下输入：
- 统一实体（canonical entities）
- 文化变体映射（entity variant mapping）
- 文化约束（culture constraints）
- 风格模式（style mode）
- 素材库能力范围（asset library capability）

输出：
- 每个实体的素材候选列表（候选排序 + 置信度）
- 被选中的默认素材（如可自动决策）
- 缺失素材清单与降级方案
- 供后续模块直接使用的素材引用契约（asset manifest）

---

## 2. Scope（范围）
### 包含
- 多类型素材匹配（人物/场景/道具/服饰/特效/音频）
- 基于文化包与变体的筛选
- 按风格、时代、题材、质量等级进行排序
- 素材能力检查（是否支持当前模型/工作流）
- 缺失项回退与降级方案
- 输出结构化 asset manifest

### 不包含
- 最终图像/视频/音频生成执行
- 复杂提示词拼接（由 Prompt Planner 完成）
- 素材下载/上传（由资源管理器或 Worker 执行）
- 最终导演级镜头调度（由 Visual Render Planner 完成）

---

## 3. Inputs（输入）

### 3.1 必需输入
- `entity_canonicalization_result.json`（上游输出）
  - `selected_culture_pack`
  - `canonical_entities[]`
  - `entity_variant_mapping[]`
  - `culture_constraints`
  - `conflicts[]`
  - `unresolved_entities[]`

- `asset_library_index`（素材索引）
  - 包含素材元数据（类型、标签、文化包、时代、风格、质量、可用模型、路径/ID等）

### 3.2 可选输入
- `style_mode`（写实 / 动画 / 国潮 / 赛博 / 影视化）
- `quality_profile`（preview / standard / high）
- `global_render_profile`（LOW_LOAD / MEDIUM_LOAD / HIGH_LOAD）
- `user_preferences`
  - 偏好某类人设/镜头风格/素材来源
- `project_asset_pack`
  - 项目专属素材（优先级可高于公共库）
- `backend_capability`
  - 当前后端支持的模型/LoRA/ComfyUI工作流类型
- `feature_flags`
  - 是否允许自动新建占位素材
  - 是否允许 generic 回退
  - 是否允许跨文化近似替代（默认关闭或低优先）

---

## 4. Outputs（输出）

### 4.1 主输出文件
- `asset_match_result.json`

### 4.2 输出内容必须包含
1. `status`
2. `selected_culture_pack`
3. `matching_summary`
4. `entity_asset_matches[]`
5. `asset_manifest`
6. `missing_assets[]`
7. `fallback_actions[]`
8. `warnings[]`
9. `review_required_items[]`（如有）

---

## 5. Core Concepts（核心概念）

### 5.1 Asset Candidate（素材候选）
满足基本筛选条件、可用于某实体的一条素材记录。
可包括：
- 参考图（reference image）
- LoRA / embedding / control preset
- 场景模板
- 道具图集
- SFX 音频片段
- ambience loops
- BGM模板（可选）
- prompt template（若你把提示词模板也纳入素材系统）

### 5.2 Asset Match（素材匹配结果）
某实体最终选中的素材方案（或候选列表）及其理由、分数、回退状态。

### 5.3 Asset Manifest（素材清单契约）
面向后续模块的结构化清单，描述：
- 每个实体/镜头需要哪些素材
- 素材ID/路径
- 用于哪个模块（图像/SFX/TTS辅助）
- 是否为临时回退资源

---

## 6. Matching Principles（匹配原则）

### 6.1 总原则
1. **先文化一致，再语义匹配，再风格一致，再质量最优**
2. 不要为了“有素材”牺牲明显文化一致性（除非用户允许混搭）
3. 缺素材时优先降级到“同文化上位变体”，再考虑 generic
4. 对关键实体（主角、核心场景、关键道具）要更严格
5. 对非关键实体（背景路人、小道具）允许更强降级策略

### 6.2 优先级（高到低）
1. 用户指定素材 / 项目专属素材（如存在）
2. 当前 `selected_culture_pack` 下精确变体匹配
3. 同 culture pack 上位实体匹配
4. 同时代/同题材近似变体
5. generic 通用素材
6. 占位符（placeholder）+ 待生成/待补齐（最后手段）

---

## 7. Branching Logic（分支流程与判断）

### [M1] 预检查分支（Precheck）
#### Trigger
- 收到上游文化绑定结果，准备开始素材匹配

#### Actions
1. 检查上游状态是否可用（必须为 `READY_FOR_ASSET_MATCH` 或系统允许在 `REVIEW_REQUIRED` 下继续）
2. 检查高严重度冲突是否阻塞
3. 检查素材索引是否可访问
4. 读取 `selected_culture_pack`、`entity_variant_mapping[]`
5. 建立匹配上下文（style_mode / quality_profile / backend_capability）

#### Output
- `precheck_status`
- `blocking_issues[]`（如有）

---

### [M2] 实体分类与优先级分支（Entity Prioritization）
#### Trigger
- 预检查通过

#### Actions
1. 将实体按类型分组：
   - character
   - scene
   - prop
   - costume
   - vehicle
   - fx / visual_effect
   - sfx_event / ambience_event（若音频也走同一匹配器）
2. 标记关键等级（critical / important / normal / background）
3. 为不同等级设置匹配严格度与回退策略

#### Output
- `entity_match_queue[]`（按优先级排序）

---

### [M3] 候选检索分支（Candidate Retrieval）
#### Trigger
- 对队列中的实体逐一或分组进行匹配

#### Actions
1. 根据 `selected_variant_id` 检索候选素材
2. 若无结果，回退到 `canonical_entity_specific`
3. 若仍无结果，回退到 `canonical_entity_root`
4. 应用文化/时代/题材过滤
5. 应用风格、质量、后端兼容过滤
6. 生成候选列表并附基础分数

#### Output
- `candidates_by_entity[]`

---

### [M4] 候选评分与排序分支（Scoring & Ranking）
#### Trigger
- 每个实体已有候选列表

#### Actions
为每个候选计算匹配分数（可规则+LLM辅助）：
- 文化匹配度
- 语义匹配度
- 时代匹配度
- 题材匹配度
- 风格匹配度
- 质量等级匹配度
- 后端兼容性
- 复用价值（项目内已有一致素材优先）
- 成本/负载（可选，供低负载模式）

排序后选出：
- 默认素材（top1）
- 候选备选（topN）

#### Output
- `ranked_asset_candidates[]`
- `selected_asset_per_entity`

---

### [M5] 回退与降级分支（Fallback & Degrade）
#### Trigger
- 某实体无候选或候选质量不达标

#### Actions
按策略回退：
1. 同文化包上位实体变体
2. 同时代/题材近似
3. generic
4. placeholder（待生成/待补齐）
5. 标记人工审阅（关键实体且无法接受降级）

#### Output
- `missing_assets[]`
- `fallback_actions[]`
- `review_required_items[]`

---

### [M6] 清单组装分支（Asset Manifest Assembly）
#### Trigger
- 所有实体完成匹配或进入回退状态

#### Actions
1. 汇总每个实体的匹配结果
2. 输出统一 `asset_manifest`
3. 标记哪些供：
   - Prompt Planner 使用
   - Visual Render Planner 使用
   - Audio Planner/SFX 使用
4. 输出可直接消费的引用字段（ID/路径/标签/兼容性）

#### Output
- `asset_match_result.json`
- `asset_manifest`

---

## 8. Matching Rules（素材匹配规则）

### 8.1 过滤阶段（Hard Filters）
候选素材必须先通过硬过滤：
- 素材类型匹配（scene/prop/character/...）
- 文化包或允许的回退范围匹配
- 时代/题材不明显冲突
- 后端兼容（模型/工作流可用）
- 资源状态可用（未禁用/未损坏/路径有效）

### 8.2 评分阶段（Soft Scoring）
对通过过滤的候选进行软评分（0~100）：
- 文化一致性（0~25）
- 语义贴合度（0~25）
- 时代/题材一致性（0~15）
- 风格一致性（0~15）
- 质量等级（0~10）
- 后端执行友好度（0~5）
- 项目一致性/复用价值（0~5）

### 8.3 严格度（按实体关键等级）
- `critical`（主角/核心场景/核心道具）
  - 高文化一致性阈值
  - 不轻易 generic 回退
- `normal`
  - 正常阈值，可有限回退
- `background`
  - 允许更积极降级，优先节省成本与匹配时间

---

## 9. Entity Type Specific Rules（按实体类型的专用规则）

### 9.1 Character（人物）
匹配重点：
- 文化服饰一致性
- 年龄/性别表达（如需要）
- 身份职业气质（将军/学生/江湖客）
- 发型/妆容/配饰
- 项目角色一致性（同角色跨镜头保持稳定）

额外规则：
- 主角优先使用角色专属资产（character pack）
- 若无专属资产，至少输出 `character_style_anchor`（用于后续生成一致性）

---

### 9.2 Scene（场景）
匹配重点：
- 建筑风格/室内结构
- 地区与时代一致性
- 灯光与材质倾向
- 场景功能语义（客栈大堂 / 办公室 / 海边空镜）

额外规则：
- 场景是文化语境锚点，优先级高于局部道具
- 若场景匹配不稳定，应优先修场景，而不是靠道具硬补

---

### 9.3 Prop（道具）
匹配重点：
- 功能语义（武器/餐具/交通工具/家具）
- 文化变体（中式长剑 vs 日式刀 vs 欧式长剑）
- 时代表现（古代/现代/近未来）

额外规则：
- 关键道具（主角佩剑、信物、法器）必须独立标记，可要求人工审阅

---

### 9.4 Costume（服饰）
匹配重点：
- 角色身份 + 时代 + 文化包
- 礼仪/社会规范
- 材质与层级（平民/贵族/门派/军队）

额外规则：
- 若人物与服饰冲突，以场景语境 + 角色身份优先判断
- 避免“语言对了但服装文化错位”

---

### 9.5 SFX / Ambience（若本模块覆盖音频素材）
匹配重点：
- 事件类型（打击、金属碰撞、风、雨、脚步）
- 材质/环境（木地板脚步 vs 石板路脚步）
- 场景空间感（室内/室外/洞穴/海边）
- 风格化程度（写实/夸张/影视化）

额外规则：
- 优先与场景文化包与材质一致
- 可输出多候选供 Audio Planner 二次挑选

---

## 10. Conflict Handling（冲突处理）

### 10.1 冲突来源
- 上游已存在 `conflicts[]`
- 本模块新增冲突（素材元数据与实体需求冲突）

### 10.2 本模块常见冲突类型
1. `ASSET_CULTURE_CONFLICT`
2. `ASSET_ERA_CONFLICT`
3. `ASSET_STYLE_CONFLICT`
4. `ASSET_BACKEND_INCOMPATIBLE`
5. `ASSET_QUALITY_BELOW_THRESHOLD`
6. `CHARACTER_CONSISTENCY_RISK`（同角色跨镜头不稳定风险）

### 10.3 处理策略
- 低严重度：记录 warning，允许继续
- 中严重度：建议替换候选，必要时降级
- 高严重度 + 关键实体：进入 `REVIEW_REQUIRED`

---

## 11. Fallback Strategy（回退策略）

### 11.1 回退层级（建议）
按顺序尝试：
1. `variant_exact`（当前 culture pack 精确变体）
2. `variant_same_pack_parent`（同文化包上位变体）
3. `variant_similar_era_genre`
4. `generic_culturally_safe`
5. `placeholder_to_generate`
6. `manual_review_required`

### 11.2 Placeholder 策略
当素材库没有合适资源时，可输出占位方案：
- `placeholder_type`: `"prompt_only"` / `"reference_needed"` / `"manual_asset_required"`
- 供后续 Prompt Planner 或 Asset Curator 补齐

### 11.3 关键实体特殊策略
若实体为 `critical`：
- 不建议直接 generic 回退
- 优先标记 `review_required`
- 可允许“先预览占位、最终版补素材”的双轨流程

---

## 12. Concurrency & Dependency（并发与依赖）

### 串行依赖（推荐）
1. Precheck
2. Entity Prioritization
3. Candidate Retrieval
4. Scoring & Ranking
5. Fallback & Degrade
6. Asset Manifest Assembly

### 可并行优化（推荐）
在 `selected_culture_pack` 和基础上下文确定后，可并行：
- 场景类实体匹配
- 道具类实体匹配
- 服饰类实体匹配
- 音频事件素材匹配（若纳入）
最终统一汇总并做冲突检查。

### 严禁提前执行
- 未完成文化绑定不得直接做定稿匹配
- 未过硬过滤不得进入评分
- 未完成回退评估不得标记 `ready_for_prompt_planner`

---

## 13. State Machine（状态机）

States:
- INIT
- PRECHECKING
- PRECHECK_READY
- PRIORITIZING
- RETRIEVING_CANDIDATES
- SCORING_RANKING
- FALLBACK_PROCESSING
- ASSEMBLING_MANIFEST
- REVIEW_REQUIRED
- READY_FOR_PROMPT_PLANNER
- FAILED

Transitions:
- INIT -> PRECHECKING
- PRECHECKING -> PRECHECK_READY
- PRECHECK_READY -> PRIORITIZING
- PRIORITIZING -> RETRIEVING_CANDIDATES
- RETRIEVING_CANDIDATES -> SCORING_RANKING
- SCORING_RANKING -> FALLBACK_PROCESSING
- FALLBACK_PROCESSING -> ASSEMBLING_MANIFEST
- ASSEMBLING_MANIFEST -> READY_FOR_PROMPT_PLANNER（无阻塞问题）
- ASSEMBLING_MANIFEST -> REVIEW_REQUIRED（关键实体缺失/高冲突）
- 任意状态 -> FAILED（不可恢复错误）

---

## 14. Output Contract（输出契约）

### 14.1 顶层结构（示例）
```json
{
  "version": "1.0",
  "status": "ready_for_prompt_planner",
  "selected_culture_pack": {
    "id": "cn_wuxia",
    "locale": "zh-CN",
    "era": "ancient_fantasy",
    "genre": "wuxia"
  },
  "matching_summary": {
    "total_entities": 18,
    "matched": 14,
    "matched_with_fallback": 3,
    "missing": 1,
    "review_required": 1
  },
  "entity_asset_matches": [],
  "asset_manifest": {},
  "missing_assets": [],
  "fallback_actions": [],
  "warnings": [],
  "review_required_items": []
}

14.2 entity_asset_matches[]（每个实体匹配结果）

每项至少包含：

entity_uid

entity_type

criticality（critical/important/normal/background）

canonical_entity_specific

selected_variant_id

match_status（matched / matched_with_fallback / missing / review_required）

selected_asset

candidate_assets[]（TopN，可裁剪）

score_breakdown

fallback_used（bool）

warnings[]

14.3 selected_asset（示例字段）

asset_id

asset_type（ref_image / lora / scene_pack / sfx / ambience / template）

source（project_pack / public_library / generated_placeholder）

path_or_ref

culture_pack

style_tags[]

era_tags[]

backend_compatibility

quality_tier

license_or_usage_policy（可选）

14.4 asset_manifest（面向下游）

建议按消费模块分组：

for_prompt_planner

for_visual_render_planner

for_audio_planner

for_consistency_checker

每组内按 scene_id / shot_id / entity_uid 组织引用关系。
15. Decision Table（关键判断表）
D1. 是否允许继续匹配
条件	动作
上游状态为 READY_FOR_ASSET_MATCH	正常继续
上游状态为 REVIEW_REQUIRED 且系统允许“预览继续”	继续，但标记风险
存在高严重度阻塞冲突且不允许绕过	进入 FAILED 或 REVIEW_REQUIRED
D2. 候选为空时处理
条件	动作
存在同文化包上位变体候选	回退并标记 fallback
存在 generic 安全候选	使用 generic 并降分
实体是 critical 且无可接受候选	review_required
非关键实体且无候选	placeholder_to_generate

D3. 默认素材自动选择
条件	动作
top1 分数显著高于 top2 且达阈值	自动选 top1
多个候选接近且影响关键一致性	保留多候选 + review_required（可选）
所有候选低于阈值	不自动选，进入 fallback/review
16. Scoring Heuristics（评分启发式）
16.1 推荐阈值（可配置）

critical_min_score: 80

important_min_score: 70

normal_min_score: 60

background_min_score: 45

16.2 低负载模式附加规则（可选）

当 global_render_profile = LOW_LOAD 时：

对背景类实体提高“复用价值”权重

对非关键实体降低“质量等级”权重

优先使用项目已有一致素材，减少新生成负担
16.3 高负载模式附加规则（可选）

当 global_render_profile = HIGH_LOAD 时：

对关键打斗/高动作镜头相关实体提高细节与质量权重

允许为关键实体保留多个高质量候选供后续选择

17. Prompting / Execution Constraints（给 AI 的执行约束）

不要把“匹配到某素材”当成“最终渲染已确定”

不要跳过文化与时代过滤，仅按关键词匹配

不要为了提高命中率过度使用 generic 回退（尤其关键实体）

信息不足时应输出 missing_assets / warnings / review_required_items

若用户指定素材优先策略，需显式记录 override_applied

输出必须满足 asset_match_result.json 契约，状态不可模糊
18. Example Mini Output（简化示例）
{
  "version": "1.0",
  "status": "ready_for_prompt_planner",
  "selected_culture_pack": {
    "id": "cn_wuxia",
    "locale": "zh-CN",
    "era": "ancient_fantasy",
    "genre": "wuxia"
  },
  "matching_summary": {
    "total_entities": 3,
    "matched": 2,
    "matched_with_fallback": 1,
    "missing": 0,
    "review_required": 0
  },
  "entity_asset_matches": [
    {
      "entity_uid": "E01",
      "entity_type": "scene",
      "criticality": "critical",
      "canonical_entity_specific": "place.social_lodging_venue.inn",
      "selected_variant_id": "place.social_lodging_venue.inn.cn_wuxia_inn",
      "match_status": "matched",
      "selected_asset": {
        "asset_id": "scene_pack_cn_wuxia_inn_hall_01",
        "asset_type": "scene_pack",
        "source": "project_pack",
        "path_or_ref": "asset://scene_pack_cn_wuxia_inn_hall_01",
        "culture_pack": "cn_wuxia",
        "style_tags": ["cinematic", "realistic"],
        "era_tags": ["ancient_fantasy"],
        "backend_compatibility": ["comfyui_scene_ref", "prompt_only"],
        "quality_tier": "high"
      },
      "candidate_assets": [
        {
          "asset_id": "scene_pack_cn_wuxia_inn_hall_01",
          "score": 93.5
        },
        {
          "asset_id": "scene_pack_cn_wuxia_inn_hall_02",
          "score": 88.1
        }
      ],
      "score_breakdown": {
        "culture": 24,
        "semantic": 24,
        "era_genre": 14,
        "style": 13,
        "quality": 9,
        "backend": 5,
        "reuse": 4.5
      },
      "fallback_used": false,
      "warnings": []
    },
    {
      "entity_uid": "E03",
      "entity_type": "prop",
      "criticality": "normal",
      "canonical_entity_specific": "prop.cold_weapon.blade",
      "selected_variant_id": "prop.cold_weapon.blade.cn_jian",
      "match_status": "matched_with_fallback",
      "selected_asset": {
        "asset_id": "ref_prop_cn_blade_generic_01",
        "asset_type": "ref_image",
        "source": "public_library",
        "path_or_ref": "asset://ref_prop_cn_blade_generic_01",
        "culture_pack": "cn_generic_historical",
        "style_tags": ["realistic"],
        "era_tags": ["historical", "ancient_fantasy"],
        "backend_compatibility": ["prompt_ref"],
        "quality_tier": "standard"
      },
      "candidate_assets": [],
      "score_breakdown": {
        "culture": 18,
        "semantic": 22,
        "era_genre": 12,
        "style": 10,
        "quality": 7,
        "backend": 4,
        "reuse": 2
      },
      "fallback_used": true,
      "warnings": ["exact_variant_not_found"]
    }
  ],
  "asset_manifest": {
    "for_prompt_planner": [
      {
        "entity_uid": "E01",
        "asset_id": "scene_pack_cn_wuxia_inn_hall_01",
        "use_as": "scene_anchor"
      },
      {
        "entity_uid": "E03",
        "asset_id": "ref_prop_cn_blade_generic_01",
        "use_as": "prop_reference"
      }
    ],
    "for_visual_render_planner": [],
    "for_audio_planner": []
  },
  "missing_assets": [],
  "fallback_actions": [
    {
      "entity_uid": "E03",
      "action": "use_generic_cn_historical_blade_reference"
    }
  ],
  "warnings": [],
  "review_required_items": []
}
19. Integration Points（与上下游模块衔接）
上游依赖

07_ENTITY_CANONICALIZATION_CULTURAL_BINDING.md

Language Background Knowledge Base（可选，用于文化约束补充）

下游消费者

Prompt Planner（提示词与控制条件拼接）

Visual Render Planner（镜头与帧预算规划时引用素材）

Audio Planner / SFX Planner（如共用音频素材库）

Consistency Checker（角色/场景跨镜头一致性）
20. Recommended Extensions（后续建议扩展）

后续可拆分为：

08.1_ASSET_INDEX_SCHEMA.md（素材索引结构规范）

08.2_ASSET_SCORING_RULES.md（评分细则）

08.3_CHARACTER_CONSISTENCY_MATCHER.md（角色一致性专用）

08.4_AUDIO_ASSET_MATCHER.md（音频素材专用匹配器）

21. Definition of Done（完成标准）

满足以下条件才视为完成：

 已完成预检查，明确是否可继续

 所有可处理实体已尝试匹配（成功/回退/缺失/审阅）

 已输出 entity_asset_matches[]

 已输出 asset_manifest

 关键实体缺失已进入 review_required_items[] 或有明确方案

 输出状态明确为 READY_FOR_PROMPT_PLANNER / REVIEW_REQUIRED / FAILED

 输出结构满足 asset_match_result.json 契约
 