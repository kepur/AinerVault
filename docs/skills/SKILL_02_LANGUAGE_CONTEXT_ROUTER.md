# 02_LANGUAGE_CONTEXT_ROUTER.md
# Language & Context Router（语言与上下文路由 Skill 模板｜中文版）

## 0. 文档定位
本 Skill 承接 `01_STORY_INGESTION_NORMALIZATION` 的输出，
负责根据语言、地区、题材、世界观、目标输出语言与用户偏好，决定后续处理路线（翻译、知识库初始化、文化包候选、规划策略）。

> 本模块是“路由与策略决策层”，不负责最终翻译生成、不负责素材匹配。

---

## 术语对齐声明（固定模板）
- 本文统一运行对象命名：`run / job / stage / event / artifact`。
- `run`：一次端到端业务运行；`job`：run 内原子执行单元；`stage`：run 阶段状态。
- `event`：跨模块事实消息，统一采用 `EventEnvelope`；`artifact`：可回溯产物元数据。
- `worker.*.completed` 为执行明细事件，不替代 `job.succeeded / job.failed` 主状态事件。
- `step` 仅表示内部步骤序号，不作为运行态主对象或事件前缀。
- 必带治理字段：`tenant_id / project_id / trace_id / correlation_id / idempotency_key / schema_version`。

## 1. Workflow Goal（目标）
根据标准化文本与上下文信息，输出：
- 处理语言路线（是否翻译、翻译到什么语言）
- 文化与地区候选（供 07 使用）
- 知识库检索/初始化建议（Language Background KB）
- 章节/镜头规划策略建议（例如中文武侠 vs 英文现代叙事）
- 风险提醒（语言混合、文化信号不足、翻译优先级冲突）

输出供下游：
- `03_STORY_SCENE_SHOT_PLANNER.md`
- `07_ENTITY_CANONICALIZATION_CULTURAL_BINDING.md`
- 翻译/本地化模块（如你后续单独拆分）

---

## 2. Inputs（输入）
### 2.1 必需输入
- `normalized_story.json`（来自 01）
- `target_output_language`（用户期望输出语言）
- `genre`（如已知）
- `story_world_setting`（现实/历史/架空/奇幻/科幻）

### 2.2 可选输入
- `target_locale`
- `user_overrides`
  - 文化偏好、是否保留原文风味、是否强制某语言旁白
- `project_defaults`
  - 默认语言、默认 culture pack、默认翻译策略
- `language_background_kb_capability`
- `feature_flags`
  - `enable_translation_route`
  - `enable_culture_candidate_export`
  - `enable_multilingual_output_plan`

---

## 3. Outputs（输出）
### 3.1 主输出文件
- `language_context_routing.json`

### 3.2 必需字段
1. `status`
2. `language_route`
3. `translation_plan`
4. `culture_candidates[]`
5. `kb_query_plan`
6. `planner_hints`
7. `warnings[]`
8. `review_required_items[]`

---

## 4. Routing Principles（路由原则）
1. 原文语言与目标输出语言分开处理
2. 语言不等于文化，但语言可作为文化弱信号
3. 用户明确指定优先于自动判断
4. 世界观/时代/题材优先于单纯语言信号
5. 文化信息不足时输出候选与置信度，不硬定唯一答案

---

## 5. Branching Logic（分支流程与判断）

### [R1] Precheck（预检查）
#### Actions
1. 检查 `normalized_story.status`
2. 读取主语言、混合语言比率
3. 检查目标语言是否缺失
4. 检查世界观/题材是否可用
#### Output
- `precheck_status`

---

### [R2] Language Route Decision（语言路线决策）
#### Actions
1. 判断是否需要翻译（原文语言 != 目标语言）
2. 判断是否需要双语输出（用户要求/项目默认）
3. 判断是否保留专有名词原文
4. 生成 `language_route`
#### Output
- `language_route`
- `translation_plan`

---

### [R3] Culture Candidate Routing（文化候选路由）
#### Actions
1. 基于世界观、时代、题材、target_locale 生成 culture pack 候选
2. 使用 primary_language 仅作弱信号补充
3. 若用户有 override，提升优先级
4. 输出候选列表 + 置信度 + 原因标签
#### Output
- `culture_candidates[]`

---

### [R4] KB Query Planning（知识库查询计划）
#### Actions
1. 生成 Language Background KB 查询项：
   - 语言风格规范
   - 文化视觉约束
   - 命名/招牌规则
   - 礼仪与动作风格（可选）
2. 标注哪些是必须项 / 可选项
#### Output
- `kb_query_plan`

---

### [R5] Planner Hints Export（规划提示导出）
#### Actions
1. 为 03（故事→场景→镜头规划）输出叙事处理提示
2. 为 07（文化绑定）输出文化约束候选
3. 标记不确定项与需人工确认项
#### Output
- `planner_hints`
- `warnings[]`

---

## 6. State Machine（状态机）
States:
- INIT
- PRECHECKING
- DECIDING_LANGUAGE_ROUTE
- ROUTING_CULTURE_CANDIDATES
- BUILDING_KB_QUERY_PLAN
- EXPORTING_PLANNER_HINTS
- READY_FOR_PLANNING
- REVIEW_REQUIRED
- FAILED

---

## 7. Output Contract（输出契约）
```json
{
  "version": "1.0",
  "status": "ready_for_planning",
  "language_route": {
    "source_primary_language": "zh",
    "target_output_language": "zh",
    "translation_required": false,
    "bilingual_output": false
  },
  "translation_plan": {
    "mode": "none",
    "preserve_named_entities": true
  },
  "culture_candidates": [
    {
      "culture_pack_id": "cn_wuxia",
      "confidence": 0.91,
      "reason_tags": ["genre_wuxia", "historical_style", "zh_primary"]
    },
    {
      "culture_pack_id": "cn_xianxia",
      "confidence": 0.62,
      "reason_tags": ["fantasy_overlap"]
    }
  ],
  "kb_query_plan": {
    "must_queries": ["cn_wuxia visual norms", "wuxia naming/signage style"],
    "optional_queries": ["jianghu etiquette gestures"]
  },
  "planner_hints": {
    "scene_planner_mode": "action_dialogue_mixed",
    "shot_planner_bias": "wuxia_cinematic",
    "culture_binding_hint": "prefer_cn_wuxia"
  },
  "warnings": [],
  "review_required_items": []
}
```

---

## 8. Definition of Done（完成标准）
- [ ] 已生成语言路线与翻译计划
- [ ] 已输出 culture candidates（含置信度）
- [ ] 已输出 KB 查询计划
- [ ] 已导出给 03/07 的 planner hints
- [ ] 状态明确为 `READY_FOR_PLANNING` / `REVIEW_REQUIRED` / `FAILED`

---

## 9. 与 RAG 进化闭环衔接（P0）
- 本模块必须额外输出 `retrieval_filters`：
  - `culture_pack`
  - `genre`
  - `era`
  - `style_mode`
- 输出 `filter_strength`：`hard_constraint` / `soft_preference`。
- 输出 `recipe_context_seed`，供 10 阶段组装 `RAG Recipe`。

### 9.1 可追溯字段
- `kb_version_id`（若可用）
- `recipe_id`（若可用）
- `trace_id`
