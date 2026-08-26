# AinerN2D v2 — 主线重构总纲

> 状态：设计基线 · 2026-08-26
> 原则：**不删旧代码，冻结外围，主线做到极致，扩展位预留。**

---

## 1. 为什么要重构

### 1.1 现状体量（实测）

| 项 | 数量 |
|----|------|
| SKILL 规格 | 33 个（01–33） |
| 微服务 | 5 个（studio-api / worker-hub / composer / worker-runtime / studio-web） |
| Python 代码 | 64,478 行 / 192 文件 |
| API 路由文件 | 25 个 / 26,574 行 |
| 前端页面 | 42 个 |
| 数据表 | 57+ |

### 1.2 臃肿的三个根因

**根因 A — 把"编排框架"当成了产品。**
`SkillRegistry / dispatch / run.stage.changed / DAG / orchestrator / RabbitMQ 事件契约` 这一整层，是为"32 个可插拔技能"服务的。但实际产品只有一条固定的线性流程（小说→翻译→剧本→素材）。用通用 DAG 框架跑一条固定管线，等于用 Kubernetes 跑一个 cron。

**根因 B — 生成能力被内化实现，而不是外化为契约。**
`worker-runtime` 里塞了 `comfyui_client / pipeline_i2v / pipeline_v2v / tts / bgm / sfx / lipsync`。每接一家新厂商就要改 worker、改 adapter、改配置中心页面。厂商 API 迭代速度远高于本系统，这是永久性负债。

**根因 C — UI 按"后端模块"切页，而不是按"用户做的事"切页。**
42 个页面里，用户在一个章节上完成工作要跳 6–8 个页面（小说库→章节编辑→转译工作台→世界观→分镜预览→提示词库→资产库→时间线）。上下文全靠人脑携带。这就是"反人类"的准确来源。

### 1.3 但有值得保留的资产

- `translation_models.py` 的 9 张表（ScriptBlock / TranslationBlock / GlossaryTerm / GlossaryCandidate / EntityNameVariant / ConsistencyWarning / TranslationPlanItem …）**模型质量高**，术语表、候选审核、漂移告警、人名锁定这套一致性机制是长文翻译的核心，直接复用。
- `Novel / Chapter / Scene / Shot / Dialogue / Artifact` 内容表，复用。
- Postgres + pgvector / Redis / MinIO 基础设施，复用。

---

## 2. v2 的定位与边界

### 2.1 一句话定位

> **AinerN2D 是一台"小说 → 多语言剧本 → 视频素材清单"的编译器。**
> 它不生成像素，不生成声波，不合成视频。它生成**结构**和**指令**，把指令交给能力层执行，把结果收回来做一致性管理。

### 2.2 系统边界（硬边界，写死）

```
┌──────────────────────────────────────────────────────┐
│  AinerN2D Core  （本系统，唯一主线服务）                │
│                                                       │
│  Novel/Chapter ──► ScriptDoc ──► ShotPlan ──► GenTask│
│       (原文)       (剧本结构)     (镜头指令)   (任务单) │
│                        ▲                              │
│                   WorldModel                          │
│                (人物/地点/道具/风格)                    │
│                        ▲                              │
│                  Translation                          │
│              (Block 的多语言层 + 术语一致性)             │
└───────────────────────┬──────────────────────────────┘
                        │  Capability API（本文档定义的标准）
                        ▼
┌──────────────────────────────────────────────────────┐
│  Capability Gateway  （你后续要做的中间层，不属于本系统）  │
│  按能力路由到：OpenAI / Gemini / 即梦 / 可灵 / Runway   │
│                 / ComfyUI / Fish-Audio / ElevenLabs …  │
└──────────────────────────────────────────────────────┘
```

**Core 只认能力（capability），永不认厂商（vendor）。**
新增一家厂商 = 中间层加一个适配器 + 后台路由表选一下，Core 零改动、零发版。

### 2.3 v2 只做五件事，做到极致

| # | 能力 | 极致标准 |
|---|------|---------|
| **1** | **翻译** | 百万字长文跨章节术语/人名零漂移；逐块可校对可锁定；候选术语自动挖掘 + 人工一键入库；改术语可反向重译受影响块 |
| **2** | **剧本** | 原文 → 场景/镜头/对白/动作 结构化；说话人自动归属；场景元信息（时间/地点/天气/情绪）齐全；可手工编辑且编辑不被重生成覆盖 |
| **3** | **世界观转译** | 中国古代 → 日本昭和 / 欧洲中世纪：**人名 · 称谓 · 名物 · 视觉** 四层全部映射；正文与画面共用同一份映射；可审查、可锁定、可版本回滚、每条转译带证据链。详见 `06_WORLDVIEW_TRANSLATION.md` |
| **4** | **世界观一致性** | 人物/地点/道具有稳定 ID、稳定视觉 prompt、稳定参考图、稳定音色、多语言名；跨章节复用；角色成长按章节叠加 |
| **5** | **生成指令编译** | 每个镜头编译出 **首帧 / 尾帧 / 运镜 / 时长 / 对白音频 / 场景背景 / BGM / 环境音** 的完整任务单，通过统一契约提交，结果回收入库 |

### 2.4 冻结清单（代码保留，主线不挂载）

以下模块**代码原地保留、不删除、不维护**，主线服务不引用；将来要用时按需重新挂载：

| 冻结项 | 原 SKILL | 原因 |
|--------|---------|------|
| SkillRegistry / dispatch / BaseSkillService | 全局 | 通用 DAG 框架，主线用固定管线代替 |
| Orchestrator / run.stage.changed / RabbitMQ 事件契约 | 28 | 主线用简单任务队列 |
| Critic 评估套件 | 16 | 质检交给人眼 + 重跑 |
| A/B Test 编排 | 17 | 无实验需求 |
| Failure Recovery 策略引擎 | 18 | 主线用「重试 + 死信 + 手动重跑」 |
| Compute-Aware Budgeter | 19 | 成本控制放在中间层 |
| Feedback Evolution Loop | 13 | 无 |
| ~~RAG KB / Embedding~~ **撤销冻结** | 11/12 | 世界观 KB 是名物转译的候选来源与证据链，不可替代。见 `06_WORLDVIEW_TRANSLATION.md §5` |
| Persona Dataset / Index / Lineage 七件套 + rag_console UI | 22/26 | 服务于别的目标；世界观 KB 的入口内嵌在世界观页，不单开知识库中心 |
| Timeline Editor / NLE / Patch 版本树 | 30 | 剪辑交给外部 NLE |
| Composer 服务（音视频合成） | 06/20 | 合成交给中间层/外部 |
| Lipsync worker | — | 交给中间层 |
| 多租户 tenant_id 双层作用域 + RBAC | 23 | 自用/小团队，砍掉 |

> 冻结做法见 `05_ROADMAP.md §2`：旧代码移入 `code/legacy/`，保留可导入状态，加 `FROZEN.md` 说明。

---

## 3. v2 主干模型（一张图）

```
Novel
 └─ Chapter                                  ← 原文（SourceDoc）
     └─ ScriptDoc  (versioned)               ← 剧本结构，语言无关
         └─ Scene   {time, location, weather, mood, bg_asset}
             └─ Block {type, speaker_id, order, source_text}
                 └─ BlockTranslation {lang, text, status, locked}   ← 翻译线
     └─ ShotPlan   (versioned)               ← 由 ScriptDoc 编译
         └─ Shot   {block_range, duration, camera}
             ├─ FrameSpec  role=first        ← 「前针」
             ├─ FrameSpec  role=last         ← 「后针」
             ├─ AudioSpec  {dialogue|narration|sfx}
             └─ (引用 Scene.bg_asset / Scene.bgm)

WorldEntity  {kind: character|location|prop|style}
 ├─ visual_prompt / negative_prompt / ref_images[]
 ├─ voice_profile  {provider_voice_id, pitch, speed, emotion}
 └─ locked: bool

WorldTransform  {novel, source_profile → target_profile, 每个目标语言一份}
 ├─ L1  entity_world_names   人名 + 读音 + family_key（家族姓氏一致）
 ├─ L2  honorifics           称谓 / 敬语体系映射
 ├─ L3  world_lexicon    ★   名物：客栈→旅籠 / 衙门→奉行所 / 铜钱→文
 └─ L4  entity_world_visual  实体 × 目标世界观 的视觉变体
       每层皆有 status(candidate/approved/locked) + rationale + evidence

GenTask  {capability, input_json, status, provider_task_id, cost}
 └─ Asset {kind: image|audio|video, url, sha256, meta}
```

**四条关键设计决策：**

1. **ScriptDoc 是唯一主干，翻译是 Block 的语言层。**
   剧本结构（场景切分/镜头/说话人）与语言无关，只算一次。翻译只作用于面向观众的文本（dialogue / narration / signage / title），多语言各一层，共享同一套镜头与生成指令。
   → 一次剧本，N 种语言，N 套配音，一套画面。这是成本上的数量级优势。

2. **尾帧从首帧派生，不独立生成。**
   `last_frame` 默认用 `image.image_to_image` 或 `image.edit`，以 `first_frame` 为基底施加动作/位移描述。独立文生图两次必然人物崩坏。仅当 `derive_from_first=false` 时才走独立 t2i。

3. **背景在 Scene 级，不在 Shot 级。**
   同一场景的所有镜头共享一张环境底图（`Scene.bg_asset`）作为 i2i 参考。省钱，且保证同场景空间一致。

4. **世界观转译贯穿正文与画面，共用同一份映射。**
   v1 的文化绑定只接通了画面线（skill_07 → skill_10），翻译线上 `culture_packs_json` / `temporal_layers_json` 存进了库却从未进入 prompt——结果是人名换了，「客栈 / 衙门 / 铜钱 / 娘子」仍按字面直译。v2 把 `world_transforms` 同时喂给翻译 prompt 与画面 prompt，两条线不可能各说各话。

---

## 4. 文档索引

| 文档 | 内容 |
|------|------|
| `00_OVERVIEW.md` | 本文：为什么、边界、主干、冻结清单 |
| `01_DATA_MODEL.md` | 表结构、版本化策略、与旧表的映射 |
| `02_CORE_API.md` | Core 自身对外 API（后台前端调用） |
| `03_CAPABILITY_API_SPEC.md` | ★ **能力 API 标准** —— 你的中间层要实现的契约 |
| `04_ADMIN_UX.md` | 后台重设计：信息架构、工作台、交互原则 |
| `05_ROADMAP.md` | 落地顺序、冻结做法、迁移脚本 |
| `06_WORLDVIEW_TRANSLATION.md` | ★ **世界观转译**：v1 实测诊断、L1–L4 四层模型、防漂移三道闸、RAG 定位 |
