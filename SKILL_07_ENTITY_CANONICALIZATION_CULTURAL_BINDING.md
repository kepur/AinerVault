# Entity Canonicalization + Cultural Binding Skill 模板（中文版）

## 0. 文档定位
本 Skill 用于在“LLM文本抽取”和“素材匹配/提示词生成”之间，完成：
1. **实体规范化（Canonicalization）**
2. **文化背景绑定（Cultural Binding）**
3. **文化变体映射（Variant Mapping）**
4. **冲突检查与回退策略（Conflict & Fallback）**

该模块的目标不是直接生成素材，而是输出“**文化一致、可供后续素材匹配/提示词生成使用的结构化实体结果**”。

---

## 术语对齐声明（固定模板）
- 本文统一运行对象命名：`run / job / stage / event / artifact`。
- `run`：一次端到端业务运行；`job`：run 内原子执行单元；`stage`：run 阶段状态。
- `event`：跨模块事实消息，统一采用 `EventEnvelope`；`artifact`：可回溯产物元数据。
- `worker.*.completed` 为执行明细事件，不替代 `job.succeeded / job.failed` 主状态事件。
- `step` 仅表示内部步骤序号，不作为运行态主对象或事件前缀。
- 必带治理字段：`tenant_id / project_id / trace_id / correlation_id / idempotency_key / schema_version`。

## 1. Workflow Goal（目标）
将来自小说/文案/剧本/章节的原始抽取实体（人物、场景、道具、服饰、食物、建筑、交通工具、声音事件等），转换为：

- 语言无关的统一实体（Canonical Entities）
- 带文化语境的实体变体（Cultural Variants）
- 可供素材库与提示词模板系统消费的结构化输出
- 文化一致性检查结果与未解决项清单

---

## 2. Scope（范围）
### 包含
- 实体归一化（同义词、跨语言表述、上位概念映射）
- 文化包选择（culture pack routing）
- 文化变体选择（entity variant mapping）
- 基础文化冲突检查（语言/时代/题材/道具/服饰）
- 未命中变体时的回退方案

### 不包含
- 最终素材文件下载/生成
- 最终提示词完整拼接（由后续 Prompt Planner 完成）
- 图像/视频生成执行（由后续 Render Planner / Worker 执行）

---

## 3. Inputs（输入）
### 3.1 必需输入
- `raw_extracted_entities`：上游 LLM 提取结果（人物/场景/道具/动作等）
- `story_context`：剧情上下文（章节摘要、场景描述、时代/世界观信息）
- `target_language`：目标语言（如 zh, en, ko）
- `genre`：题材（如 wuxia, xianxia, modern_city, fantasy, thriller）
- `story_world_setting`：世界观设定（现实/历史/架空/奇幻/科幻）
- `time_period`（可为空）：时代信息（现代、古代、近未来等）

### 3.2 可选输入
- `target_locale`：目标地区（如 zh-CN, zh-TW, en-US, en-GB, ko-KR, ph-PH）
- `user_override`：用户强制指定文化风格/地区/时代（最高优先级）
- `style_mode`：视觉风格（写实、动画、国潮、赛博、影视化等）
- `asset_library_capability`：素材库支持范围（有哪些 culture packs / variants）
- `language_background_kb_output`：语言背景知识库输出（推荐文化包、禁忌项、视觉规范等）

---

## 4. Outputs（输出）
本 Skill 必须输出结构化结果，供后续素材匹配与提示词生成使用。

### 4.1 主输出对象
- `entity_canonicalization_result.json`

### 4.2 输出内容应包含
1. `selected_culture_pack`
2. `canonical_entities[]`
3. `entity_variant_mapping[]`
4. `culture_constraints`
5. `conflicts[]`
6. `unresolved_entities[]`
7. `fallback_actions[]`
8. `routing_reasoning_summary`（简要原因标签，不输出冗长思维过程）

---

## 5. Core Concepts（核心概念）

### 5.1 Canonical Entity（统一实体）
语言无关的、可复用的实体定义，用于作为“跨语言/跨文化”的统一中间层。
- 示例：`place.social_drinking_venue`
- 示例：`prop.cold_weapon.sword`
- 示例：`costume.formal_uniform.school`

### 5.2 Cultural Variant（文化变体）
统一实体在特定文化包/地区/时代/题材下的具体表现形式。
- 示例：`place.social_drinking_venue.cn_wuxia_inn`
- 示例：`place.social_drinking_venue.uk_pub_modern`
- 示例：`street_food.cart.kr_pojangmacha_modern`

### 5.3 Culture Pack（文化场景包）
用于控制视觉与素材匹配的高层文化语境配置，通常由多个维度组成：
- language（弱信号）
- locale/region（强信号）
- era/time_period
- genre
- social_context
- world_setting

---

## 6. Routing Rules（文化素材路由规则）

### 6.1 总原则
**语言只作为弱信号，世界观/时代/题材/用户指定优先于语言。**

### 6.2 路由优先级（从高到低）
1. `user_override`（用户明确指定，最高优先级）
2. `story_world_setting`（现实/历史/架空/奇幻/科幻）
3. `time_period + genre`（时代 + 题材组合）
4. `target_locale`（地区）
5. `language_background_kb_output.culture_pack_recommendation`
6. `target_language`（仅作为弱信号）
7. `default_culture_pack`（兜底）

### 6.3 决策规则（示例）
- 若用户指定 `cn_wuxia`，则优先选用 `cn_wuxia`，除非明确与世界观冲突且用户未坚持。
- 若 `story_world_setting = historical` 且 `target_locale = ko-KR`，优先考虑 `kr_historical_*` 而非 `ko_modern`。
- 若 `genre = xianxia`，应优先使用 `cn_xianxia` 或其衍生文化包，不因目标语言是英文就切到欧美现代素材。
- 若 `story_world_setting = fantasy` 且为架空世界，可使用 `fantasy_generic + locale_influenced` 组合策略（避免强行现实地区映射）。

---

## 7. Branching Logic（分支流程与判断）

### [B1] 规范化分支（Canonicalization）
#### Trigger
- 存在原始实体提取结果，需要做跨语言归一化

#### Actions
1. 清洗实体名称（去噪、去冗余描述）
2. 合并同义词/别名/跨语言指代
3. 归入统一实体命名空间（canonical entity namespace）
4. 标注实体类型（人物/场景/道具/服饰/食物/交通/声音事件等）
5. 记录源文本证据位置（可选）

#### Output
- `canonical_entities[]`

---

### [B2] 文化包路由分支（Culture Pack Routing）
#### Trigger
- 已完成 canonical entities，且需要进行素材匹配或提示词生成

#### Actions
1. 收集路由信号（language/locale/era/genre/world_setting/user_override）
2. 按优先级选择 `selected_culture_pack`
3. 生成 `culture_constraints`（视觉宜项/禁忌项/命名规范/服饰规范等）
4. 记录选择理由标签（不要输出冗长内部推理）

#### Output
- `selected_culture_pack`
- `culture_constraints`
- `routing_reasoning_summary`

---

### [B3] 变体映射分支（Variant Mapping）
#### Trigger
- 已选定 culture pack，需要为 canonical entities 选择文化变体

#### Actions
1. 遍历 `canonical_entities[]`
2. 在当前 `selected_culture_pack` 中查找匹配变体
3. 若找到多个候选，按语义匹配度 + 时代一致性 + 题材一致性排序
4. 选择最佳变体并输出映射
5. 若无匹配，写入 `unresolved_entities[]`

#### Output
- `entity_variant_mapping[]`
- `unresolved_entities[]`

---

### [B4] 冲突检查分支（Conflict Check）
#### Trigger
- 完成文化包选择与变体映射后

#### Actions
检查以下冲突：
- 语言/招牌文字系统冲突
- 时代冲突（古代场景出现现代道具）
- 题材冲突（武侠场景出现明显现代酒吧元素）
- 服饰礼仪冲突
- 建筑/室内风格冲突
- 道具地域冲突（如错误地区特征物）

#### Output
- `conflicts[]`
- `fallback_actions[]`（建议替换或降级方案）

---

## 8. Entity Canonicalization Rules（实体规范化规则）

### 8.1 规范化原则
- 优先保留“语义功能”，而非表面词形
- 将描述性修饰与实体核心分离
- 跨语言同义实体映射到同一 canonical entity
- 保留原文别名用于回溯（alias / source_mentions）

### 8.2 示例（概念性）
- “客栈 / 酒馆 / inn / tavern / pub”  
  不应直接合并为同一视觉实体，但可先归入上位语义，再由文化变体细化：
  - canonical（上位）：`place.social_drinking_venue` 或 `place.lodging_and_drink_venue`
  - variant（具体）：`cn_wuxia_inn`, `uk_pub_modern`, `eu_tavern_medieval_fantasy`

- “长剑 / 宝剑 / sword / katana（注意：这类不能乱合并）”
  - canonical 可先到 `prop.cold_weapon.blade`
  - 再细分 variant：`jian_cn`, `katana_jp`, `longsword_eu`

### 8.3 允许输出多层级 canonical（推荐）
- `canonical_entity_root`（上位）
- `canonical_entity_specific`（更具体）
当上游信息不足时，允许先落到上位层，后续再细化。

---

## 9. Cultural Binding Rules（文化绑定规则）

### 9.1 绑定目标
为每个实体选择在当前文化包下的“可视化实现方向”，包括：
- 名称
- 外观特征
- 默认材质/色彩/构图倾向（可选）
- 提示词模板引用（可选）
- 素材库候选引用（可选）

### 9.2 绑定时必须考虑的维度
- `selected_culture_pack`
- `time_period`
- `genre`
- `story_world_setting`
- `style_mode`
- `scene_context`（例如宫廷、江湖、校园、办公室、贫民区等）
- `character_role`（角色身份影响服饰/道具）

### 9.3 绑定策略（推荐）
- **先场景后道具后人物细节**
  - 场景决定大部分视觉语境
  - 再映射道具
  - 最后再细化人物服饰与行为风格
这样能减少局部正确、整体违和。

---

## 10. Conflict Detection Rules（冲突检测规则）

### 10.1 冲突类型
1. `LANGUAGE_SIGNAGE_CONFLICT`
   - 目标文化包与招牌文字系统不一致
2. `ERA_CONFLICT`
   - 时代不一致（古代场景出现现代路灯/霓虹牌）
3. `GENRE_CONFLICT`
   - 题材语义冲突（武侠风配现代酒吧吧台）
4. `COSTUME_CONFLICT`
   - 人物身份/时代与服饰不符
5. `PROP_REGION_CONFLICT`
   - 地域特征道具错配
6. `ARCHITECTURE_CONFLICT`
   - 建筑风格与地区/时代不符
7. `SOCIAL_NORM_CONFLICT`
   - 手势/礼仪/座次等语境明显不符（可选高级）

### 10.2 冲突输出要求
每个冲突项至少包含：
- `conflict_type`
- `entity_id` / `variant_id`
- `severity`（low/medium/high）
- `description`
- `suggested_fix`

---

## 11. Fallback Strategy（回退策略）

### 11.1 当找不到文化变体时
按优先级回退：
1. 同 culture pack 下的上位实体变体（更泛化）
2. 同地区/时代相近题材的近似变体
3. `generic` 通用变体（保守视觉）
4. 标记 unresolved，交由后续 Prompt Planner 生成“弱约束提示词”
5. 若关键实体且无法回退，阻塞并请求人工确认（根据系统策略）

### 11.2 当存在高严重度冲突时
- 不应直接进入最终素材匹配
- 先执行修正或降级策略
- 若用户明确要求保留（风格混搭），记录 `user_override_applied = true`

### 11.3 当文化信号不足时
- 使用默认 culture pack（如 `generic_modern` 或项目默认）
- 同时输出 `warnings[]` 提示“文化绑定可信度较低”

---

## 12. Concurrency & Dependency（并发与依赖）

### 串行依赖（推荐）
1. Canonicalization
2. Culture Pack Routing
3. Variant Mapping
4. Conflict Check
5. Output Contract

### 可并行（可选优化）
- 在 `selected_culture_pack` 确定后：
  - 场景实体变体映射
  - 道具实体变体映射
  - 服饰实体变体映射
  可并行处理，最后汇总冲突检查

### 严禁提前执行
- 未确定 `selected_culture_pack` 前，不得做最终变体定稿
- 未完成冲突检查前，不得标记结果为 `ready_for_asset_match`

---

## 13. State Machine（状态机）

States:
- INIT
- CANONICALIZING
- CANONICAL_READY
- CULTURE_ROUTING
- CULTURE_BOUND
- VARIANT_MAPPING
- VARIANTS_READY
- CONFLICT_CHECKING
- REVIEW_REQUIRED（存在高严重度冲突或关键实体未解）
- READY_FOR_ASSET_MATCH
- FAILED

Transitions（示例）:
- INIT -> CANONICALIZING
- CANONICALIZING -> CANONICAL_READY
- CANONICAL_READY -> CULTURE_ROUTING
- CULTURE_ROUTING -> CULTURE_BOUND
- CULTURE_BOUND -> VARIANT_MAPPING
- VARIANT_MAPPING -> VARIANTS_READY
- VARIANTS_READY -> CONFLICT_CHECKING
- CONFLICT_CHECKING -> READY_FOR_ASSET_MATCH（无高严重度冲突）
- CONFLICT_CHECKING -> REVIEW_REQUIRED（有高严重度冲突/关键未解）
- 任意状态 -> FAILED（不可恢复错误）

---

## 14. Output Contract（输出契约）

### 14.1 顶层结构（示例）
```json
{
  "version": "1.0",
  "status": "ready_for_asset_match",
  "selected_culture_pack": {
    "id": "cn_wuxia",
    "locale": "zh-CN",
    "era": "ancient_fantasy",
    "genre": "wuxia",
    "source": "user_override"
  },
  "routing_reasoning_summary": {
    "reason_tags": ["user_override", "genre_wuxia", "historical_style"],
    "confidence": 0.93
  },
  "culture_constraints": {
    "visual_do": ["wood_architecture", "lantern_lighting", "jianghu_costume"],
    "visual_dont": ["modern_neon_sign", "western_pub_taps"],
    "signage_rules": ["hanzi_preferred", "avoid_modern_typography"]
  },
  "canonical_entities": [],
  "entity_variant_mapping": [],
  "conflicts": [],
  "unresolved_entities": [],
  "fallback_actions": [],
  "warnings": []
}
14.2 canonical_entities[]（示例字段）

每项至少包含：

entity_uid

entity_type

source_mentions[]

canonical_entity_root

canonical_entity_specific（可为空）

attributes（颜色/材质/动作倾向/角色身份等）

scene_scope（出现于哪些 scene/shot）

14.3 entity_variant_mapping[]（示例字段）

每项至少包含：

entity_uid

canonical_entity_specific

selected_variant_id

variant_display_name

culture_pack

match_confidence

visual_traits[]

prompt_template_refs[]（可为空）

asset_refs[]（可为空）

fallback_used（bool）
14.4 unresolved_entities[]（示例字段）

每项至少包含：

entity_uid

reason（无匹配/信息不足/冲突未解）

severity

suggested_fallback

requires_review（bool）

15. Decision Table（关键判断表）
D1. 文化包选择
条件	动作
user_override 存在	使用 user_override（最高优先级）
story_world_setting=historical 且 locale 存在	优先选择对应地区历史文化包
genre 为 wuxia/xianxia	优先选择对应中式题材文化包
仅有 target_language，无其他强信号	使用语言对应默认 culture pack（低置信度）
无法判断	使用 default_culture_pack 并输出 warning
D2. 变体缺失处理
条件	动作
当前 culture pack 有近似上位变体	降级到上位变体
无近似变体但有 generic 版本	使用 generic 变体并标记 fallback_used=true
关键实体且无回退可用	标记 unresolved + requires_review=true

D3. 冲突处理
条件	动作
冲突 severity=low	可继续，输出 warning
冲突 severity=medium	建议修复后继续，必要时降级
冲突 severity=high 且关键实体	进入 REVIEW_REQUIRED，不进入 asset match
用户明确接受混搭	记录 user_override_applied 后继续
16. Prompting / Execution Constraints（给 AI 的执行约束）

不要将“语言”直接等同于“视觉文化”

不要在未确定 culture pack 前就强行选定最终素材方向

不要跳过冲突检查直接输出 ready 状态

信息不足时应明确输出 warnings / unresolved_entities

优先保证整体文化一致性，其次再优化局部细节精度

若用户已明确指定风格混搭，应尊重用户选择并标注 override

17. Example Mini Output（简化示例）
{
  "version": "1.0",
  "status": "ready_for_asset_match",
  "selected_culture_pack": {
    "id": "cn_wuxia",
    "locale": "zh-CN",
    "era": "ancient_fantasy",
    "genre": "wuxia",
    "source": "genre+world_setting"
  },
  "canonical_entities": [
    {
      "entity_uid": "E01",
      "entity_type": "scene",
      "source_mentions": ["客栈大堂"],
      "canonical_entity_root": "place.social_lodging_venue",
      "canonical_entity_specific": "place.social_lodging_venue.inn",
      "attributes": {"mood": "busy", "material_hint": "wood"},
      "scene_scope": ["SCENE_03"]
    }
  ],
  "entity_variant_mapping": [
    {
      "entity_uid": "E01",
      "canonical_entity_specific": "place.social_lodging_venue.inn",
      "selected_variant_id": "place.social_lodging_venue.inn.cn_wuxia_inn",
      "variant_display_name": "江湖客栈大堂",
      "culture_pack": "cn_wuxia",
      "match_confidence": 0.96,
      "visual_traits": ["wood_beams", "lanterns", "tea_wine_tables"],
      "prompt_template_refs": ["scene_cn_wuxia_inn_hall_v1"],
      "asset_refs": ["ref_cn_inn_01", "lora_cn_wuxia_arch_v2"],
      "fallback_used": false
    }
  ],
  "conflicts": [],
  "unresolved_entities": [],
  "fallback_actions": [],
  "warnings": []
}
18. Integration Points（与上下游模块衔接）
上游依赖（输入来源）

LLM Extractor（实体抽取）

Language Background Knowledge Base（语言/文化背景建议）

Story Planner / Scene Planner（场景与分镜上下文）

下游消费者（输出去向）

Asset Matcher（素材库匹配）

Prompt Planner（提示词规划）

Visual Render Planner（视觉渲染规划）

Consistency Checker（一致性校验）

19. Recommended File Split（建议拆分文件）

若后续模块变复杂，建议拆成：

07.1_CANONICALIZATION_RULES.md

07.2_CULTURE_ROUTING_RULES.md

07.3_VARIANT_MAPPING_CONTRACT.md

07.4_CONFLICT_FALLBACK_RULES.md

当前阶段也可先保留为一个文件。
20. Definition of Done（完成标准）

满足以下条件才能认为该 Skill 执行完成：

 已输出 selected_culture_pack

 所有可识别实体完成 canonicalization

 已完成文化变体映射（或明确 unresolved）

 已执行冲突检查并输出结果

 高严重度冲突已进入 REVIEW_REQUIRED 或已修复

 输出结构满足 entity_canonicalization_result.json 契约

 状态为 READY_FOR_ASSET_MATCH 或 REVIEW_REQUIRED（不可模糊）

---

## 你可以怎么接到你现有流程图里（建议位置）

放在你图里的这两个节点之间最合适：

- `LLM提取文章信息`
- `匹配素材库 人物/场景/道具`

中间插入：

1. `Entity Canonicalization`
2. `Culture Pack Routing`
3. `Variant Mapping + Conflict Check`

这样后面的素材匹配、SFX、画面规划都会更稳。

---

## 我再送你一个超实用补充（建议你加）

在这个 skill 后面再加一个轻量模块：

- **`Cultural Prompt Hints Exporter`**
  - 把 `culture_constraints + visual_traits + signage_rules` 导出给 Prompt Planner
  - 这样图像提示词不会“实体对了但文化味不对”

---

## RAG 闭环衔接补充（P0）
- 输出必须拆分为：
  - `hard_constraints`（不可违反）
  - `soft_preferences`（可降级）
- 为 10 输出 `culture_binding_trace`：
  - `culture_pack_id`
  - `constraint_source_item_ids`
  - `kb_version_id`
- 为 13 输出 `feedback_anchor_tags`：
  - `culture_mismatch`
  - `naming_inconsistency`
  - `signage_style_conflict`

