# 06 · 世界观转译（WorldView Transform）

> 本文档修正 `00_OVERVIEW.md` 与 `01_DATA_MODEL.md` 中对文化/世界观能力的低估。
> **世界观转译是本系统第一稀缺能力，不是附属配置。** v2 必须比 v1 更强，不得简化。

---

## 1. v1 现状实测（读代码得出，非文档推测）

### 1.1 设计层：优秀，v2 全盘继承

`SKILL_02_LANGUAGE_CONTEXT_ROUTER` + `SKILL_07_ENTITY_CANONICALIZATION_CULTURAL_BINDING` + `SKILL_27_WORLD_CULTURE_PACK_MANAGER` 确立了四条正确原则，v2 原样保留：

| 原则 | 内容 |
|------|------|
| **语言 ≠ 文化** | 语言只是弱信号。路由优先级：`user_override > story_world_setting > era+genre > target_locale > KB推荐 > target_language > default`。目标语言是英文，不等于要切到欧美现代素材。 |
| **两层实体抽象** | `Canonical Entity`（上位语义，语言无关）→ `Cultural Variant`（文化变体）。`place.social_drinking_venue` → `cn_wuxia_inn` / `uk_pub_modern` / `eu_tavern_medieval`。**「客栈/tavern/pub」不可直接合并为同一视觉实体**，必须先归上位语义再由文化变体细化。 |
| **硬约束 / 软偏好分离** | `hard_constraints` 不可违反，`soft_preferences` 可降级。 |
| **四级回退链** | 同包上位变体 → 近似题材变体 → generic → unresolved + requires_review。关键实体无回退则阻塞人工确认。 |

七类冲突检测同样保留：`LANGUAGE_SIGNAGE` / `ERA` / `GENRE` / `COSTUME` / `PROP_REGION` / `ARCHITECTURE` / `SOCIAL_NORM`。

### 1.2 实现层：三条链通，一条断

| 链路 | 状态 | 证据 |
|------|:----:|------|
| **画面文化绑定** | ✅ 通 | `skill_07_canonicalization.py` 1044 行 + `skill_10_prompt_planner.py` 1418 行。`culture_constraints.visual_do` → 正向 prompt，`visual_dont + hard_constraints` → 负向 prompt，另有 `_CULTURE_NEGATIVES` 按包预设负向词。 |
| **实体 × 文化包 视觉变体** | ✅ 表已建 | `EntityPromptVariant` 带 `UNIQUE(entity_id, culture_pack_id)`，每个实体在每个文化包下一套 `prompt_struct_json`。 |
| **人名文化等效命名** | ✅ 通 | `name_localization.py` 503 行。4 种策略、按语言分别锁定（`locked_langs_json`）、按语言分别设策略（`naming_policy_by_lang_json`）、每实体 3–5 候选带 rationale、**拼音消除校验器**（LLM 返回音译名直接判废）。 |
| **占位符防漂移** | ✅ 通，很扎实 | 稳定 token `{{CHAR:e_xxxx}}`；别名与本名一起替换；**按长度倒序替换**（防「李清」抢在「李清照」前）；**LLM 变异容错**（模型把 `{{CHAR:e_xxx}}` 改写成 `{{CHAR:Mason}}` 仍能还原）；**锁定语言缺译名直接 422 硬失败**，不静默降级。 |
| **正文文化转译** | ❌ **断** | 见下。 |

### 1.3 断链点（精确定位）

`translation.py:2409` 的 `translate_blocks` 构造 system prompt 时，只注入了四样东西：

```
源语言 → 目标语言
占位符保留规则
"保持文学风格，按原文顺序逐块翻译"
术语表
```

而 `TranslationProject` 上存着的 `culture_mode` / `culture_packs_json` / `temporal_enabled` / `temporal_layers_json` / `temporal_detect_policy` / `naming_policy_by_lang_json` —— **一个都没有进入 prompt**。全文 grep 确认：这些字段只出现在 CRUD 与 export 接口里（1347/1508/1603/3365 行），翻译执行路径上零引用。

同时，`skill_07` 算出的 `selected_culture_pack` 与 `culture_constraints` 只流向画面线（10），**从未回流到翻译线**。

**后果正是你担心的那种半成品**：人名转对了（李清照 → 昭和名），但正文里的「客栈 / 衙门 / 县令 / 铜钱 / 马车 / 娘子」仍按字面直译。世界观只换了人名的皮，没换名物的骨。

### 1.4 另外四个实测缺陷

| # | 缺陷 | 位置 | 后果 |
|---|------|------|------|
| 1 | `_fallback_localized_name` 用 `hash(entity_id) % len(pool)` 选兜底名 | `name_localization.py` | Python 字符串 `hash()` 每进程随机（PYTHONHASHSEED）。**同一实体在不同进程会兜底到不同名字——这是真正的漂移 bug**，且发生在最不该发生的兜底路径上 |
| 2 | `FORBIDDEN_PINYIN_PARTS` 硬编码约 30 词 | 同上 | 中文常见姓氏数百个，`Zheng / Feng / Shen / Tang` 等一律漏网，拼音名照样通过校验 |
| 3 | culture pack 借 `CreativePolicyStack.stack_json` 存放，无独立表 | `culture_packs.py` | 列表需全表扫描再按 `payload["type"]=="culture_pack"` 过滤；版本靠 `name` 字符串拼接；无法按 axes 检索 |
| 4 | 无家族姓氏一致性、无同世界观内命名风格协调 | 全局 | 李清照与其父李格非可能被映射成毫无关联的两个姓；同一部书里可能同时出现昭和名与平成名 |

---

## 2. v2 目标：把「半条链」补成「一等公民」

### 2.1 核心模型

```
        SourceWorld                          TargetWorld
      中国 · 唐宋 · 古典     ──WorldTransform──▶   日本 · 昭和 (1926–1989)
                             │                    欧洲 · 中世纪盛期
                             │                    ...（每个目标语言/市场一个）
                             ▼
              ┌──────────────────────────────┐
              │  L1  人名     EntityWorldName │  李清照 → 綾小路 静
              │  L2  称谓     HonorificMap    │  娘子 → 奥様 ／ milady
              │  L3  名物     WorldLexicon ★  │  客栈 → 旅籠 ／ tavern
              │  L4  视觉     WorldVisual     │  visual_do / dont / costume
              └──────────────────────────────┘
```

**L3「名物转译」是 v1 完全缺失、而这套系统真正的护城河。** 它复用 SKILL_07 已确立的上位语义机制：

```
canonical_key: place.lodging_venue
  ├─ cn_tang_classical  →  客栈
  ├─ jp_showa           →  旅館 (りょかん)
  └─ eu_medieval        →  tavern

canonical_key: office.county_magistrate
  ├─ cn_tang_classical  →  县令
  ├─ jp_showa           →  代官
  └─ eu_medieval        →  bailiff

canonical_key: currency.copper_coin
  ├─ cn_tang_classical  →  铜钱
  ├─ jp_showa           →  文
  └─ eu_medieval        →  silver penny
```

一份 `canonical_key` 词表可跨小说复用，这是长期资产。

### 2.2 五件事，不是四件事

修订 `00_OVERVIEW.md §2.3`，主线做到极致的能力由四项增为五项：

| # | 能力 | 极致标准 |
|---|------|---------|
| 1 | 翻译 | 百万字跨章节零漂移 |
| 2 | 剧本 | 结构化、可编辑不被覆盖 |
| 3 | **世界观转译** | **L1–L4 四层全通，正文与画面共用同一份映射，可审查、可锁定、可版本回滚、有证据链** |
| 4 | 世界观一致性 | 实体稳定 ID / 视觉 / 音色 / 多语言名 |
| 5 | 生成指令编译 | 首尾帧 / 音频 / 背景完整任务单 |

### 2.3 冻结清单修订

`00_OVERVIEW.md §2.4` 中「RAG KB / Embedding / Persona Dataset（11/12/22/26）」一项 **撤销冻结**。理由见 §5：名物词表的候选挖掘、命名风格参考、视觉约束补全、冲突判定依据，都需要按世界观切分的知识库。这是 RAG 在本系统里唯一真正不可替代的用途。

保留冻结的是 `rag_console` 那套面向「通用知识库管理」的 UI 与 `persona_dataset/index/lineage/runtime_manifest` 七件套，它们服务的是别的目标。

---

## 3. 数据模型

### 3.1 `world_profiles` —— 世界观档案（取代 v1 借 CreativePolicyStack 存的 culture pack）

```
id
novel_id        FK novels | NULL        -- NULL = 全局模板，可被任何小说引用
code            str    "cn_tang_classical" / "jp_showa" / "eu_medieval_high"
display_name    str    "中国·唐·古典" / "日本·昭和" / "欧洲·中世纪盛期"
role            enum(source, target, both)
parent_id       FK world_profiles | NULL     -- ★ 继承：jp_showa_rural 继承 jp_showa

axes_json       JSONB  {
                  region:        "JP",
                  era:           "showa",
                  era_span:      [1926, 1989],
                  genre:         "literary_drama",
                  world_setting: "historical",
                  social_context:"rural_town",
                  tech_level:    "early_industrial"
                }

visual_json     JSONB  {
                  visual_do[], visual_dont[],
                  signage_rules{}, costume_norms{}, prop_norms{},
                  architecture{}, palette[]
                }

language_json   JSONB  {                        -- ★ v1 完全没有这块
                  register:          "literary_formal",
                  name_pattern:      "family_given",
                  name_script:       "kanji+kana",
                  honorifics:        {...},      -- L2 称谓体系
                  forbidden_tokens:  ["inn","hotel","Mr.","pinyin:*"],
                  numerals:          "kanji",
                  date_style:        "era_year"
                }

kb_collection_id FK rag_collections | NULL      -- ★ 绑定该世界观的知识库
version         int
status          enum(draft, active, archived)
UNIQUE (code, version)
```

`parent_id` 继承让「昭和·乡村」只需覆写差异项，其余继承「昭和」。v1 的扁平模板做不到。

### 3.2 `world_transforms` —— 一本小说的一次世界观映射

```
novel_id             FK novels
target_language_code str                 -- 通常与目标世界观一一对应，但允许分离
source_profile_id    FK world_profiles
target_profile_id    FK world_profiles
version              int
status               enum(draft, active, archived)

policy_json   JSONB  {
  naming_policy:     "cultural_equivalent",   -- 可按实体类型细分
  honorific_policy:  "map",                   -- map | keep_source | drop
  lexicon_policy:    "strict",                -- strict | balanced | free
  preserve_original_for: ["poem_title", "song_lyrics"],  -- 不转译白名单
  strictness:        "strict"
}
stats_json    JSONB
UNIQUE (novel_id, target_language_code, version)
```

**一本小说可同时挂多个 active transform**（英文版走中世纪欧洲、日文版走昭和日本），共用同一套剧本与镜头，各自一套 L1–L4 映射。

### 3.3 `world_lexicon` —— ★ L3 名物转译表（v2 核心新增）

```
transform_id      FK world_transforms
canonical_key     str        "place.lodging_venue"     -- 上位语义，跨世界观稳定
category          enum(place, office, title, honorific, garment, food,
                        currency, weapon, vehicle, custom, ritual, measure, other)
source_term       str        "客栈"
source_aliases    JSONB      ["旅店", "客舍"]
target_term       str        "旅籠"
target_reading    str|NULL   "はたご"                   -- ★ 给 TTS 用，v1 没有
forbidden_targets JSONB      ["inn", "hotel", "客栈"]   -- ★ 译文里出现即违规

status            enum(candidate, approved, locked)
confidence        float
rationale         Text                                  -- 为什么这样转译
evidence_json     JSONB      {block_ids[], kb_doc_ids[], chapter_ids[]}  -- ★ 证据链
source            enum(template, mined, rag, manual)
hit_count         int
UNIQUE (transform_id, source_term)
INDEX (transform_id, canonical_key), INDEX (transform_id, status)
```

`forbidden_targets` 是防漂移第二道闸的执行依据（§4.2）。

### 3.4 `world_lexicon_templates` —— 预置词表，解决冷启动

```
pair_code     str    "cn_ancient__jp_showa"
display_name  str    "中国古代 → 日本昭和"
entries_json  JSONB  [{canonical_key, category, source_term, target_term,
                       target_reading, forbidden_targets, rationale}, ...]
version       int
```

内置至少三对：`cn_ancient→jp_showa`、`cn_ancient→eu_medieval`、`cn_wuxia→en_modern`。用户一键导入后再增删改，而不是从零手填。

### 3.5 `entity_world_names` —— L1 人名（取代 EntityMapping 上的 translations_json）

```
entity_id      FK world_entities
transform_id   FK world_transforms
target_name    str        "綾小路 静"
target_reading str|NULL   "あやのこうじ しずか"        -- ★ TTS 与字幕用
family_key     str|NULL   "li_family"                 -- ★ 家族姓氏一致性
naming_policy  enum(transliteration, literal, cultural_equivalent, hybrid)
candidates_json JSONB     [{name, reading, policy, rationale, register}]
rationale      Text
status         enum(candidate, approved, locked)
locked         bool
UNIQUE (entity_id, transform_id)
INDEX (transform_id, family_key)
```

**`family_key` 是 v1 没有的一层**：同 `family_key` 的实体在同一 transform 下**必须共享姓氏映射**。李清照与李格非同为 `li_family`，映射到昭和日本时姓氏统一（如「綾小路」），不会一个姓綾小路一个姓佐藤。生成候选时把整个家族一次性喂给 LLM，而不是逐个独立生成。

### 3.6 `entity_world_visual` —— L4 视觉变体（继承 v1 的 EntityPromptVariant）

```
entity_id         FK world_entities
world_profile_id  FK world_profiles
visual_prompt     Text
negative_prompt   Text
costume_note      Text
prop_note         Text
ref_asset_ids     JSONB
status            enum(draft, approved, locked)
UNIQUE (entity_id, world_profile_id)
```

挂 `world_profile_id` 而非 `transform_id`：视觉只取决于目标世界观，与源世界观无关，可跨小说复用。

### 3.7 `world_violations` —— 转译违规（扩展 v1 的 consistency_warnings）

```
transform_id  FK world_transforms
kind          enum(
                name_drift,          -- 人名与锁定值不符
                name_family_conflict,-- ★ 家族姓氏不一致
                lexicon_miss,        -- 该命中的名物词未命中
                forbidden_token,     -- ★ 译文出现禁用词
                register_conflict,   -- ★ 文体/敬语层级不符
                era_conflict, genre_conflict, costume_conflict,
                prop_region_conflict, architecture_conflict,
                signage_conflict, social_norm_conflict
              )
severity      enum(low, medium, high)
scope         enum(block, shot, entity, scene)
ref_id        str
detected      str
expected      str|NULL
suggested_fix Text
evidence_json JSONB
status        enum(open, resolved, ignored)
```

`high` 且属关键实体 → 阻断进入素材生成（继承 SKILL_07 的 `REVIEW_REQUIRED` 状态语义）。

### 3.8 `entity_chapter_states` —— 从扩展位提升为主线

v1 已有 `EntityState(entity_id, chapter_id, state_json)`。v2 接线，用于角色成长与场景历史：
```
entity_id, chapter_order_from, state_json {appearance, costume, age, injury, rank},
visual_prompt_override, ref_asset_ids, note
```
渲染第 N 章时取 `chapter_order_from <= N` 的最新一条叠加到基础 `visual_prompt` 上。

---

## 4. 防漂移三道闸（比 v1 多两道）

### 闸一 · 占位符隔离（继承 v1，加固）

翻译前把所有实体名替换为稳定占位符，翻译后用锁定的目标名还原。**人名根本不进 LLM，也就无从漂移。**

v1 已有的四个细节全部保留：别名一起替换、按长度倒序、LLM 变异容错、锁定语言缺译名硬失败 422。

v2 修补两处：
- **兜底名改为确定性哈希**：`sha256(entity_id + transform_id)` 取模，替换掉 `hash()`。同一实体在任何进程、任何时刻兜底结果恒定。
- **拼音校验器改为规则式**：完整汉语拼音音节表（约 410 个合法音节）+ 声调剥离 + 姓氏全表，取代 30 词硬编码黑名单。目标语言为日语时另加片假名音译检测（`リ・セイショウ` 这类）。

### 闸二 · 名物词表强制注入 + 反向校验（v2 新增）

**注入**：翻译每一批 block 前，用 Aho–Corasick 扫描本批原文，命中的 `world_lexicon` 条目才注入 prompt（只注入命中的，控制 token）：

```
【世界观转译】中国·唐·古典 → 日本·昭和（1926–1989）
【名物对照】必须使用右列译法：
  客栈 → 旅籠     衙门 → 奉行所    县令 → 代官
  铜钱 → 文       娘子 → 奥様
【禁用词】译文中不得出现：inn, hotel, magistrate, copper coin
```

**反向校验**（翻译后立即执行，不等人工）：
1. 译文命中 `forbidden_targets` → `world_violations(forbidden_token, severity=high)`
2. 原文命中了某 lexicon 条目、但译文中找不到对应 `target_term` → `world_violations(lexicon_miss, severity=medium)`
3. 敬语层级与 `language_json.register` 不符 → `register_conflict`

`lexicon_policy=strict` 时，`forbidden_token` 触发**自动重译该块**（带违规反馈重试一次），仍失败才落告警。

### 闸三 · 跨章节漂移扫描（继承并扩展 v1）

v1 的 `consistency_warnings` 只覆盖人名。v2 扩展到 L2/L3：全书扫描 `entity_world_names` 与 `world_lexicon` 的实际命中情况，检出同一 `canonical_key` 在不同章节被译成不同词的情况。

---

## 5. RAG 的位置（撤销冻结的理由）

RAG 在本系统里有且只有四个不可替代的用途，全部服务于世界观转译：

| 用途 | 检索什么 | 产出 |
|------|---------|------|
| **名物候选挖掘** | 目标世界观 KB 中的名物条目 | `world_lexicon` 的 `target_term` 候选 + rationale |
| **命名风格参考** | 目标世界观的人名语料（昭和流行名、中世纪教名与地缘姓氏） | `entity_world_names.candidates_json` |
| **视觉约束补全** | 目标世界观的服饰/建筑/器物规范 | `world_profiles.visual_json` 与 `entity_world_visual` |
| **冲突判定依据** | 时代/地域禁忌条目 | `world_violations` 的 `evidence_json` |

实现：复用现有 `rag_collections / kb_versions / rag_documents / rag_embeddings`（pgvector 已就绪），把 `rag_collections.bind_type` 绑到 `world_profile`。每个世界观一个 collection，KB 版本化（`kb_versions`）保证「换 KB 版本会改变哪些转译」可追溯——`world_lexicon.evidence_json.kb_doc_ids` 记录了来源文档。

**不恢复**的是 `rag_console` 那套通用知识库管理 UI 与 persona 七件套；世界观 KB 的入口在世界观页内部，不单开一个知识库中心。

---

## 6. 翻译 prompt 组装（断链修复点）

```
system =
  ① 基础指令        源语言 → 目标语言，逐块对齐，JSON 输出
  ② 世界观声明      "源世界观：中国·唐·古典 / 目标世界观：日本·昭和(1926–1989)
                     乡镇背景。译文须让昭和日本读者感到本土，而非翻译腔。"
  ③ 文体与敬语      language_json.register + honorifics 映射表（L2）
  ④ 名物对照表      本批命中的 world_lexicon 条目（L3）
  ⑤ 禁用词表        forbidden_targets 合集
  ⑥ 术语表          glossary_terms（继承 v1）
  ⑦ 占位符规则      继承 v1
  ⑧ 上下文接续      前后各一块的原文与译文
```

②③④⑤ 是 v1 完全缺失的四段。它们全部来自 `world_transforms` → `world_profiles` → `world_lexicon`，而这些数据 v1 其实已经在收集（`culture_packs_json` / `temporal_layers_json`），只是从未送进 prompt。

**Capability 契约无需改动**：`text.translate` 的 `input.style_prompt` 与 `input.glossary` 两个字段足以承载上述全部内容。中间层不需要理解世界观，只需照单执行。

---

## 7. 后台：世界观工作台

`04_ADMIN_UX.md` 的五区中，「世界观」区扩充为三个 Tab：

**Tab 1 · 世界观映射**
```
┌ 中国·唐·古典  ──▶  日本·昭和 ────────── active v3 ─┐
│ 命名策略 文化等效   敬语 映射   名物 严格            │
│ 覆盖率  人名 42/42 ✓   名物 218/240 ⚠   称谓 16/16 ✓│
│ [导入预置词表] [从章节挖掘候选] [RAG 补全] [发布新版本]│
└──────────────────────────────────────────────────┘
```
同一本书可并列多张卡（英文版走中世纪欧洲、日文版走昭和日本）。

**Tab 2 · 名物词表**
一张可编辑表格：`canonical_key | 类别 | 原文 | 译文 | 读音 | 禁用词 | 状态 | 命中数 | 依据`。
支持批量审核（候选 → 通过 → 锁定）、按类别筛选、点击「依据」展开 RAG 来源文档与原文出处。

**Tab 3 · 人物名录**
按 `family_key` 分组显示，一眼看出家族姓氏是否一致：
```
▾ 李家 (li_family) → 綾小路
    李清照  →  綾小路 静   あやのこうじ しずか   🔒 已锁定
    李格非  →  綾小路 格   あやのこうじ ただし   ✓ 已通过
```
候选名带 rationale，可试听（TTS 读 `target_reading`）。

**违规面板**常驻右侧，与译文 Tab 共享：点击违规直接跳到出问题的块。

---

## 8. 落地顺序修订

插入 `05_ROADMAP.md` 的 P0 与 P1 之间，作为 **P0.5**——因为它决定翻译质量，必须在大规模翻译之前就位：

| # | 任务 |
|---|------|
| 0.5.1 | `world_profiles` / `world_transforms` / `world_lexicon` / `entity_world_names` 表与 CRUD |
| 0.5.2 | 三对预置词表模板 + 一键导入 |
| 0.5.3 | 翻译 prompt 组装接入 ②③④⑤ 四段（**断链修复**） |
| 0.5.4 | 闸二：Aho–Corasick 命中注入 + 反向校验 + strict 模式自动重译 |
| 0.5.5 | 闸一加固：确定性兜底哈希 + 完整拼音音节表校验器 |
| 0.5.6 | `family_key` 家族一致性命名（整族一次生成） |
| 0.5.7 | 名物候选挖掘（从章节文本）+ 人工审核流 |
| 0.5.8 | 世界观工作台三个 Tab |
| 0.5.9 | RAG：world_profile 绑定 collection + 候选补全 |

**验收标准**：
- [ ] 同一本书配两个 transform（昭和日本 / 中世纪欧洲），各自导出译文，正文中的名物、称谓、人名全部符合各自世界观
- [ ] 全书扫描 `forbidden_token` 违规为 0
- [ ] 家族成员姓氏映射 100% 一致
- [ ] 任一条转译都能点开看到 rationale 与证据（原文出处 / KB 文档）
- [ ] 锁定的条目在任何重译中不被改动
- [ ] 兜底命名在不同进程中结果恒定（反复重启验证）
