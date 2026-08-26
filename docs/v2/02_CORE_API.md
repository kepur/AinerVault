# 02 · Core API（后台前端调用）

> Base: `/api/v2`　认证：`Authorization: Bearer <jwt>`（单一角色，无 RBAC）
> 目标：**从 145+ 路由收敛到 ~50 个**，按「用户做的事」组织，而非按后端模块组织。

---

## 0. 通用约定

- 列表统一 `?page=1&size=50&q=&sort=`，返回 `{items, total, page, size}`
- 长任务统一返回 `{run_id}`，进度走 **SSE**：`GET /api/v2/runs/{run_id}/stream`
- 所有"生成"动作统一语义：`POST .../{resource}:generate`（冒号动作，非 REST 名词）
- 错误统一 `{ "code": "...", "message": "...", "detail": {...} }`

---

## 1. 书架 Library

```
GET    /novels
POST   /novels
GET    /novels/{id}
PATCH  /novels/{id}
DELETE /novels/{id}

POST   /novels/{id}/chapters:import        # 上传 txt/md/epub，自动分章
GET    /novels/{id}/chapters               # 列表带每章状态徽标
POST   /novels/{id}/chapters
GET    /chapters/{id}                      # 含 content
PATCH  /chapters/{id}
DELETE /chapters/{id}
POST   /chapters:reorder
```

`GET /novels/{id}/chapters` 的每一项返回**状态四联**，后台列表直接画进度条：
```jsonc
{ "id":"ch_1", "order_no":1, "title":"第一章", "word_count":3412,
  "state": {
    "script":      "active",              // none | draft | active
    "translation": { "en-US": 0.92, "ja-JP": 0.0 },   // 完成率
    "shots":       "active",
    "assets":      { "total": 42, "ready": 38, "failed": 1 }
  } }
```

---

## 2. 剧本 ScriptDoc

```
GET    /chapters/{id}/script                    # 当前 active 版本，含 scenes+blocks
POST   /chapters/{id}/script:generate           # → {run_id}，生成新版本
GET    /chapters/{id}/script/versions
POST   /chapters/{id}/script/versions/{v}:activate
POST   /chapters/{id}/script/versions/{v}:diff  # 与另一版本比较

PATCH  /scenes/{id}                             # 手改场景元信息 → edited_by_human=true
POST   /scenes:reorder
POST   /scenes/{id}:split                       # 拆场
POST   /scenes:merge

PATCH  /blocks/{id}                             # 改 type / speaker / 原文
POST   /blocks/{id}:split
POST   /blocks:merge
POST   /blocks/{id}:move                        # 移到另一场景
```

`script:generate` 请求体：
```jsonc
{
  "mode": "full",                  // full | scenes_only | resegment
  "keep_human_edits": true,        // 默认 true，继承上版人工编辑
  "scene_granularity": "medium",   // coarse | medium | fine
  "capability_route": null         // null=用默认路由
}
```

---

## 3. 翻译 Translation

```
GET    /novels/{id}/translation-settings
PUT    /novels/{id}/translation-settings/{lang}

GET    /chapters/{id}/translation/{lang}          # 逐块原文+译文对照
POST   /chapters/{id}/translation/{lang}:run      # → {run_id}
POST   /novels/{id}/translation/{lang}:run        # 批量多章 → {run_id}
PATCH  /translation-blocks/{id}                   # 人工改译文
POST   /translation-blocks/{id}:lock
POST   /translation-blocks:batch-status           # 批量标 reviewed
POST   /chapters/{id}/translation/{lang}:retranslate-affected
                                                   # 术语改动后，只重译受影响的块
GET    /runs/{run_id}                             # 通用任务查询
GET    /runs/{run_id}/stream                      # SSE 进度
POST   /runs/{run_id}:cancel
```

`GET /chapters/{id}/translation/{lang}` 返回：
```jsonc
{ "blocks": [
    { "block_id":"b_1", "type":"dialogue", "speaker":"李白",
      "source":"「你来了。」", "target":"\"You've come.\"",
      "status":"draft", "locked":false,
      "glossary_hits":["青莲剑歌"],
      "warnings":[{"type":"name_drift","detected":"Li Bo","expected":"Li Bai"}] }
  ],
  "stats": { "total": 120, "translated": 110, "reviewed": 40, "locked": 12 } }
```

### 3.1 术语与一致性

```
GET    /novels/{id}/glossary?lang=en-US&status=
POST   /novels/{id}/glossary
PATCH  /glossary/{id}
DELETE /glossary/{id}
POST   /novels/{id}/glossary:import              # CSV/JSON
GET    /novels/{id}/glossary:export

POST   /novels/{id}/glossary/candidates:mine     # 从已译内容挖掘候选术语 → {run_id}
GET    /novels/{id}/glossary/candidates
POST   /glossary/candidates/{id}:approve         # 一键入库
POST   /glossary/candidates:batch-approve
POST   /glossary/candidates/{id}:reject

GET    /novels/{id}/consistency/warnings?status=open
POST   /consistency/warnings/{id}:resolve        # {action: "apply_canonical"|"accept_variant"|"ignore"}
POST   /novels/{id}/consistency:scan             # 全书重扫 → {run_id}
```

---

## 3.2 世界观转译 WorldView（★ 详见 `06_WORLDVIEW_TRANSLATION.md`）

```
GET    /world-profiles                          # 世界观档案（全局模板 + 本书专属）
POST   /world-profiles
PATCH  /world-profiles/{id}
POST   /world-profiles/{id}:fork                # 基于 parent 派生（昭和 → 昭和·乡村）
GET    /world-profiles/{id}/versions

GET    /novels/{id}/transforms                  # 本书的所有世界观映射
POST   /novels/{id}/transforms                  # {source_profile_id, target_profile_id, lang, policy}
PATCH  /transforms/{id}
POST   /transforms/{id}:activate
GET    /transforms/{id}/coverage                # 覆盖率：人名/名物/称谓 各多少已确认

# L3 名物词表
GET    /transforms/{id}/lexicon?category=&status=&q=
POST   /transforms/{id}/lexicon
PATCH  /lexicon/{id}
DELETE /lexicon/{id}
POST   /transforms/{id}/lexicon:import-template  # {pair_code:"cn_ancient__jp_showa"}
POST   /transforms/{id}/lexicon:mine             # 从章节文本挖掘候选 → {run_id}
POST   /transforms/{id}/lexicon:rag-fill         # RAG 补全 target_term 候选 → {run_id}
POST   /lexicon/{id}:approve
POST   /lexicon:batch-approve
POST   /lexicon/{id}:lock
GET    /transforms/{id}/lexicon:export           # CSV / JSON

# L1 人名
GET    /transforms/{id}/names?family_key=
POST   /transforms/{id}/names:suggest            # 按 family_key 整族一次生成 → {run_id}
PATCH  /names/{id}                               # 选定候选 / 手改
POST   /names/{id}:lock
POST   /transforms/{id}/names:check-family       # 家族姓氏一致性检查

# L4 视觉变体
GET    /entities/{id}/visual-variants
PUT    /entities/{id}/visual-variants/{profile_id}
POST   /entities/{id}/visual-variants/{profile_id}:generate

# 违规
GET    /transforms/{id}/violations?kind=&severity=&status=open
POST   /violations/{id}:resolve                  # {action:"apply_expected"|"accept"|"ignore"}
POST   /transforms/{id}:scan                     # 全书重扫三道闸 → {run_id}
POST   /transforms/{id}:retranslate-violations   # 只重译违规块 → {run_id}
```

`GET /transforms/{id}/coverage` 返回，直接驱动世界观工作台的卡片：
```jsonc
{
  "source": {"code":"cn_tang_classical","display_name":"中国·唐·古典"},
  "target": {"code":"jp_showa","display_name":"日本·昭和"},
  "version": 3, "status": "active",
  "coverage": {
    "names":      {"total": 42,  "approved": 42,  "locked": 38},
    "lexicon":    {"total": 240, "approved": 218, "candidate": 22},
    "honorifics": {"total": 16,  "approved": 16},
    "visual":     {"total": 42,  "approved": 31}
  },
  "violations": {"high": 0, "medium": 4, "low": 11}
}
```

---

## 4. 世界观 World

```
GET    /novels/{id}/entities?kind=character
POST   /novels/{id}/entities
GET    /entities/{id}
PATCH  /entities/{id}
DELETE /entities/{id}
POST   /entities:merge                           # 合并重复实体
POST   /entities/{id}:lock

POST   /chapters/{id}/entities:extract           # 从章节抽取实体 → {run_id}
POST   /entities/{id}/visual-prompt:generate     # AI 写视觉描述
POST   /entities/{id}/refs:generate              # 生成人设参考图 (n 张选一)
POST   /entities/{id}/refs:upload
DELETE /entities/{id}/refs/{asset_id}

GET    /entities/{id}/states                     # 角色成长历史（按章节）
PUT    /entities/{id}/states/{chapter_order}
GET    /voices?language=&gender=                 # 透传 capability audio.voice_list
PUT    /entities/{id}/voice                      # 绑定音色
POST   /entities/{id}/voice:preview              # 试听一句
```

---

## 5. 分镜与生成 Shots

```
GET    /chapters/{id}/shot-plan?lang=en-US
POST   /chapters/{id}/shot-plan:generate         # → {run_id}
GET    /chapters/{id}/shot-plan/versions
POST   /chapters/{id}/shot-plan/versions/{v}:activate

PATCH  /shots/{id}                               # 改时长/运镜/描述
POST   /shots/{id}:split
POST   /shots:merge
POST   /shots:reorder
DELETE /shots/{id}

PATCH  /frame-specs/{id}                         # 改 prompt / 参考图 / 参数
POST   /frame-specs/{id}:generate                # 单帧生成 → {gen_task_id}
POST   /frame-specs/{id}:approve
POST   /frame-specs:batch-generate               # {ids:[], only_missing:true}

PATCH  /audio-specs/{id}
POST   /audio-specs/{id}:generate
POST   /audio-specs:batch-generate

POST   /scenes/{id}/background:generate          # 场景底图
POST   /scenes/{id}/bgm:generate
POST   /scenes/{id}/ambience:generate

# 一键：整章跑完所有缺失素材
POST   /chapters/{id}/assets:generate-all        # {scope:["frames","audio","bg","bgm"], only_missing:true} → {run_id}
POST   /chapters/{id}/shots/{sid}/video:generate # 首尾帧 → 视频片段
```

### 5.1 任务中心

```
GET    /gen-tasks?status=&capability=&chapter_id=
GET    /gen-tasks/{id}
POST   /gen-tasks/{id}:retry
POST   /gen-tasks/{id}:cancel
POST   /gen-tasks:batch-retry                    # {filter:{status:"failed", chapter_id:"..."}}
POST   /gen-tasks/callback                       # ★ 中间层回调入口（HMAC 校验，无需 JWT）
GET    /gen-tasks/stream                         # SSE：全局任务状态推送
```

### 5.2 导出

```
POST   /chapters/{id}/export                     # {format: "manifest"|"srt"|"fcpxml"|"zip"}
GET    /exports/{id}                             # 下载
```

**`manifest` 格式**（交付给外部合成/剪辑的最终产物）：
```jsonc
{
  "chapter": {...}, "language": "en-US", "fps": 24,
  "shots": [
    { "index": 1, "duration_ms": 4000,
      "first_frame": "assets/f_001.png",
      "last_frame":  "assets/f_002.png",
      "video":       "assets/v_001.mp4",
      "camera": {"move":"push_in","speed":0.4},
      "audio": [ {"kind":"dialogue","file":"assets/a_001.wav","start_ms":0,
                  "duration_ms":1830,"speaker":"Li Bai","text":"You've come."} ],
      "subtitle": {"text":"You've come.","start_ms":0,"end_ms":1830} }
  ],
  "scenes": [ {"index":1, "bg":"assets/bg_001.png", "bgm":"assets/bgm_001.mp3",
               "ambience":"assets/amb_001.mp3", "shot_range":[1,6]} ]
}
```

---

## 6. 设置 Settings

```
GET    /settings/endpoints
POST   /settings/endpoints
PATCH  /settings/endpoints/{id}
POST   /settings/endpoints/{id}:test             # 真实请求 /cap/v1/health
POST   /settings/endpoints/{id}:refresh-caps     # 拉 /cap/v1/capabilities
GET    /settings/capabilities                    # 聚合后的能力+模型+param_schema（前端渲染表单用）

GET    /settings/routes
PUT    /settings/routes                          # 整表提交，简单可靠
GET    /settings/prompts                         # 系统提示词模板（剧本/抽取/翻译）
PUT    /settings/prompts/{key}

GET    /me
POST   /auth/login
POST   /auth/logout
```

---

## 7. 路由数量对照

| 模块 | v1 | v2 |
|------|---:|---:|
| 书架/章节 | 2879 行 | 12 |
| 剧本 | 762 行 | 12 |
| 翻译+术语 | 3391 行 | 20 |
| 世界观 | 573+503+821 行 | 13 |
| 世界观转译 ★ | 684 行（未接线） | 30 |
| 分镜生成 | 分散在 8 个文件 | 20 |
| 任务 | 676+895+2168 行 | 7 |
| 设置 | 3145 行 | 11 |
| **合计** | **145+** | **~125 → 核心 60** |
