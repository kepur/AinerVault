# 32_SCRIPTDOC_WORLDMODEL_PLANS_PIPELINE.md
# ScriptDoc + WorldModel + Plans 主干重构（翻译/制作双线分离）

## 0. 文档定位
本 Skill 用于修正“翻译工作台承担过多生产职责”导致的结构丢失问题。
核心原则：
- **主干是 ScriptDoc + WorldModel + Plans**。
- **翻译仅作用于面向观众文本**，不承担镜头/BGM/SFX 生成。
- **制作指令统一在 Plans 层维护**，供分镜、TTS、SFX、BGM、NLE 使用。

---

## 1. 基于当前代码的现状诊断（已核对）

### 1.1 前端现状（studio-web）
- 转译工作台页：`code/apps/ainern2d-studio-web/src/pages/StudioTranslationProjectPage.vue`
  - 已存在 block_type 显示与筛选，支持：`narration/dialogue/action/heading/scene_break`。
  - 当前“转译剧本”Tab 以 `listScriptBlocks` 返回的块为准。
- API 类型定义：`code/apps/ainern2d-studio-web/src/api/product.ts`
  - `ScriptBlockResponse.block_type` 同样只覆盖上述 5 种类型。
- 计划能力分散：
  - 翻译计划在 `/translations/projects/{id}/plan`（翻译执行计划）
  - 分镜预览有 `shot_plan`（`StudioChapterPreviewPage.vue` + `previewChapterPlan`）
  - NLE 时间线已有 `dialogues/bgm/sfx` 入口（`useNleTimelineStore.ts`）

### 1.2 问题根因
- **工作台职责混叠**：翻译页既承载翻译，又被用户期待承载制作计划。
- **Plan 模型不统一**：`shot_plan`、`timeline`、translation plan 分散，缺统一的 `Plans` 聚合对象。
- **结构主干感知弱**：UI 上“ScriptDoc/WorldModel/Plans”层级不直观，导致误解为“翻译后只剩对白/动作”。

结论：前端并非只允许对白/动作，而是**缺少“制作计划中心”的单独视图与统一数据契约**。

---

## 2. 目标架构（4层主干 + 2条产出线）

### 2.1 四层主干（持久化）
1) **SourceDoc**：原始章节文本（现有 chapter markdown）
2) **ScriptDoc**：结构化剧本（scene/segment/block）
3) **WorldModel**：实体与世界约束（人物/地点/道具/关系/风格）
4) **Plans**：制作分层计划
   - `shot_plan`
   - `dialogue_plan`
   - `sfx_plan`
   - `bgm_plan`
   - `ambience_plan`
   - `style_pack`

### 2.2 两条产出线
- **翻译线（观众向）**：`ScriptDoc -> TranslatedScriptDoc`
  - 只翻：`dialogue/narration/signage/ui_text/title`（可配置）
- **制作线（生成向）**：`ScriptDoc + WorldModel (+TranslatedScriptDoc可选) -> Plans -> Assets -> NLE`

---

## 3. 数据契约（建议新增）

### 3.1 ScriptDoc（建议）
```json
{
  "script_doc_id": "sd_xxx",
  "chapter_id": "ch_xxx",
  "version": "v1",
  "scenes": [
    {
      "scene_id": "sc_001",
      "order": 1,
      "time": "夜",
      "location": "长安城外",
      "weather": "小雨",
      "mood": "压抑",
      "blocks": [
        {"block_id":"b1","type":"narration","text":"..."},
        {"block_id":"b2","type":"dialogue","speaker":"李白","text":"..."},
        {"block_id":"b3","type":"action","text":"..."},
        {"block_id":"b4","type":"signage","text":"..."}
      ]
    }
  ]
}
```

### 3.2 Plans（建议）
```json
{
  "plans_id": "pl_xxx",
  "chapter_id": "ch_xxx",
  "input_fingerprint": "sha256:...",
  "language_internal": "en",
  "shot_plan": [],
  "dialogue_plan": [],
  "sfx_plan": [],
  "bgm_plan": [],
  "ambience_plan": [],
  "style_pack": {}
}
```

### 3.3 EntityMap（建议）
```json
{
  "entity_id": "e_xxx",
  "canonical_name": "Li Bai",
  "localized_names": {
    "zh-CN": "李白",
    "ja-JP": "李白",
    "en-US": "Li Bai"
  },
  "locked": true
}
```

---

## 4. API 改造计划（按最小侵入）

## 4.1 保留现有接口
- 保留：`/translations/projects/*` 全链路（避免回归风险）
- 保留：`generateWorldModel/regenerateWorldModel`
- 保留：`preview-plan` 与 `timeline` 已有能力

### 4.2 新增聚合接口（建议）
1) `GET /api/v1/chapters/{chapter_id}/script-doc`
2) `POST /api/v1/chapters/{chapter_id}/script-doc:build`
3) `GET /api/v1/chapters/{chapter_id}/plans`
4) `POST /api/v1/chapters/{chapter_id}/plans:generate`
5) `POST /api/v1/chapters/{chapter_id}/plans:regenerate`
6) `POST /api/v1/chapters/{chapter_id}/plans:apply-entity-map`

### 4.3 翻译接口边界收敛
- `translateBlocks` 仅面向 ScriptDoc 中可翻译字段。
- 为 `translateBlocks` 增加 `translatable_types` 参数（可选）：
  - 默认：`["dialogue", "narration", "signage", "ui_text", "title"]`

---

## 5. Studio Web UI 拆分（必须）

### 5.1 转译工作台三标签
在 `StudioTranslationProjectPage.vue` 中将主心智改为：
1) **译稿（观众向）**：仅显示/编辑可翻译字段
2) **制作计划 Plans（生成向）**：展示 `shot/dialogue/sfx/bgm/ambience/style_pack`
3) **一致性中心**：实体映射、术语、漂移告警

### 5.2 文案明确边界
在“译稿”Tab 顶部增加提示：
- “本页只翻译面向观众文本（对白/旁白/屏幕文字）。镜头/BGM/SFX/氛围在 Plans 面板生成与维护。”

### 5.3 新页面建议
- 新增：`StudioPlansWorkbenchPage.vue`（或先内嵌于转译页为子 Tab）
- 路由建议：`/studio/plans/:chapterId`

---

## 6. 执行顺序（闭环）

1) 生成/加载 ScriptDoc（持久化）
2) 生成/加载 WorldModel（持久化）
3) 生成 EntityMap（并支持 locked）
4) 生成 Plans（shot/dialogue/sfx/bgm/ambience/style_pack）
5) 翻译 ScriptDoc 可翻译字段（应用 EntityMap）
6) 资产生成（t2i/i2v/tts/sfx/bgm）
7) NLE 装配（按 shot_plan 时轴 + 对白 + BGM/SFX/Ambience）

---

## 7. Token/成本最优策略
- `ScriptDoc/WorldModel/Plans` 全部使用 `input_fingerprint` 缓存。
- 翻译按 `chapter/scene` 增量执行。
- EntityMap 一次生成后默认锁定，翻译阶段强替换。
- Plans 内部提示词语言统一英文（便于多后端生成稳定）；观众文本保持目标语言。

---

## 8. 落地分期（建议 3 个迭代）

### Iteration 1（1~2天，低风险）
- 前端：
  - 转译页增加“译稿边界提示文案”
  - 新增 Plans Tab（先 read-only，读取现有 `preview-plan/timeline` 聚合）
- 后端：
  - 新增 `GET /chapters/{id}/plans` 聚合层（拼接现有数据）

**DoD**
- 用户在转译页可明确区分“翻译”与“制作计划”
- 不影响现有翻译任务执行

### Iteration 2（3~5天，中风险）
- 后端新增 `plans:generate`，统一产出 `shot/dialogue/sfx/bgm/ambience/style_pack`
- 前端 Plans Tab 支持编辑与保存
- NLE 读取统一 Plans 契约

**DoD**
- 单章可一键生成 Plans，并可被 NLE 消费

### Iteration 3（3~5天，中高风险）
- ScriptDoc 正式化（scene meta + signage/ui_text）
- 翻译接口增加 `translatable_types`
- EntityMap 锁定策略全面接入翻译

**DoD**
- 翻译不再影响制作链路结构完整性
- 分镜/音频计划完全脱离“翻译是否完成”的硬依赖

---

## 9. 与现有文件映射（开发改造入口）

### 前端
- `code/apps/ainern2d-studio-web/src/pages/StudioTranslationProjectPage.vue`
  - 拆分“译稿/Plans/一致性中心”职责
- `code/apps/ainern2d-studio-web/src/api/product.ts`
  - 新增 Plans 聚合类型与 API
- `code/apps/ainern2d-studio-web/src/router/index.ts`
  - 新增 Plans workbench 路由（若采用独立页）
- `code/apps/ainern2d-studio-web/src/stores/useNleTimelineStore.ts`
  - 对齐新的 Plans 契约字段

### 后端（建议）
- `ainern2d-studio-api`：新增 ScriptDoc/Plans 聚合与生成接口
- `ainern2d-composer`：统一读取 Plans 进行时间线装配

---

## 10. 验收清单（必须全部满足）
- [ ] 转译页不再承载镜头/BGM/SFX 生产入口
- [ ] Plans 可独立生成、保存、回放
- [ ] 翻译只覆盖可翻译字段，结构不丢
- [ ] EntityMap 锁定后跨章节称呼一致
- [ ] NLE 可按统一 Plans 自动装配
- [ ] 相同输入 `input_fingerprint` 命中缓存

---

## 11. 风险与回滚
- 风险：旧接口字段不兼容导致前端空白
  - 方案：Plans Tab 先 read-only 聚合，不改旧翻译链路
- 风险：生成计划波动影响时间线
  - 方案：计划版本化 + 手工锁定 + 一键回滚上个版本
- 回滚：保持 `translations/projects` 与 `timeline` 原路径可独立工作

---

## 12. 下一步建议（可直接交给 Agent）
1) 先做 Iteration 1（最小可见收益）
2) 我们再开一个实现任务：
   - 新增 Plans 聚合 API 类型
   - 在转译页加 Plans 子 Tab（read-only）
   - 顶部加入“翻译边界说明”
3) 完成后再推进统一 `plans:generate` 与 ScriptDoc 正式化
