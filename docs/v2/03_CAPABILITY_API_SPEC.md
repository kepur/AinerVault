# 03 · Capability API 标准 v1.0

> **这份文档定义 AinerN2D Core 与「能力中间层」之间的唯一契约。**
> Core 是 Client，中间层是 Server。中间层内部怎么对接 OpenAI / Gemini / 即梦 / 可灵 / Runway / ComfyUI / ElevenLabs / Fish-Audio，Core 一概不知也不关心。
>
> 契约版本通过 `X-Capability-Version: 1.0` 头协商。

---

## 1. 设计原则（六条，全部有理由）

| # | 原则 | 理由 |
|---|------|------|
| 1 | **按能力寻址，不按厂商寻址** | 厂商 API 半年一变，能力语义十年不变。Core 代码里永远不出现厂商名。 |
| 2 | **统一异步模型：submit → task_id → 回调（轮询兜底）** | 图/视频动辄 30s–5min，同步必然超时。文本类可用同步快捷通道。 |
| 3 | **能力自描述（Discovery）** | 中间层用 JSON Schema 声明每个能力/模型的参数。**后台据此自动渲染参数表单** —— 这是"后台不再反人类"的技术前提：加一个模型，后台零改动。 |
| 4 | **媒体一律用 `AssetRef`，不裸传 base64** | 首尾帧链路要反复传图，base64 会撑爆请求体和日志。默认传 URL。 |
| 5 | **幂等键强制** | 生成很贵。重试、页面重复点击、任务重放都不能重复扣费。 |
| 6 | **成本与实际厂商必须回报** | Core 不做路由决策，但必须能审计"这一帧花了多少钱、谁生成的"。 |

---

## 2. 通用规范

### 2.1 Base 与鉴权
```
Base URL:  https://<your-gateway>/cap/v1
Header:    Authorization: Bearer <token>
           X-Capability-Version: 1.0
           Content-Type: application/json
```

### 2.2 AssetRef —— 所有媒体的统一表示

```jsonc
// 输入侧，三选一
{ "url": "https://minio.local/ainer/img/01H....png" }   // 首选
{ "asset_id": "as_01H..." }                              // 中间层曾产出的资产，可内部复用
{ "b64": "iVBORw0...", "mime": "image/png" }             // 仅限 <2MB 的小图

// 输出侧，中间层必须返回
{
  "url": "https://cdn.vendor/xxx.png",
  "mime": "image/png",
  "bytes": 1843200,
  "sha256": "9f86d0...",          // 可选但强烈建议
  "meta": { "width": 1280, "height": 720, "seed": 4212 }
}
```

> Core 收到 output 后会**立刻转存到自己的 MinIO**，不依赖厂商 URL 的存活期。中间层无需保证 URL 长期有效，但需保证 **≥30 分钟**可下载。

### 2.3 幂等

请求体必带 `idempotency_key`（Core 用 `sha256(capability + 规范化input)` 生成）。

- 同 key 重复提交 → 返回**同一个 `task_id`**，HTTP `200`（而非 `201`），不重复计费。
- 幂等记录保留 ≥ 7 天。

### 2.4 请求信封

```jsonc
POST /cap/v1/tasks
{
  "capability": "image.text_to_image",
  "idempotency_key": "sha256:...",
  "model": "seedream-4.0",          // 可选。null = 中间层按自己的策略选
  "input": { /* 因 capability 而异，见 §4 */ },
  "options": {
    "priority": "normal",           // low | normal | high
    "timeout_ms": 300000,
    "callback_url": "https://core.local/api/v1/gen-tasks/callback",
    "callback_secret": "whsec_...", // 用于 HMAC 签名校验
    "max_cost": 0.50,               // 超过则直接失败，不执行
    "trace_id": "tr_01H..."
  }
}
```

### 2.5 响应信封（提交）

```jsonc
// 202 Accepted
{
  "task_id": "ct_01H8XY...",
  "status": "queued",              // queued | running | succeeded | failed
  "capability": "image.text_to_image",
  "estimated_ms": 25000,
  "accepted_at": "2026-08-26T10:00:00Z"
}
```

### 2.6 任务查询

```
GET /cap/v1/tasks/{task_id}
```
```jsonc
{
  "task_id": "ct_01H8XY...",
  "status": "succeeded",
  "capability": "image.text_to_image",
  "progress": 1.0,                 // 0..1，能给就给
  "output": { /* 见 §4 各能力 */ },
  "usage": {
    "cost": 0.032,
    "currency": "USD",
    "duration_ms": 24310,
    "tokens": null,
    "units": { "images": 1 }
  },
  "provider": "volcengine",        // 实际执行厂商，仅供审计
  "model": "seedream-4.0",
  "error": null,
  "submitted_at": "...",
  "finished_at": "..."
}
```

失败时：
```jsonc
{
  "status": "failed",
  "output": null,
  "error": {
    "code": "CONTENT_POLICY_BLOCKED",   // 见 §6
    "message": "prompt rejected by upstream moderation",
    "retryable": false,
    "provider_raw": { "...": "原始错误，透传即可" }
  }
}
```

### 2.7 回调（首选完成通知）

中间层在任务终态时 `POST` 到 `options.callback_url`，body 即 §2.6 的完整对象。

```
Header: X-Cap-Signature: sha256=<hex(hmac_sha256(callback_secret, raw_body))>
        X-Cap-Task-Id: ct_01H8XY...
```

- Core 返回 2xx 视为送达；否则中间层按 `1s, 5s, 30s, 5min, 30min` 重试 5 次。
- Core 同时有**轮询兜底**：`submitted_at + estimated_ms * 3` 后仍无回调则主动 `GET`。
- 回调必须幂等安全（Core 侧按 `task_id` 去重）。

### 2.8 取消
```
POST /cap/v1/tasks/{task_id}:cancel
```
尽力而为；已完成返回 `409`。

### 2.9 批量提交（可选实现，但强烈建议）
```
POST /cap/v1/tasks:batch
{ "tasks": [ {...}, {...} ] }     // ≤ 50
→ { "results": [ {task_id, status} | {error} ] }
```
一章书的分镜可能一次提交 40–200 个任务，逐个 HTTP 太慢。

---

## 3. Discovery —— 能力自描述（**必须实现**）

```
GET /cap/v1/capabilities
```

```jsonc
{
  "capability_version": "1.0",
  "capabilities": [
    {
      "capability": "image.text_to_image",
      "models": [
        {
          "id": "seedream-4.0",
          "display_name": "Seedream 4.0",
          "default": true,
          "async_only": true,
          "estimated_ms": 25000,
          "pricing": { "unit": "image", "cost": 0.032, "currency": "USD" },
          "limits": {
            "max_prompt_chars": 2000,
            "sizes": ["1024x1024", "1280x720", "720x1280", "1920x1080"],
            "max_ref_images": 4
          },
          // ★ 关键：后台按这份 schema 自动渲染参数表单
          "param_schema": {
            "type": "object",
            "properties": {
              "steps":  { "type": "integer", "minimum": 1, "maximum": 50, "default": 28,
                          "title": "采样步数" },
              "cfg":    { "type": "number", "minimum": 1, "maximum": 20, "default": 7.5,
                          "title": "提示词强度" },
              "seed":   { "type": "integer", "title": "随机种子",
                          "description": "留空则随机" },
              "style_strength": { "type": "number", "minimum": 0, "maximum": 1, "default": 0.6 }
            }
          }
        }
      ]
    }
    // ... 其余能力
  ]
}
```

Core 每 10 分钟缓存刷新一次，存入 `capability_endpoints.caps_cache_json`。

```
GET /cap/v1/health  →  { "ok": true, "version": "1.0", "upstreams": [{"provider":"...", "ok":true}] }
```

---

## 4. 能力清单（capability 枚举）

命名规范：`<domain>.<action>`，全小写下划线。**Core 只会调用下表中的能力。**

| capability | 用途 | 必须实现 |
|-----------|------|:--------:|
| `text.chat` | 剧本生成、实体抽取、术语挖掘等一切 LLM 调用 | ✅ |
| `text.translate` | 翻译（可由 `text.chat` 实现，但独立能力便于路由到专用模型） | ✅ |
| `image.text_to_image` | **首帧**、场景背景图、人物设定图 | ✅ |
| `image.image_to_image` | **尾帧**（从首帧派生）、风格迁移、场景变体 | ✅ |
| `image.edit` | 局部重绘（inpaint）、扩图（outpaint）、换装 | ⬜ |
| `image.upscale` | 出片前放大 | ⬜ |
| `audio.tts` | 对白/旁白配音 | ✅ |
| `audio.voice_list` | 列出可用音色（用于人物音色绑定 UI） | ✅ |
| `audio.music` | BGM 生成 | ⬜ |
| `audio.sfx` | 音效 / 环境音生成 | ⬜ |
| `video.image_to_video` | **首尾帧 → 视频片段**（本系统的终点） | ⬜ |

> ✅ = 主线必需，⬜ = 可延后。Core 会读 Discovery，未声明的能力在后台自动置灰并说明原因。

---

## 4.1 `text.chat`

```jsonc
"input": {
  "messages": [
    { "role": "system", "content": "..." },
    { "role": "user",   "content": "..." }
  ],
  "temperature": 0.7,
  "max_tokens": 8192,
  "response_format": { "type": "json_schema", "schema": { /* JSON Schema */ } },
  "stream": false
}
```
```jsonc
"output": {
  "text": "...",
  "json": { /* response_format 为 json_schema 时，解析后的对象 */ },
  "finish_reason": "stop"      // stop | length | content_filter
}
```

**要求**：
- 支持 `response_format.json_schema` 并**保证输出可解析**（内部做重试/修复）。剧本生成、实体抽取全靠这个，返回一段带 ` ```json ` 围栏的自然语言是不可接受的。
- `usage.tokens: { prompt, completion, total }`。
- 长文本任务需支持 `max_tokens ≥ 8192`。

**同步快捷通道**（文本类专用）：
```
POST /cap/v1/invoke     # 同上请求体，但直接返回 §2.6 的终态对象
```
`text.*` 能力应支持此通道（≤60s）。图像/视频禁止。

---

## 4.2 `text.translate`

```jsonc
"input": {
  "source_language": "zh-CN",
  "target_language": "en-US",
  "segments": [
    { "id": "b_001", "text": "他推开门。", "kind": "narration" },
    { "id": "b_002", "text": "「你来了。」", "kind": "dialogue", "speaker": "李白" }
  ],
  "glossary": [
    { "source": "青莲剑歌", "target": "Azure Lotus Sword Chant", "note": "功法名，不可意译" }
  ],
  "style_prompt": "英式书面语，第三人称过去时，保留东方玄幻语感",
  "context_before": "...上一块原文与译文，用于接续...",
  "context_after": "..."
}
```
```jsonc
"output": {
  "segments": [
    { "id": "b_001", "text": "He pushed the door open.", "glossary_hits": [] },
    { "id": "b_002", "text": "\"You've come.\"", "glossary_hits": ["青莲剑歌"] }
  ]
}
```

**要求**：
- **必须逐段对齐返回**，`id` 一一对应，不得合并或漏段。这是长文翻译一致性的生死线。
- `glossary` 中的术语必须原样使用；若被迫改写，在 `glossary_hits` 之外加 `warnings`。
- 若中间层无专用翻译模型，用 `text.chat` 实现即可，但仍需满足对齐要求。

---

## 4.3 `image.text_to_image` —— 首帧 / 背景图

```jsonc
"input": {
  "prompt": "cinematic wide shot, ancient Chinese city gate at dusk, light rain, ...",
  "negative_prompt": "text, watermark, extra limbs, blurry",
  "width": 1280,
  "height": 720,
  "n": 1,
  "reference_images": [                 // 角色/风格一致性参考
    { "ref": { "url": "https://..." }, "role": "character", "weight": 0.8,
      "tag": "li_bai" },
    { "ref": { "url": "https://..." }, "role": "style", "weight": 0.5 }
  ],
  "params": { "seed": 4212, "steps": 28, "cfg": 7.5 }   // 由 Discovery param_schema 约束
}
```
```jsonc
"output": {
  "images": [ { "url": "...", "mime": "image/png", "bytes": 1843200,
                "meta": { "width": 1280, "height": 720, "seed": 4212 } } ]
}
```

**`reference_images[].role` 语义约定**（中间层负责映射到各厂商的具体机制）：

| role | 含义 | 典型映射 |
|------|------|---------|
| `character` | 人物长相一致性 | IP-Adapter FaceID / 角色参考 / subject reference |
| `style` | 画风一致性 | style reference / LoRA |
| `composition` | 构图/姿势 | ControlNet pose·depth |
| `scene` | 场景空间一致性 | i2i 低强度 / scene reference |

不支持某个 role 时，**忽略并在 output 加 `warnings: ["ref role 'composition' not supported"]`**，不要报错。

---

## 4.4 `image.image_to_image` —— **尾帧（后针）**

这是本系统最核心的一次调用。尾帧必须从首帧派生，否则人物必崩。

```jsonc
"input": {
  "image": { "url": "https://.../first_frame.png" },   // 首帧
  "prompt": "same scene and character, he has now stepped through the gate, back half-turned",
  "negative_prompt": "...",
  "strength": 0.35,          // ★ 0=完全不变, 1=完全重绘。尾帧推荐 0.25–0.45
  "reference_images": [ ... ],
  "params": { "seed": 4212 }    // 与首帧同 seed 提升连贯度
}
```
```jsonc
"output": { "images": [ { "url": "...", "meta": { "width":1280, "height":720 } } ] }
```

**要求**：`strength` 语义必须统一为"改动幅度"（0 保持原图，1 完全重绘）。厂商语义相反的（如某些 API 的 `image_strength` 是"保留强度"）由中间层做 `1-x` 转换。**这是最容易出错的一处，务必在适配器里写测试。**

---

## 4.5 `image.edit`（局部重绘 / 扩图）

```jsonc
"input": {
  "image": { "url": "..." },
  "mask":  { "url": "..." },         // 白=重绘区，黑=保留区。省略则由 prompt 自动定位
  "prompt": "change the red robe to a torn grey cloak",
  "mode": "inpaint",                 // inpaint | outpaint | remove
  "outpaint": { "left": 0, "right": 512, "top": 0, "bottom": 0 }  // mode=outpaint
}
```

---

## 4.6 `audio.tts` —— 对白 / 旁白

```jsonc
"input": {
  "text": "You've come.",
  "language": "en-US",
  "voice_id": "vc_male_calm_01",     // 来自 audio.voice_list
  "params": {
    "speed": 1.0,                    // 0.5–2.0
    "pitch": 0,                      // -12..+12 半音
    "volume_db": 0,
    "emotion": "calm",               // 自由文本；不支持则忽略并 warn
    "style_prompt": "低沉，略带疲惫"    // 支持指令式 TTS 的模型用
  },
  "reference_audio": { "url": "..." },  // 声音克隆参考，可选
  "output_format": "wav",               // wav | mp3 | ogg
  "sample_rate": 44100,
  "with_timestamps": true               // ★ 见下
}
```
```jsonc
"output": {
  "audio": { "url": "...", "mime": "audio/wav", "bytes": 320044,
             "meta": { "duration_ms": 1830, "sample_rate": 44100 } },
  "timestamps": [                       // with_timestamps=true 时返回
    { "text": "You've", "start_ms": 0,   "end_ms": 420 },
    { "text": "come",   "start_ms": 480, "end_ms": 900 }
  ]
}
```

**`duration_ms` 是硬要求**。Core 用它回填 `shots.duration_ms`，整条时间线的长度由配音决定，不是由估算决定。
`timestamps` 用于字幕和口型，能给就给。

---

## 4.7 `audio.voice_list`

```
GET /cap/v1/voices?language=en-US&gender=male
```
```jsonc
{
  "voices": [
    { "voice_id": "vc_male_calm_01", "display_name": "Ethan · 沉稳男声",
      "languages": ["en-US", "en-GB"], "gender": "male", "age": "adult",
      "tags": ["calm", "narration"],
      "preview_url": "https://.../preview.mp3",
      "supports": { "clone": false, "emotion": true, "timestamps": true } }
  ]
}
```
后台的"人物音色绑定"页面直接渲染这个列表 + 试听。

---

## 4.8 `audio.music` / `audio.sfx`

```jsonc
// audio.music
"input": {
  "prompt": "tense guqin and low strings, ancient Chinese, building dread",
  "duration_ms": 45000,
  "loopable": true,
  "instrumental": true
}
// audio.sfx
"input": { "prompt": "wooden door creaking open, rain outside", "duration_ms": 2500 }
```
output 同 `audio.tts` 的 `audio` 字段。

---

## 4.9 `video.image_to_video` —— **首尾帧 → 片段**

```jsonc
"input": {
  "first_frame": { "url": "https://.../first.png" },
  "last_frame":  { "url": "https://.../last.png" },   // 省略则为单帧驱动
  "prompt": "slow push-in, light rain falling, cloth moving in wind",
  "duration_ms": 4000,
  "fps": 24,
  "width": 1280, "height": 720,
  "camera": {
    "move": "push_in",        // static|push_in|pull_out|pan_left|pan_right|tilt_up|tilt_down|orbit_left|orbit_right|handheld
    "speed": 0.4              // 0..1
  },
  "params": { "seed": 4212, "motion_strength": 0.5 }
}
```
```jsonc
"output": {
  "video": { "url": "...", "mime": "video/mp4",
             "meta": { "width":1280, "height":720, "fps":24, "duration_ms":4000,
                       "has_audio": false } },
  "last_frame": { "url": "..." }    // 实际末帧，可作下一镜头的首帧 → 长镜头接续
}
```

**`output.last_frame` 请务必返回**：它让「上一镜头的真实末帧 → 下一镜头的首帧」成为可能，是长片连贯性的关键。

---

## 5. 参数不支持时的行为（重要）

中间层**永远不要因为某个可选参数不支持就整体报错**。规则：

1. 该参数属于 `input` 顶层语义（如 `last_frame`、`duration_ms`）→ 若无法满足，返回 `error.code = CAPABILITY_UNSUPPORTED`，并在 message 说明缺哪一项。
2. 该参数属于风格化增强（`emotion`、`negative_prompt`、某个 `ref role`、`seed`）→ **静默降级**，在 `output.warnings[]` 里记录。

```jsonc
"output": { "images": [...], "warnings": ["seed ignored: upstream does not support deterministic sampling"] }
```

Core 会把 warnings 展示在后台的任务卡片上，但不阻断流程。

---

## 6. 错误码（统一枚举）

| code | HTTP | retryable | 含义 |
|------|:----:|:---------:|------|
| `INVALID_REQUEST` | 400 | ✗ | 请求体不合契约 |
| `CAPABILITY_UNSUPPORTED` | 400 | ✗ | 该能力/模型/关键参数不支持 |
| `MODEL_NOT_FOUND` | 404 | ✗ | 指定 model 不存在 |
| `UNAUTHORIZED` | 401 | ✗ | token 无效 |
| `QUOTA_EXCEEDED` | 402 | ✗ | 账户余额/配额不足 |
| `COST_LIMIT_EXCEEDED` | 400 | ✗ | 预估成本超过 `options.max_cost` |
| `RATE_LIMITED` | 429 | ✓ | 限流，响应带 `Retry-After` |
| `CONTENT_POLICY_BLOCKED` | 422 | ✗ | 上游内容审核拒绝 |
| `UPSTREAM_ERROR` | 502 | ✓ | 厂商 5xx / 异常 |
| `UPSTREAM_TIMEOUT` | 504 | ✓ | 厂商超时 |
| `TASK_FAILED` | 200 | 视情况 | 异步任务终态失败，详见 `error.retryable` |
| `INTERNAL_ERROR` | 500 | ✓ | 中间层自身故障 |

Core 的重试策略：`retryable=true` → 指数退避 `2s/8s/30s`，最多 3 次；`false` → 直接标失败，等人工处理。

---

## 7. 最小实现清单（中间层 MVP）

按此顺序实现即可跑通全链路：

```
□ GET  /cap/v1/health
□ GET  /cap/v1/capabilities        ← 哪怕先返回硬编码 JSON
□ POST /cap/v1/invoke              ← text.chat  (同步)
□ POST /cap/v1/tasks               ← image.text_to_image
□ GET  /cap/v1/tasks/{id}
□ 回调 POST + HMAC 签名
□ POST /cap/v1/tasks               ← image.image_to_image  (尾帧, 注意 strength 语义!)
□ POST /cap/v1/tasks               ← audio.tts  (必须回 duration_ms)
□ GET  /cap/v1/voices
□ POST /cap/v1/tasks:batch
□ video.image_to_video / audio.music / audio.sfx  (后续)
```

---

## 8. 契约演进

- 新增能力 / 新增可选参数 → 不升版本，通过 Discovery 自然生效。
- 修改已有字段语义 / 删除字段 → 升 minor（`1.1`），Core 按 `X-Capability-Version` 兼容两个版本。
- 中间层收到不认识的 `X-Capability-Version` → 按自己支持的最高版本处理，并在响应头回 `X-Capability-Version-Served`。
