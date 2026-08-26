# 01 · v2 数据模型

> 表前缀统一 `v2_`？**否。** 直接复用既有表名，新增表用无前缀新名。理由：旧服务冻结后不再写库，无冲突风险；加前缀会让 SQL 和 ORM 变丑。
> 唯一例外：`script_blocks` 需要扩展（见 §3.1）。

---

## 0. 全局约定

### 0.1 标准列（所有表）

```python
id           str   # ULID，字符串主键，可排序
created_at   datetime
updated_at   datetime
created_by   str | None
```

**移除**：`tenant_id` / `project_id` 双层作用域（砍多租户）。
**扩展位**：保留 `workspace_id: str = "default"`，非空默认值。将来要多团队时，加索引 + 中间件注入即可，不需要改表结构。这是"不删除、可扩展"的落法。

### 0.2 版本化策略

只有两类对象需要版本化：`ScriptDoc` 和 `ShotPlan`。

```
ScriptDoc(chapter_id, version=1, status=active)
ScriptDoc(chapter_id, version=2, status=draft)   ← 重新生成时新建，不覆盖
```

- 生成新版本时，**继承上一版本中 `edited_by_human=true` 的 Block/Shot**，不被 AI 覆盖。这是"编辑不被重生成吃掉"的实现点。
- `status: draft | active | archived`，一个 chapter 同时只有一个 `active`。

### 0.3 幂等与指纹

`ScriptDoc.input_fingerprint = sha256(chapter.content + script_config)`
`Shot.spec_fingerprint = sha256(frame_spec + audio_spec + entity_versions)`

指纹不变 → 跳过重生成，直接复用已有 Asset。这是省钱的主要手段。

---

## 1. 内容层（复用既有表，小改）

### 1.1 `novels`（复用）
```
title, author, source_language_code, description, cover_asset_id,
default_target_languages: JSONB   ← 新增
```

### 1.2 `chapters`（复用）
```
novel_id, order_no, title, content(Text), word_count,
source_format: str          ← 新增: plain | markdown | epub_html
ingest_meta_json: JSONB     ← 新增: 原始来源、切分参数
```

---

## 2. 剧本层（新表）

### 2.1 `script_docs`
```
chapter_id        FK chapters
version           int
status            enum(draft, active, archived)
language_source   str          # 剧本结构所用语言 = 原文语言
input_fingerprint str
generator_meta    JSONB        # 模型、prompt 版本、耗时、cost
stats_json        JSONB        # scene/block/dialogue 计数
UNIQUE (chapter_id, version)
```

### 2.2 `scenes`（复用旧表 + 扩展）
```
script_doc_id     FK script_docs      ← 新增（旧表挂 chapter_id）
order_no          int
title             str
time_of_day       str    # 晨/日/黄昏/夜  —— 自由文本，不做枚举
location_entity_id FK world_entities | None
location_text     str
weather           str
mood              str
summary           Text
bg_asset_id       FK assets | None    ← 场景底图（Scene 级共享）
bgm_asset_id      FK assets | None
ambience_asset_id FK assets | None
edited_by_human   bool = false
```

### 2.3 `script_blocks`（**复用并扩展旧表**）

旧表已有：`translation_project_id, chapter_id, seq_no, block_type, source_text, speaker_tag`

新增列：
```
script_doc_id     FK script_docs | None   ← v2 主挂载点
scene_id          FK scenes | None
speaker_entity_id FK world_entities | None  ← 从 speaker_tag 解析到稳定实体
edited_by_human   bool = false
meta_json         JSONB
```
`translation_project_id` 保留可空，兼容旧数据。

**`block_type` 枚举扩展**（旧 5 种 → 8 种）：
```
narration      旁白        ← 可翻译
dialogue       对白        ← 可翻译
action         动作描述     ← 不翻译（仅供生成用）
signage        画面文字/招牌 ← 可翻译
title          标题        ← 可翻译
inner_monolog  内心独白     ← 可翻译
scene_break    分场分隔     ← 不翻译
heading        章节标题     ← 可翻译
```
**可翻译集合**默认 `{narration, dialogue, signage, title, inner_monolog, heading}`，可配置。
`action` 不进翻译线 —— 它只服务于画面生成，用内部语言（英文）即可。这是 v1 最大的心智混乱点，此处写死。

---

## 3. 翻译层（几乎全部复用）

### 3.1 保留原样的表
`glossary_terms` · `glossary_candidates` · `entity_name_variants` · `consistency_warnings` · `translation_plan_items`

去掉 `tenant_id/project_id`，其余不动。这套是资产。

### 3.2 `translation_blocks`（复用 + 扩展）
```
script_block_id      FK script_blocks
target_language_code str        ← 新增（旧的语言在 project 上，v2 提到 block 上）
translated_text      Text
status               enum(draft, reviewed, locked)
locked               bool       ← locked 的块永不被批量重译覆盖
translation_notes    Text
glossary_hits_json   JSONB      ← 新增：本块命中的术语，用于审计和反向重译
model_meta_json      JSONB      ← 新增：模型/耗时/cost
UNIQUE (script_block_id, target_language_code)
```

### 3.3 `translation_projects` → 降级为 `translation_runs`

v1 把 `TranslationProject` 当成重对象（携带 scope/batch/cost/culture/temporal 一大堆配置），导致翻译"必须先建项目"。v2 反转：

- **翻译配置挂在 `novels` 上**（`novel_translation_settings`），一次配置长期生效
- **每次批量翻译只是一个 `translation_run`**（轻量任务记录）

```
novel_translation_settings
  novel_id, target_language_code,
  consistency_mode  enum(strict, balanced, free),
  translatable_types JSONB,
  style_prompt      Text,        # 译文风格指令（语气/人称/文体）
  naming_policy     JSONB,       # 人名策略：音译/意译/保留原文/按语言分别配置
  capability_route  JSONB,       # 用哪个 capability profile 翻译
  UNIQUE(novel_id, target_language_code)

translation_runs
  novel_id, target_language_code,
  scope_json,      # {chapter_ids: [...]} 或 {block_ids: [...]}
  status, progress, error_json,
  stats_json       # blocks_done/total, cost, tokens
```

> 迁移：旧 `translation_projects` 一行 → 一条 `novel_translation_settings` + 若干历史 `translation_runs`。见 `05_ROADMAP.md §4`。

---

## 4. 世界观层（新表，替代 v1 的 entity_mappings + preview_models 七件套）

### 4.1 `world_entities`
```
novel_id      FK novels
kind          enum(character, location, prop, faction, style)
canonical_key str          # 稳定标识，如 "li_bai"，跨章节不变
display_name  str          # 原文名
localized_names JSONB      # 只读缓存，权威在 entity_world_names（见 06 文档）
aliases_json  JSONB        # 原文别名/称谓，用于说话人归属和术语挖掘
summary       Text

-- 视觉
visual_prompt      Text         # 稳定外观描述（内部语言=英文）
negative_prompt    Text
ref_asset_ids      JSONB        # 参考图 asset id 列表，i2i/角色一致性用
style_entity_id    FK world_entities | None   # 绑定的风格实体

-- 声音（仅 character）
voice_profile_json JSONB   # {capability_voice_id, pitch, speed, emotion, sample_asset_id}

-- 控制
locked        bool = false  # 锁定后 AI 不得修改
version       int
UNIQUE (novel_id, canonical_key)
```

**合并的边界**（此处修订早期判断）：v1 把人物拆到 `entity_mappings / entity_instance_links / entity_continuity_profiles / entity_preview_variants / character_voice_bindings / persona_*` 七张表，其中 `entity_instance_links / continuity_profiles / preview_variants / persona_*` 确属过度拆分，合并进本表。

但**两处不可合并，必须保留独立表**：
- **实体 × 目标世界观 的视觉变体** → `entity_world_visual`（v1 的 `EntityPromptVariant`，带 `UNIQUE(entity_id, culture_pack_id)`）。同一个角色在昭和日本与中世纪欧洲是两套外观，塞进一行 JSON 会立刻失去可查询性与可锁定性。
- **实体 × 世界观映射 的名字** → `entity_world_names`（含 `target_reading` 与 `family_key`）。

`world_entities.localized_names` 因此降级为**只读缓存视图**，权威数据在 `entity_world_names`。详见 `06_WORLDVIEW_TRANSLATION.md §3`。

### 4.2 `entity_chapter_states`（**主线，P1 接线**）

v1 已有 `EntityState(entity_id, chapter_id, state_json)`，v2 接线用于角色成长与场景历史：
```
entity_id, chapter_order_from, state_json {appearance, costume, age, injury, rank},
visual_prompt_override, ref_asset_ids, note
```
渲染第 N 章时，取 `chapter_order_from <= N` 的最新一条叠加到基础 `visual_prompt` 上。
> 对应旧 SKILL_33「角色成长连续性」。早期版本把它列为"先建表不用的扩展位"，此处修订为主线能力——场景与人物的跨章节历史是一致性的组成部分，不是可选项。

### 4.3 世界观转译层（★ 新增，详见 `06_WORLDVIEW_TRANSLATION.md §3`）

| 表 | 作用 |
|----|------|
| `world_profiles` | 世界观档案（中国·唐·古典 / 日本·昭和 / 欧洲·中世纪），带 `parent_id` 继承、`axes_json`、`visual_json`、`language_json`、绑定 KB collection。取代 v1 借 `CreativePolicyStack.stack_json` 存放的 culture pack |
| `world_transforms` | 一本小说的一次映射实例：`source_profile → target_profile`，每个目标语言一份，可并存多个 active |
| `world_lexicon` | ★ **L3 名物转译表**：`canonical_key` + `source_term` → `target_term` + `target_reading` + `forbidden_targets` + 证据链。v1 完全缺失 |
| `world_lexicon_templates` | 预置词表，解决冷启动（`cn_ancient__jp_showa` 等三对内置） |
| `entity_world_names` | L1 人名：`target_name` + `target_reading` + **`family_key`**（家族姓氏一致性）+ 候选 + rationale + 分级锁定 |
| `entity_world_visual` | L4 视觉变体：`UNIQUE(entity_id, world_profile_id)` |
| `world_violations` | 转译违规：12 类 kind，扩展 v1 的 `consistency_warnings` |

---

## 5. 生成层（新表）

### 5.1 `shot_plans`
```
script_doc_id  FK script_docs
version        int
status         enum(draft, active, archived)
target_language_code str | None   # 音频所用语言；null=仅画面
config_json    JSONB   # 目标时长、宽高比、风格 pack、镜头密度
stats_json     JSONB
```

### 5.2 `shots`（复用旧表名，重定义）
```
shot_plan_id   FK shot_plans
scene_id       FK scenes
order_no       int
block_id_range JSONB      # 本镜头覆盖的 block id 列表
duration_ms    int        # 初值来自估算，TTS 完成后回填真实值
camera_json    JSONB      # {move: push_in|pan_left|static|orbit, speed, fov, transition_in/out}
description    Text       # 镜头内容自然语言描述（内部语言）
spec_fingerprint str
edited_by_human bool = false
status         enum(pending, generating, ready, failed, skipped)
```

### 5.3 `frame_specs` —— 「前后针」
```
shot_id     FK shots
role        enum(first, last)
prompt          Text
negative_prompt Text
entity_ids      JSONB     # 出镜实体，用于拼接 visual_prompt 与 ref 图
ref_asset_ids   JSONB     # 显式参考图（含 Scene.bg_asset）
derive_from_first bool = true    # 仅 role=last 有效
derive_instruction Text          # 尾帧相对首帧的变化描述
params_json     JSONB     # {width, height, seed, steps, cfg, style_strength}
asset_id        FK assets | None   # 生成结果
gen_task_id     FK gen_tasks | None
status          enum(pending, generating, ready, failed, approved)
```

### 5.4 `audio_specs`
```
shot_id      FK shots | None
scene_id     FK scenes | None      # BGM/ambience 挂 scene
kind         enum(dialogue, narration, sfx, bgm, ambience)
block_id     FK script_blocks | None
entity_id    FK world_entities | None   # 说话人 → voice_profile
text         Text                  # 已是目标语言的文本
language_code str
params_json  JSONB                 # {emotion, speed, pitch, volume_db, loop}
asset_id     FK assets | None
duration_ms  int | None            # 生成后回填 → 反写 shots.duration_ms
gen_task_id  FK gen_tasks | None
status       enum(...)
```

### 5.5 `gen_tasks` —— 能力调用记录（核心新表）
```
capability      str        # "image.text_to_image" 等，见 03 文档
idempotency_key str  UNIQUE
request_json    JSONB      # 提交给中间层的完整 payload
provider_task_id str|None  # 中间层返回的任务 id
provider        str|None   # 中间层回报的实际厂商，仅作记录
model           str|None
status          enum(queued, submitted, running, succeeded, failed, cancelled)
attempt         int
error_json      JSONB      # {code, message, retryable}
result_json     JSONB
usage_json      JSONB      # {cost, currency, duration_ms, tokens}
submitted_at / finished_at
-- 反向引用
ref_kind        str        # frame_spec | audio_spec | scene_bg | translation
ref_id          str
INDEX (status, capability), INDEX (ref_kind, ref_id)
```

### 5.6 `assets`（复用 `artifacts` 表思路，重命名为 `assets`）
```
kind        enum(image, audio, video, text, other)
url         str          # MinIO / 外链
sha256      str  INDEX   # 去重
mime        str
bytes       int
meta_json   JSONB        # 图: w/h/seed；音: duration_ms/sample_rate
source      enum(generated, uploaded, external)
gen_task_id FK gen_tasks | None
novel_id    FK novels | None   # 便于按书清理
```

---

## 6. 配置层

### 6.1 `capability_endpoints` —— 中间层注册
```
name        str          # "primary-gateway"
base_url    str
auth_json   JSONB        # {mode: bearer|header|none, ...}  ← 密钥加密存储
enabled     bool
health_json JSONB        # 最近一次探活结果
caps_cache_json JSONB    # GET /capabilities 的缓存（用于渲染表单）
caps_fetched_at datetime
```

### 6.2 `capability_routes` —— 能力路由
```
capability     str        # "image.text_to_image"
purpose        str        # "first_frame" | "last_frame" | "scene_bg" | "*"
endpoint_id    FK capability_endpoints
model          str | None       # 指定模型，null=由中间层决定
default_params JSONB
priority       int              # 多条则按优先级 fallback
enabled        bool
UNIQUE (capability, purpose, priority)
```

> 这两张表就是全部的"配置中心"。v1 的 `model_providers / provider_adapters / model_profiles / route_decisions` 四张表 + 3000 行 `config_center.py` 被这 2 张表取代 —— 因为**适配逻辑全部下沉到中间层了**。

---

## 7. 表清单汇总

| 类别 | 表 | 来源 |
|------|----|------|
| 内容 | `novels` `chapters` | 复用+加列 |
| 剧本 | `script_docs` `scenes` `script_blocks` | 新建 / 复用+加列 |
| 翻译 | `translation_blocks` `glossary_terms` `glossary_candidates` `entity_name_variants` `consistency_warnings` `novel_translation_settings` `translation_runs` | 复用为主 |
| 世界观 | `world_entities` `entity_chapter_states` | 新建 |
| 世界观转译 | `world_profiles` `world_transforms` `world_lexicon` `world_lexicon_templates` `entity_world_names` `entity_world_visual` `world_violations` | 新建（★核心） |
| RAG | `rag_collections` `kb_versions` `rag_documents` `rag_embeddings` | 复用（撤销冻结，绑定 world_profile） |
| 生成 | `shot_plans` `shots` `frame_specs` `audio_specs` `gen_tasks` `assets` | 新建 |
| 配置 | `capability_endpoints` `capability_routes` | 新建 |
| 账号 | `users` | 复用（去 RBAC） |

**合计 31 张表**（v1 为 57+）。比早期草案的 20 张多出 11 张，全部投在世界观转译与其 RAG 支撑上——这是本系统最不该省的地方。
