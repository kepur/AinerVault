# 05 · 落地路线

> 原则：**不删旧代码。** 旧服务整体冻结但可运行，v2 在旁边长起来，跑通后再切流量。

---

## 1. 目录结构

```
code/
├── apps/
│   ├── ainer-core/              ★ v2 唯一后端（新建，单体 FastAPI）
│   │   └── app/
│   │       ├── main.py
│   │       ├── api/            library / script / translation / world / shots / settings
│   │       ├── domain/         纯业务逻辑，无 IO
│   │       ├── pipelines/      script_build / translate_run / shot_compile  ← 取代 SkillRegistry
│   │       ├── capability/     ★ Capability API 客户端（03 文档的实现）
│   │       │   ├── client.py       submit / poll / callback verify
│   │       │   ├── router.py       capability_routes 查表 → 选端点
│   │       │   └── schemas.py      能力 input/output 的 pydantic 模型
│   │       ├── models/         SQLAlchemy（20 张表）
│   │       └── workers/        arq / dramatiq 任务消费
│   │
│   ├── ainer-web/               ★ v2 前端（新建）
│   │
│   └── ...（旧的 5 个 app 原地不动）
│
└── legacy/                      ← 冻结说明入口（不移动文件，只放文档）
    └── FROZEN.md
```

**冻结怎么做**（"不删除、可扩展"的具体落法）：

1. `docker-compose.yml` 里旧服务改 `profiles: ["legacy"]` —— 默认不启动，`docker compose --profile legacy up` 仍可拉起。
2. 新建 `code/legacy/FROZEN.md`，写明：哪些目录冻结、为什么、将来解冻某个能力（如 NLE）时应该怎么接（走 v2 的 `assets` + `manifest` 导出，而不是重新接 DAG）。
3. 旧代码**不改一行**。不改 import、不加 deprecation。它就是一份可运行的参考实现。

**为什么不共用一个进程**：旧代码依赖 `SkillRegistry` / RabbitMQ 事件契约 / tenant 中间件，混在一起会把这些约束带进 v2。物理隔离是最便宜的解耦。

---

## 2. 阶段划分

### P0 — 骨架 + 翻译线打通（先交付价值最大的一半）

| # | 任务 | 产出 |
|---|------|------|
| 0.1 | 新建 `ainer-core`，最小 FastAPI + 20 张表的 SQLAlchemy 模型 + alembic 初始迁移 | 服务能起 |
| 0.2 | `capability/` 客户端：submit / poll / callback + HMAC 校验 + 重试 | 单测覆盖 §6 全部错误码 |
| 0.3 | **Mock Gateway**：一个 200 行的假中间层，实现 03 文档全部接口（返回占位图/静音音频） | 前后端可以并行开发，不等真实厂商 |
| 0.4 | 书架：小说/章节 CRUD + 导入分章 | API §1 |
| 0.5 | 剧本：`script:generate` pipeline（`text.chat` + json_schema）→ Scene/Block | API §2 |
| 0.6 | 翻译：settings + `translation:run` + 逐块对照 + 锁定 | API §3 |
| 0.7 | 术语：glossary CRUD + 候选挖掘 + 一键入库 + 漂移扫描 + 反向重译 | API §3.1 |
| 0.8 | 前端：书架 + 工作台的「原文/译文/剧本」三个 Tab | 04 文档 §3 |
| 0.9 | 旧数据迁移脚本（见 §4） | 现有小说/译文可用 |

**P0 完成即可独立使用**：一个专业的长文翻译工作台，术语一致性完备。这本身就是产品。

### P0.5 — 世界观转译（★ 必须在大规模翻译之前就位）

它决定翻译质量本身，不能排在翻译之后。完整任务表见 `06_WORLDVIEW_TRANSLATION.md §8`。

| # | 任务 |
|---|------|
| 0.5.1 | `world_profiles` / `world_transforms` / `world_lexicon` / `entity_world_names` 表与 CRUD |
| 0.5.2 | 三对预置词表模板（`cn_ancient→jp_showa` / `cn_ancient→eu_medieval` / `cn_wuxia→en_modern`）+ 一键导入 |
| 0.5.3 | **断链修复**：翻译 prompt 组装接入 世界观声明 / 敬语映射 / 名物对照 / 禁用词 四段 |
| 0.5.4 | 闸二：Aho–Corasick 命中注入 + 反向校验 + strict 模式自动重译 |
| 0.5.5 | 闸一加固：确定性兜底哈希（修 `hash()` 漂移 bug）+ 完整拼音音节表校验器 |
| 0.5.6 | `family_key` 家族一致性命名（整族一次生成，不逐个独立生成） |
| 0.5.7 | 名物候选挖掘 + 人工审核流 |
| 0.5.8 | 世界观工作台三个 Tab |
| 0.5.9 | RAG：`world_profile` 绑定 collection + 候选补全 + 证据链 |

### P1 — 世界观 + 首尾帧

| # | 任务 |
|---|------|
| 1.1 | `world_entities` CRUD + 从章节抽取实体 + 合并去重 |
| 1.1b | `entity_world_visual`：实体 × 目标世界观 的视觉变体（昭和的李清照 vs 中世纪的李清照） |
| 1.1c | `entity_chapter_states` 接线：角色成长按章节叠加到 visual_prompt |
| 1.2 | 实体视觉 prompt 生成 + 参考图生成（`image.text_to_image` + `reference_images`） |
| 1.3 | 音色绑定（`audio.voice_list` + 试听） |
| 1.4 | `shot-plan:generate`：ScriptDoc → Shot + FrameSpec(first/last) + AudioSpec |
| 1.5 | **首帧生成** `image.text_to_image`（拼 entity.visual_prompt + scene.bg 作 ref） |
| 1.6 | **尾帧派生** `image.image_to_image`（首帧为基底，strength 0.25–0.45） |
| 1.7 | 场景背景图 / TTS 配音 + duration 回填 |
| 1.8 | 前端：分镜 Tab + 世界观页 + 任务抽屉 |
| 1.9 | 设置页：端点 + 路由 + `param_schema` 自动表单 |

### P2 — 出片与扩展

| # | 任务 |
|---|------|
| 2.1 | `manifest` / `srt` / `zip` 导出 |
| 2.2 | BGM / 环境音 |
| 2.3 | `video.image_to_video`（首尾帧 → 片段），`output.last_frame` 接续下一镜 |
| 2.5 | 批量成本看板（按书/章/能力聚合 `gen_tasks.usage_json`） |

---

## 3. 关键实现注记

### 3.1 pipeline 不是 DAG
`pipelines/` 里就是普通 Python 函数：
```python
async def build_script(chapter_id: str, cfg: ScriptConfig) -> ScriptDoc:
    chapter = await repo.get_chapter(chapter_id)
    prev    = await repo.get_active_script(chapter_id)      # 用于继承人工编辑
    raw     = await capability.chat(prompt_for_script(chapter, cfg),
                                    response_format=SCRIPT_SCHEMA)
    doc     = merge_human_edits(parse(raw), prev)
    return await repo.save_script_doc(doc)
```
没有注册表、没有 stage 事件、没有 orchestrator。**要看流程就读这个函数。** 这是 v1 最大的可读性损失点。

### 3.2 任务队列
`arq`（Redis 队列，轻）足够。不需要 RabbitMQ 的 topic 编排。
`gen_tasks` 表本身就是任务状态源，回调直接改表 + SSE 广播。

### 3.3 首尾帧的 prompt 拼装（质量核心）
```
first_frame.prompt =
    [style_entity.visual_prompt]          # 全书统一画风
  + [scene 描述: 时间/地点/天气/情绪]
  + [出场 entity.visual_prompt 逐个]       # 稳定外观
  + [shot.description]                    # 本镜内容
  + [镜头语言: 景别/构图]

first_frame.reference_images =
    scene.bg_asset      role=scene       weight=0.5
  + entity.ref_assets   role=character   weight=0.8   (每个出场角色取 1–2 张)
  + style_entity.ref    role=style       weight=0.4

last_frame = image_to_image(
    image = first_frame.asset,
    prompt = first_frame.prompt + " ; " + derive_instruction,
    strength = 0.35,
    seed = first_frame.seed          # 同 seed
)
```
`derive_instruction` 由 LLM 在生成 ShotPlan 时一并产出，形如 `"he has now stepped through the gate, back half-turned, rain heavier"`。

### 3.4 成本闸门
每个 `:generate` 前，用 Discovery 的 `pricing` 估算总成本，超过章节预算则**先弹确认框**列出"将生成 42 张图，预估 $1.34"。生成很贵，绝不能静默批量烧钱。

---

## 4. 数据迁移

一次性脚本 `scripts/migrate_v1_to_v2.py`：

| v1 | v2 | 说明 |
|----|----|------|
| `novels` / `chapters` | 同名表加列 | 原地 alter |
| `script_blocks` | 同表加列 `script_doc_id/scene_id/speaker_entity_id` | 为每个已有 chapter 造一个 `script_docs` v1 记录挂上 |
| `translation_blocks` | 同表加 `target_language_code` | 从其 `translation_project.target_language_code` 回填 |
| `translation_projects` | → `novel_translation_settings` + `translation_runs` | 一行拆两处 |
| `glossary_terms` / `glossary_candidates` / `entity_name_variants` / `consistency_warnings` | 原样，去 tenant 列 | 直接用 |
| `entity_mappings` + `character_voice_bindings` + `entity_preview_variants` | → `world_entities` | 按 canonical name 聚合成一行 |
| `artifacts` | → `assets` | 字段映射 |
| 其余 30+ 表 | 不迁移 | 留在库里，旧服务解冻时仍可用 |

迁移**只读旧表、只写新表/新列**，不 DROP 任何东西。

---

## 5. 验收标准

P0 验收：
- [ ] 导入一本 30 万字小说，自动分章
- [ ] 一章生成剧本，场景/对白/说话人正确率人工抽检 ≥ 90%
- [ ] 全书翻译到 en-US，术语命中率 100%（术语表内的词零漂移）
- [ ] 改一条术语 → 反向重译只影响命中块，不动已 lock 的块
- [ ] 一致性告警能定位到具体块并一键修正

P0.5 验收：
- [ ] 同一本书配两个 transform（昭和日本 / 中世纪欧洲），各自导出译文，正文中的**名物、称谓、人名**全部符合各自世界观
- [ ] 全书扫描 `forbidden_token` 违规为 0
- [ ] 家族成员姓氏映射 100% 一致
- [ ] 任一条转译都能点开看到 rationale 与证据（原文出处 / KB 文档）
- [ ] 锁定条目在任何重译中不被改动
- [ ] 兜底命名在不同进程中结果恒定（反复重启验证）

P1 验收：
- [ ] 同一角色在同一章 10 个镜头中外观稳定（人工目视）
- [ ] 尾帧与首帧构图连贯，非独立随机
- [ ] TTS 时长回填后，`shots.duration_ms` 与音频实际时长一致
- [ ] 换一家图像厂商（改 `capability_routes` 一行）→ 全链路仍跑通，**Core 与前端零改动**

> 最后一条是整个架构成立与否的判据。
