# LTX 2.5 接入需求（交给模型端）

> **2026-09-28 更新：模型端改由本会话直接实现，下面是已落地的状态；原需求保留在后面作契约说明。**
>
> **网关（`ml-stable-diffusion/ai-studio`，不在 git，改前备份在会话临时目录）**
> - `video.image_to_video` 新增模型 `ltx-2.5-22b-distilled`（非默认；core 按用途路由显式指定）。
> - 支持：文生视频、首帧/尾帧/任意关键帧锚、`audio.mode=generate|none|drive`（a2v 配音驱动）、分段提示词、
>   `quality=preview` 只跑第一阶段＋`resume_token` 续跑、`control`（2.3 Union Control IC-LoRA，深度/骨架/边缘可多路）、
>   `reference_sheet`（2.5 Ingredients IC-LoRA，主角一致）。
> - 输出：mp4（含音轨）、48k wav、实际首帧/末帧、按实际帧数算的时长、warnings。
> - 运行：走全局推理锁；进度按步上报；240 秒无进度杀进程组重试；可取消；跑前让 ComfyUI 释放内存。
> - 引擎入口 `scripts/ltx25_infer.py`：`generate`（含 `--stage1-only/--resume`、`--segment`）、`a2v`、`iclora`。
>
> **core**
> - 路由：用途 `shot_video_ltx25`、`director_final_ltx25` → `ltx-2.5-22b-distilled`；通配仍是 2B（老流程不变）。
> - 分镜：`app/pipelines/ltx25_shots.py` ＋ `POST /api/v2/shot-plans/{id}/videos:ltx25`。不要首尾帧；
>   有对白的镜头按配音驱动口型，没对白的镜头模型出同步音效（成片时替掉程序化拟音）。
>   提示词按「场景头（同场每镜一字不差）→ 人物外貌 → 构图 → 动作 → 声音」拼：只有文字时，
>   逐镜各写的光线和地点会互相矛盾（实跑同一场走廊戏出成了室外、隧道）。
> - 旧首尾帧已清：16 张解绑，备份 `code/apps/ainer-core/var/backups/20260928_frame_specs_before_ltx25.jsonl`。
>
> **实测结论**见 §13。

- **提出方**：ainer-core，包括 Director Core 和小说分镜成片管线
- **承接方**：模型端，包括：
  - 能力网关 `ml-stable-diffusion/ai-studio`（:7999，`cap_api.py` / `server.py`）
  - 引擎 `ltx25-mlx`（入口 `ai-studio/scripts/ltx25_infer.py`，已有 `generate` / `a2v`）
- **日期**：2026-09-28
- **流程**：模型端按 P0 → P1 → P2 的顺序做。做完跑一遍 §10 的验收，把 §11 的回报清单交回。core 这边再接入、打开开关、做端到端测试（§12）。

---

## 0. 一句话

我们要网关提供一个**本机 LTX 2.5 成片模型**，不依赖首尾帧。它要能做下面几件事：

- 文生视频，自带同步音轨；
- 关键帧锚定，可选；
- 用我们的配音驱动画面（a2v）；
- 用 Blender 控制视频驱动画面（IC-LoRA union，或白模重绘）。

输出要如实回报**实际帧数、时长、音轨、实际首末帧**。

## 1. 背景（模型端需要知道的）

- **用户决定：现有首尾帧全部作废。** 它们是 FLUX 出的首帧和尾帧，画面有问题，人物也有问题。成片不再走「FLUX 首帧＋尾帧 → LTXV 插值」这条主路，改成 LTX 2.5 直接出片；关键帧只是可选的锚点。
  - 模型端**不用删**现有的 2B 首尾帧工作流，留着当回退。
- **core 有两条调用链：**
  1. **Director Core**：
     - 流程：3D-BOX 或一句话 → Scene Protocol → Blender 无头渲控制素材 → 渲染器适配层 → 网关。
     - 控制素材包括 preview / clay / depth / pose / canny，以及 camera.json / motion.json。
     - 适配层 `LTX25Adapter` 的 payload、校验和 mock 已经写好（`code/apps/ainer-core/app/director/renderers/ltx25.py`），开关 `ltx25_enabled` 关着。
  2. **小说分镜**：
     - 流程：剧本 → 分镜 → 运动单（英文动作／物理提示词，外加 `action_ms`）→ 视频 → TTS 对白 → 合成。
     - 视频请求在 `code/apps/ainer-core/app/pipelines/cut.py` 的 `generate_videos`。
- **硬约束（用户定的）：**
  - 禁止云端，只跑本机，免费；
  - 同一时刻只跑一个重活（单线程或协程排队）；
  - **卡住就直接杀掉进程、换一个新进程**；
  - 运行时不联网下载。
- **契约基线**：`docs/v2/03_CAPABILITY_API_SPEC.md`，内容包括：
  - tasks 的提交、查询、取消、回调；
  - AssetRef；
  - 错误码；
  - 可选参数不支持时写进 `warnings` 静默降级；
  - 幂等。

  本需求只在它上面扩展，**不改已有字段的含义**。

## 2. 挂在哪：能力与模型 id

- **能力名不变**：仍然是 `video.image_to_video`。core 的能力枚举、路由、超时、Director 适配器都挂在它上面。在它的 `models` 里**新增一个模型**：
  - id 暂定 `ltx-2.5-22b-distilled`，名字可以改，告诉我即可；
  - display_name：「LTX-2.5 22B 蒸馏 Q8（本地 MLX）」；
  - `default: true`。
- **保留** `ltxv-2b-distilled` 作第二个模型（回退）。
  - ltx25 失败时，网关**不要自动偷偷降级到 2B**，core 要知道片子到底是谁出的。
- **分派**：网关按任务请求体里的 `model` 分派。core 的路由（CapabilityRoute）可以给每个 purpose 指定 model，所以不用靠 input 里的字段猜。
- **对 ltx25 放宽的地方**：
  - `input.first_frame` 改成**可选**，缺省就是文生视频。现在的 `_run_image_to_video` 缺首帧会直接报错，这条对 ltx25 要放开。
  - `motion` 的语义：
    - `auto` 一律当 `animate`。现在 2B 路径在「没给尾帧」时会判成 kenburns 静帧，ltx25 不能这样。
    - `hold` / `kenburns` 只在给了 `first_frame` 时有效。

## 3. 输入字段（ltx25 模型）

| 字段 | 类型 | 必填 | 说明 | 不支持 / 越界时 |
|---|---|:-:|---|---|
| `prompt` | string | ✓ | 英文。写法见 §3.1 | — |
| `duration_ms` | int \| `"auto"` | ✓ | 帧数算法见表后说明。`"auto"` 表示让 DurationHead 预测时长（P2）| 超上限 → `CAPABILITY_UNSUPPORTED`，message 写明上限 |
| `fps` | int | | 默认 24 | 其它值 → 用 24 ＋ warning |
| `width` / `height` | int | ✓ | 对齐规则见表后说明 | 自动对齐 ＋ warning |
| `params.seed` | int | | 同 seed 同输入应能复现 | — |
| `style` | string | | photoreal / anime / cinematic / auto，沿用网关现有的 `_apply_style`。**只认顶层**，`params.style` 忽略（现网约定）| — |
| `negative_prompt` | string | | 蒸馏版不跑 CFG 时会被忽略 | warning，不报错 |
| `camera` | `{move, speed}` | | 同契约 §4.9。没有运镜 LoRA 就并进提示词（沿用 `_with_camera`）| warning |
| `first_frame` | AssetRef | | 首帧锚（frame 0，strength 1.0）| — |
| `last_frame` | AssetRef | | 尾帧锚（frame = N−1）。core 新流程基本不用，接口保留 | — |
| `keyframes` | `[{image: AssetRef, frame_idx, strength}]` | | 任意帧锚，映射 `--image PATH IDX STRENGTH`。frame_idx 按像素帧、从 0 起；与 first/last 同时给时合并 | 越界 → `INVALID_REQUEST` |
| `segments` | `[{prompt, start_ms, end_ms}]` | | 分段提示词，见表后说明（P1）| 不支持 → 并成一句 ＋ warning |
| `audio` | `{mode, track?, start_ms?, speech?}` | | 见 §5 | — |
| `control` | object | | 见 §4 | — |
| `reference_images` | `[AssetRef + role/identity]` | | 人物身份参考。LTX 2.5 本身没有参考图入口，按 §6 的结论处理 | warning，不报错 |
| `quality` | `draft` \| `final` | | 草稿和成片两档，见表后说明 | — |

**补充说明：**

- **`duration_ms` 的帧数算法**：
  - 帧数 = round(duration_ms / 1000 × fps) + 1，再**向上**凑到 8n+1，首尾都算在内。例如 6000 ms @24 fps = 145 帧。
  - 向上凑是为了片子不比请求短：向下凑最多短 0.29 秒，配音驱动时会截掉最后一个字（实跑 1600 ms 出成 1.375 秒）。
    控制视频那条路例外，控制视频多长就只能出多长。
- **`width` / `height` 的对齐**：
  - 32 的倍数。如果两阶段管线要求 64，请在 limits 里写明，并自动对齐。
  - **横 16:9 和竖 9:16 都要支持**，短剧是竖屏。
- **`segments`（分段提示词，P1）**：
  - 对应 Prompt Relay（`--segment`），把一镜里的动作节拍按时间分给不同提示词。例如 0–3 s「A 冲上来挥右拳」、3–6 s「B 闪开前踢」。
  - core 会从 Scene Protocol 的 timeline 自动生成这些分段。
  - 毫秒换算成 latent 帧长度由网关负责。
- **`quality` 两档**：
  - `draft` 求快，用来预览；
  - `final` 用模型端认为本机最好的配置。
  - 本机只有蒸馏权重，两档具体怎么配，由模型端实测后决定。

### 3.1 请模型端实测后给一页「提示词写法」

core 的提示词编译器（`compose_frame_prompt` 和运动单）要按 LTX 2.5 的习惯重写。请说明以下几点：

- 推荐结构：比如是否按 Scene / Action / Camera / Audio 分段；长度上限多少；Gemma 编码的 token 上限多少。
- 人物外观要写多细，才能在不同镜头里保持稳定。
- 怎样写能让模型**不自己编台词**，但保留环境声和动作声。对白走我们的 TTS，角色音色要一致。
- 哪些运镜词好使，例如 dolly in、orbit、tracking、handheld。
- 我们会发英文。想知道混入少量中文专名会不会出问题。
- `--enhance-prompt`（让 Gemma 改写提示词）值不值得开，要多花多少时间。

## 4. Director／Blender：控制视频驱动（白模、深度、骨架、边缘）

### 4.1 我们给的素材（固定规格）

Blender 无头 worker 每个任务都产出下面这些文件。

**现成示例**：`/Users/mac/AinerWorkFlow/AinerHub_IDEA/code/apps/ainer-core/var/director/jobs/djob_01M3C7F5G0FDB490GF0M6FZWB5/`。内容是夜巷打斗：两个人、6 秒，A 冲近打右拳，B 闪避后前踢，镜头侧面跟拍。

| 文件 | 内容 |
|---|---|
| `preview.mp4` | EEVEE 预演：有明暗，灰人偶加灰场景 |
| `clay.mp4` | Workbench 白模 |
| `depth.mp4` | 视差深度图，规格见表后说明 |
| `pose.mp4` | OpenPose COCO-18 骨架（只有身体，没有手和脸），配色与 controlnet_aux 的 `draw_bodypose` 一致，黑底 |
| `canny.mp4` | 对 preview 逐帧做 Canny（ffmpeg edgedetect），白线黑底 |
| `first_frame.png` | preview 的第 1 帧。**它是灰的，不能直接拿来当首帧锚** |
| `camera.json` / `motion.json` | 逐帧的机位（位置、朝向、焦距），以及每个角色逐帧的位置、朝向、关节。网关不需要读 |

- **`depth.mp4` 规格**：
  - 近白远黑，按 1/z 线性映射到 near–far；
  - 整段用同一组 near/far，不逐帧归一化；
  - 背景纯黑。
- **所有视频的共同规格**（已用 ffprobe 核对）：
  - 分辨率 1024×576，16:9。分辨率可配，竖屏时是 576×1024。
  - 24 fps，帧数 8n+1（6 秒 = 145 帧）。
  - 编码 H.264 yuv420p，CRF 16（深度 CRF 12），带 faststart。
- **怎么传**：core 用 AssetRef.url 传绝对地址（`http://127.0.0.1:8100/...`），网关沿用现有的 `_fetch_asset` 去拉。

### 4.2 `control` 字段（ltx25）

这就是 `LTX25Adapter` 现在组出来的 payload，另外补了 `conditioning_strength` 和 `fidelity` 两个字段。字段名想调整的话，模型端定下来告诉我，我去改适配器。

```jsonc
"control": {
  "type": "union",                  // union | depth | pose | canny | v2v
  "videos": {                       // union：给一路或多路
    "depth": {"url": "..."}, "pose": {"url": "..."}, "canny": {"url": "..."}
  },
  "strengths": {"depth": 0.8, "pose": 1.0, "canny": 0.6},   // 各路强度：这是我们的初值，请实测后给推荐值
  "conditioning_strength": 1.0,     // IC-LoRA 注意力强度，映射 --conditioning-strength
  "fidelity": "balanced",           // tight | balanced | fast，映射见下方说明，请实测后给默认值
  "video": {"url": "..."},          // 单路 depth/pose/canny，或 v2v 时用
  "denoise": 0.92,                  // 只用于 v2v：0.3–1.0，越大越自由（越不像白模）
  "pin_first": false                // 给了 first_frame 时，要不要把首帧钉死
}
```

`fidelity` 三档映射到 ltx-2-mlx 的哪种跑法：

| 档位 | 映射 |
|---|---|
| `tight` | `--single-stage` |
| `balanced` | 默认两阶段 |
| `fast` | `--upsample-only`（可加 `--refine-steps`）|

### 4.3 要求

1. **Union 控制（P0，要下载，下载前先问用户）**
   - 需要 LTX-2.x 22B 的 IC-LoRA Union Control。ltx-2-mlx 的帮助里举的例子是 `Lightricks/LTX-2.3-22b-IC-LoRA-Union-Control`。
   - 请核实三件事：有没有 2.5 版；2.3 版能不能挂在本机的 2.5 蒸馏 **Q8** 权重上（量化权重能不能融 LoRA）；文件有多大。
   - **下载前先把仓库名、文件名、大小报给用户，用户点头了再下。**
   - 要支持多路同时喂（最常用的是 depth＋pose），各路强度可调。
2. **白模重绘 v2v（P0 兜底）**
   - IC-LoRA 没到位之前，先用这个兜底：把 preview 或 clay 编码成 latent，加噪到 denoise，再去噪。语义和现在 2B 的 `ltxv_v2v` 一样。
   - 如果 ltx-2-mlx 没有现成的 v2v，请评估改造成本和可行性，比如 retake 整段加强度。
   - **验收**：人和环境变成真实的，动作和机位跟着预演走。
3. **首帧**
   - 默认**不钉** Blender 的首帧。2B 实测过：钉灰首帧，整段都发灰；钉一张构图对不上的首帧，第 1 帧到第 2 帧会跳。
   - 只有 `pin_first=true`，而且给的是已经上好色的首帧，才钉。
4. **尺寸和帧数**
   - 请告诉我推荐的生成分辨率。**我会让 Blender 直接按那个尺寸渲控制素材**，避免宽高比不一致。例如 1024×576 是 1.78，832×448 是 1.86，两者不一样。
   - 万一尺寸还是对不上：等比缩放加居中裁切，**禁止拉伸**。
   - 控制视频比请求的帧数短：就按控制视频的长度出，在 output 里报实际帧数（现在 `_run_control_video` 就是这样做的）。
   - **不准悄悄重采样时间轴。**
5. **构图保持**
   - 成片的机位路径、人物位置要和控制素材一致。
   - 原因：后面要用 camera.json / motion.json 叠字幕、做连续性检查。
6. **组合能力**
   - union control 时，`audio.mode=generate`（环境声、动作声）要能同时出。
   - `audio.mode=drive`（a2v）能不能和 control 同时用，请实测后告诉我。我猜 a2v 管线不吃 IC-LoRA。
7. **Blender 那边要改就告诉我**
   - 如果 IC-LoRA 要的控制图规格和我们的不一样，比如：
     - 骨架要 DWPose 带手和脸；
     - 深度要逐帧归一化，或者近黑远白；
     - 边缘要更细，或阈值不同；
     - 要别的分辨率或帧率。
   - 请把要求写清楚，**Blender 渲染那边由我来改**。

### 4.4 V1 时说「到 2.5 再上」的几项

这几项请评估可行性。这轮只要求给结论，不要求全做。

| 项 | LTX 2.5 上的做法 | 优先级 |
|---|---|:-:|
| 复杂多条件混合 | 就是上面的 union control | P0 |
| 长视频拼接 | `extend`：从上一段的尾部接着生成，接缝不跳 | P1 |
| 动态 mask／局部重做 | `retake`：只重做某个时间段 | P1 |
| 空间局部重绘 | 只重画某个人或某块区域，能不能做 | P2（给结论）|
| 多角色分区控制 | 每个角色一块区域，各有自己的提示词和身份（类似我们 FLUX 的分区身份）| P2（给结论）|

## 5. 音频（LTX 2.5 自带同步音轨）

### 5.1 三种模式

`audio.mode` 有三种取值：

1. **`generate`**：模型自己出同步音轨（环境声、动作声、脚步、打击）。
   - `speech` 默认 false。为 false 时尽量不出人声台词。
   - 台词由我们的 TTS 配，因为角色音色要前后一致。
   - 如果人声压不住，请如实说明。那样我们只把它当环境声参考，或者直接丢掉。
2. **`none`**：不要音轨。如果能省时间，就只出画面。
3. **`drive`（a2v，P0）**：我们给这一镜的对白音轨，画面的口型和节奏跟着它走。
   - 音轨是 TTS 合好的 wav，24 kHz 单声道；可能有多句，也可能两个人在说。
   - **成片音轨必须原样是我们给的音频**：不重新生成，不变速。
   - `start_ms` 对应 `--audio-start`。
   - 音频比画面短：补静音（`ltx25_infer.py` 已经做了 apad）。
   - 音频比画面长：截断，并加一条 warning。

### 5.2 请实测后告诉我

- a2v 能不能同时带 first_frame / keyframes（脚本里 a2v 是支持 `--image` 的）。
- 两个人对话时，模型分不分得清谁在说。要不要在提示词里写明，比如「A speaks first, then B」。
- a2v 的时长上限是多少。

### 5.3 输出和 Discovery 声明

- **音轨输出**：音轨要**单独**给一个 wav（48 kHz），同时混进 mp4 里。
- **Discovery 声明**：请声明 `supports: {native_audio: true, audio_track_input: true, voice_reference: false}`。这些字段 core 已经有了。core 的交付清单（`delivery.detect_projection`）靠 `native_audio` 切换到「原生音频」投影。

## 6. 人物一致性（用户反馈「人物也有问题」）

去掉 FLUX 首尾帧之后，靠什么让同一个角色在不同镜头里长得一样？这是 core 最担心的一点。

请模型端**实测后给结论和推荐**，不需要每种都做成产品：

1. **单首帧锚**
   - 我们给一张「这个角色在这一镜里」的首帧（首帧怎么来另议），用 i2v 的 frame 0 锚住。
   - 问：5–8 秒内，LTX 2.5 能不能守住这张脸，不漂？
2. **多点关键帧锚**
   - 同一张图，在第 0 帧和中后段各锚一次。ltx-2-mlx 的帮助里说，锚两端可以 preserve identity。
   - 问：这样会不会把动作拉回原位？
3. **角色 LoRA**
   - 训练素材：角色库的五视角加表情九宫格，每个角色约 14 张。
   - 训练工具：ltx-2-mlx 的 `train`（需要 ltx-trainer-mlx）。
   - 问：
     - 本机能不能训？
     - 训一个要多久？
     - 推理时能同时挂几个角色 LoRA？
     - 要不要额外下载？要下载的话先问用户。
4. **其它方案**
   - 如果有 LTX-2.x 的参考图类或身份类 IC-LoRA，也请一并评估。

**回报**：每种方案给一段对比视频，加一句结论。

另外，如果模型端有更好的**本机出图模型**，能用来出角色设定图（五视角一致、性别和年龄准确），也请告诉我。现在角色立绘是 FLUX.2-klein 4B 出的。

## 7. 输出（ltx25 模型）

```jsonc
"output": {
  "video": {
    "url": "...", "mime": "video/mp4",
    "meta": {
      "width": 832, "height": 448, "fps": 24,
      "frames": 145,             // 用 ffprobe 数出来的实际帧数
      "duration_ms": 6041,       // = frames / fps，按实际帧数算，不按请求报
      "has_audio": true, "seed": 42,
      "model": "ltx-2.5-22b-distilled",
      "pipeline": "distilled | two_stage | ic_lora | a2v | v2v",
      "infer_ms": 0, "load_ms": 0, "peak_mem_gb": 0
    }
  },
  "audio": {
    "url": "...", "mime": "audio/wav",
    "meta": {"sample_rate": 48000, "duration_ms": 6041, "kind": "generated | input"}
  },
  "first_frame": {"url": "...png"},  // 成片的实际第 1 帧
  "last_frame":  {"url": "...png"},  // 成片的实际最后一帧：用于下一镜接续、缩略图、连续性检查
  "motion_decision": "animate",
  "warnings": ["negative_prompt ignored: distilled model runs without CFG"]
}
```

对输出的要求：

- **mp4**：H.264 yuv420p，有音轨时是 AAC 48 kHz，带 faststart。**文件的实际帧数必须等于 `meta.frames`。**
- **wav 的 mime**：要写 `audio/wav`。现在 `_asset_out` 的 mime 表里没有 .wav，会落成 octet-stream。

## 8. 运行与资源

1. **全局 GPU 锁**
   - LTX 2.5、ComfyUI（FLUX 出图、2B 视频）、TTS（MLX）三者同一时刻只能跑一个重活。
   - 排队中的任务在 task 里给出 `queue_position`。
   - LTX 2.5 的峰值内存：脚本注释说 low-ram 流式约 32 GB，请实测。
   - FLUX 和 LTX 同时驻留会不会爆内存，请实测。会爆的话，切换前先让 ComfyUI 释放显存（ComfyUI 有 `/free` 接口）。
2. **进度**
   - `progress` 取值 0–1。
   - 同时给 `stage`：load / encode_prompt / stage1 / upscale / stage2 / decode / audio / mux。
   - 同时给 `step` / `steps`，最好再带 `eta_ms`。
   - core 的 Director 面板会显示这些进度。
3. **看门狗**
   - 超过 N 秒没有新的进度行（建议 180 s，可配），就杀掉**整个进程组**，换一个新进程重跑一次。
   - 再卡住就判失败，`retryable=true`。
   - Metal 被系统看门狗杀掉的情况，也按可重试处理。
4. **取消**
   - `POST /cap/v1/tasks/{id}:cancel` 后 5 秒内杀掉子进程组、释放内存，任务状态变成 `cancelled`。
5. **预估耗时**
   - `estimated_ms` 要按「模式 × 分辨率 × 帧数」来算。
   - core 的超时 = 预估 × 3，预估偏小任务就会被误杀。分区身份以前就吃过这个亏：按单人编辑估的时间去跑三人，每次都被掐断。
   - 请给一张实测表，或者一个公式。
6. **常驻进程（P1）**
   - 请报 `load_ms`。
   - 如果每个任务重新加载 20 GB 权重占了大头，就做一个常驻 worker：模型留在内存里，空闲 N 分钟后自动退出、释放内存。
   - ComfyUI 需要内存时，常驻 worker 要能让出来。
7. **错误分类**
   - 缺权重或缺 LoRA → `CAPABILITY_UNSUPPORTED`，不可重试，message 写明缺哪个文件。
   - 参数不合法 → `INVALID_REQUEST`。
   - OOM、看门狗、进程崩溃 → `UPSTREAM_ERROR`，可重试。
8. **离线**
   - 设置 `HF_HUB_OFFLINE=1`，运行时不下载任何东西。
   - LoRA 只从本地路径加载。
9. **子进程环境**
   - 用最小环境启动（`env -i PATH HOME TMPDIR LANG` 加必需的变量），不继承会话里的凭据变量。

## 9. Discovery（`GET /cap/v1/capabilities`）里要声明的内容

```jsonc
{
  "id": "ltx-2.5-22b-distilled", "default": true, "async_only": true,
  "estimated_ms": 0,
  "pricing": {"unit": "clip", "cost": 0.0, "currency": "USD"},
  "limits": {
    "max_prompt_chars": 0,
    "sizes": ["832x448", "448x832", "1280x704", "704x1280"],
    "size_multiple": 32,
    "max_frames": 0, "max_duration_ms": 0, "fps": [24],
    "max_keyframes": 0, "max_segments": 0
  },
  "supports": {
    "native_audio": true, "audio_track_input": true, "voice_reference": false,
    "text_to_video": true, "keyframes": true, "segments": true,
    "auto_duration": false, "extend": false, "retake": false
  },
  "control_types": ["v2v", "union", "depth", "pose", "canny"],
  "audio_modes": ["generate", "none", "drive"],
  "quality": ["draft", "final"]
}
```

- 上面的 0 请换成实测值。`sizes` 请换成模型端推荐的分辨率。
- `control_types` **只列本机当前真能跑的**，按权重文件是否在盘上动态计算，照搬现在 `_control_ready()` 的做法。
- core 的 `LTX25Adapter` 会读 `control_types` 和 `supports`，据此决定面板上哪些选项能点，不会自己去猜。

## 10. 验收用例（做完跑一遍，把结果回填）

### 10.1 素材

- **控制素材**：`/Users/mac/AinerWorkFlow/AinerHub_IDEA/code/apps/ainer-core/var/director/jobs/djob_01M3C7F5G0FDB490GF0M6FZWB5/`
  - depth / pose / canny / clay / preview 五个 mp4
  - 1024×576，145 帧
- **对白音频**：`/Users/mac/AinerWorkFlow/AinerHub_IDEA/code/apps/ainer-core/var/media/ed2053b266f342a3043e239e577a99567c6e5cf4c6f691cfc454cfadd30ffe39.wav`
  - 3.36 s，24 kHz 单声道，Qwen3-TTS 中文
- **夜巷提示词**：

  ```
  Night, a narrow wet alley lit by neon signs. Two young men fight: man A in a black jacket runs in and throws a right punch; man B in a grey hoodie dodges and answers with a front kick. The camera tracks them from the side. Realistic, cinematic.
  ```

### 10.2 用例

| # | 用例 | 通过标准 |
|---|---|---|
| A1 | 文生视频：832×448，6000 ms，audio=generate | 145 帧；duration_ms=6041；has_audio；单独的 wav；first_frame / last_frame 都有 |
| A2 | 竖屏：448×832，4000 ms | 97 帧，画面不拉伸 |
| A3 | 首帧锚：用 A1 的 last_frame 当 first_frame | 成片第 1 帧与输入图的 SSIM ≥ 0.9 |
| A4 | 关键帧：第 0 帧 ＋ 第 96 帧 | 对应帧接近锚图，中间过渡自然 |
| A5 | 分段提示词：0–3 s 挥拳 / 3–6 s 前踢 | 两个动作按时间先后出现 |
| A6 | a2v：用上面的 wav；提示词写「一个人对着镜头说话」 | 口型对得上；输出音轨的时长和内容与输入一致（比 sha，或比波形相关）|
| A7 | union（depth＋pose）：夜巷素材 | 帧数与控制素材一致；两人的位置、动作和机位跟骨架走；附一段并排对比视频 |
| A8 | v2v 白模重绘：preview，denoise 0.92 | 真人、真环境，动作跟预演走 |
| A9 | 帧数：2000 / 6000 / 8000 ms，24 fps | 分别是 49 / 145 / 193 帧，`meta.frames` 与 ffprobe 一致 |
| A10 | 取消：提交 A1，20 s 后取消 | 5 s 内进程消失，状态 cancelled，内存回落 |
| A11 | 卡死：跑到一半对子进程 `kill -STOP` | 看门狗杀掉后重跑，最后成功，或以 retryable 失败 |
| A12 | 并发：A1 和一个 FLUX 出图同时提交 | 串行执行，不 OOM，`queue_position` 正确 |
| A13 | Discovery | 按 §9 声明；`control_types` 与本机实际权重一致 |
| A14 | 人物一致性（§6）| 每个方案一段对比视频，外加一句结论 |

## 11. 回报清单（交回给 core）

- 模型 id 和最终字段名。和本文不一样的地方逐条列出。
- 各模式的实测耗时表（分辨率 × 帧数 × 模式），以及峰值内存、`load_ms`。
- 帧数和时长上限；推荐分辨率（草稿 / 成片，横屏 / 竖屏）。
- 提示词写法说明（§3.1）。
- union 各路的推荐强度，以及 `fidelity` 的默认值。
- 下面几种输入能不能组合，给一个矩阵：
  - a2v
  - control
  - keyframes
  - segments
  - audio.generate
- 控制素材规格有没有要改的地方（§4.3 第 7 条）。
- 人物一致性的结论（§6）。
- 做了哪些下载：仓库、文件、大小，以及用户是否同意。
- 没做或做不了的项，以及原因。

## 12. core 这边等模型端做完后要做的

这一节只是让模型端知道全貌，不需要模型端做。

- **清掉现有首尾帧**：先备份数据库记录和图片文件（移到备份目录，不硬删），再从分镜上解绑。
- **分镜管线**：
  - 首尾帧阶段下线；
  - 视频改走 LTX 2.5：有对白的镜头用 a2v 驱动，没有对白的镜头用文生视频加环境声；
  - 提示词编译器按 §3.1 重写；
  - 时长按对白长度或动作时长来定。
- **Director**：
  - `LTX25Adapter` 真正接入，读 Discovery 声明的能力；
  - 打开 `ltx25_enabled=true`；
  - 3D-BOX 渲染面板加「LTX 2.5 / 控制方式 / 音频」选项；
  - 分段提示词从 Scene Protocol 的 timeline 自动生成；
  - 按 §4.3 第 7 条的回报修改 Blender 控制素材的规格。
- **人物**：按 §6 的结论改流程（首帧锚或角色 LoRA），必要时重出角色参考图。
- **端到端测试**：
  - Director 链：夜巷打斗；
  - 分镜链：坏蛋第 1 章前 4 镜，包括对白口型。

## 13. 实测记录（2026-09-28，M2 Max 96GB）

### 13.1 音频

- 蒸馏版不加 CFG，音频就是正常的。验证方式：
  - 「狗叫三声」→ 频谱上正好三次爆发，后面是喘气声；
  - 「人说两句话」→ 两段人声，中间有停顿，嘴型在动。
- 「蒸馏路径没有引导所以静音」的判断不成立。蒸馏 LoRA 的 3320 个张量里有 2134 个属于音频分支，官方 DistilledPipeline 本身也不加引导。
- 结论：不用给音频加 CFG（加了每步要多跑一遍前向，速度减半），也不用下 38GB 的 dev 模型。

### 13.2 预览 → 续跑

- 续跑出来的成片和一次跑完的**逐帧一致**：PSNR=∞，音频 md5 相同。
- 576×320、73 帧：预览 41 秒 ＋ 续跑 39 秒。
- 「固定 seed、换分辨率或帧数重跑」拿不到同一条样本：噪声张量形状一变，同一个 seed 出来就是另一张画。

### 13.3 速度

条件：832×448、97 帧、同一条提示词、同一个 seed；Docker 开着，占 16.7GB。

| 组合 | 总计 | 第一阶段 | 第二阶段 | 解码 | 内存峰值 |
|---|---|---|---|---|---|
| Q8 流式 | 221s | 71s | 125s | 12s | 32GB |
| bf16 流式 | 238s | 88s | 124s | 12s | 32GB |
| bf16 常驻 | 208s | 67s | **97s** | 23s | 79GB |
| Q8 常驻 | 237s | 71s | 127s | 26s | 79GB |
| bf16 常驻，缓存上限 0 | 239s | 85s | 124s | 11s | 41GB |
| bf16 常驻，缓存上限 12GB | 248s | 77s | 139s | 12s | 43GB |

**怎么读这张表：**

- **第二阶段：**
  - 这一段比的是算力：bf16 做大矩阵乘，比 Q8 边算边反量化快约 22%。
  - 对 Q8 来说，常驻还是流式没有差别。
- **流式加载：**
  - 每一步都要把整套权重重读一遍（bf16 是 38GB，Q8 是 20GB），所以 bf16 流式最吃亏。
- **常驻模式：**
  - 峰值总在 79GB，原因是引擎只在流式模式里把 MLX 显存缓存上限设成 0；常驻时缓存越攒越多，解码也被内存压力拖慢一倍。
  - 推理脚本已加 `--cache-limit-gb`，常驻时默认按 0 设。
- **默认配置（网关 `_ltx25_run_opts`）：**
  - 普通出片（文生视频、配音驱动）用 **Q8 流式**：最稳，内存 32GB。
  - 挂 IC-LoRA（白模控制、参考设定图）用 **Q8 常驻、缓存上限 0**：LoRA 只在加载时融合一次，约 45GB。
  - `LTX25_TURBO=1` 开 **bf16 常驻、缓存不限**：快约 6%，第二阶段快 22%，但峰值 79GB，只适合关掉 Docker 等内存大户时用。
  - 结论：bf16 在这台机器上不是提速的主要手段。真正省时间的是「先出预览、满意再续跑」、按镜头实际时长出片，以及给 LTX 留足内存。
- **内存吃紧的代价：**
  - 同一条片子，内存宽裕时 76 秒，交换区用满时 122 秒，两次输出逐帧一样。
  - 网关跑 LTX 前会先让 ComfyUI 释放内存。

### 13.4 白模 / Blender 控制

- 2.5 目前没有官方的 Union Control，用的是 2.3 版（参考视频半尺寸）挂在 2.5 上。
- 实测素材是夜巷打斗，1024×576、73 帧。成片的动作、站位、机位都跟着 Blender 预演走，白模场景也变成了真实街景，还带同步音效。
- 耗时约 6 分钟（Q8 常驻）。

### 13.5 人物一致（Ingredients 参考设定图）

- **对照方法：** 同一对角色放进两个不同镜头（走廊中近景、教室特写），挂设定图（强度 0.8）和只用文字描述各跑一遍。
- **结果：**
  - 挂设定图：两镜是同一张脸，而且对得上设定图；
  - 只用文字：两镜里的瘦男孩不是同一个人。
  - 强度 1.0 时镜头贴得很近，动作看不清，所以默认改成 0.8。
- **设定图漏进片头：**
  - 3 条里有 1 条，前 48 帧（2 秒）整屏都是设定图的格子。
  - 网关按构图检测：64×36 灰度图去掉均值后，和设定图算相关系数。漏出来的帧在 0.70 左右，正常画面低于 0.2，阈值定 0.45。
  - 漏了就换 seed 重来；还漏就裁掉开头，并写进 warnings。
- **设定图 × 配音驱动：** a2v 管线不吃 IC-LoRA。所以网关先挂设定图出 25 帧，取第一张不是设定图本身的帧，拿它当 a2v 的首帧锚。
- **自动拼图：** core 按这一镜出场的人（最多三行）自动拼设定图。每行是脸部特写加上正面、¾、侧面、背面全身，黑底，不写字。
- **形象期要按改编的目标圈层取**，和出首帧的 `resolve_epoch` 是同一套规则。谢文东在原著圈层那一期，是早年画坏的动漫半身像（四个视角其实是同一张图）；不分圈层就会把它拼进设定图。

### 13.6 分镜实跑（坏蛋第 1–4 镜）

- **旧提示词**（沿用首帧提示词）：四镜分别是走廊、室外、青色隧道、操场。根因是逐镜各写各的光和地点，比如第 2 镜写的是「正午城市室外」。旧流程靠场景图把地点拉回来，只剩文字就全露出来了。
- **结构化提示词**（场景头 → 人物 → 构图 → 动作 → 声音）：地点回到了走廊，但画风跑成了皮克斯式卡通，配音驱动的两镜最明显。
  - 原因：截断首帧提示词时，丢掉了末尾那串写实摄影词。
  - 修法：提示词最前面加画风锚（真人实拍，不要动画、卡通、3D、动漫）。
- **帧数：** 向上凑到 8n+1 之后，1.6 秒出 41 帧（1.71 秒），3.12 秒配音出 81 帧，不再截掉字。
