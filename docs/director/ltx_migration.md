# LTX：0.9.7 现状与 2.5 迁移

## 现状（2026-09-25 实查）

- 网关现用视频底模：**`ltxv-2b-0.9.8-distilled.safetensors`**（2B）。
- 官方 depth / pose / canny 控制（IC-LoRA）**只有 13B 0.9.7 版**（`Lightricks/LTX-Video-ICLoRA-{depth,pose,canny}-13b-0.9.7`），没有 2B 版。
- 已下载三个 IC-LoRA（sha256 与官方一致）到 `models-hub/loras/`：
  depth 78MB、pose 144MB、canny 78MB（`ltxv-097-ic-lora-*-control-comfyui.safetensors`）。
- **未下载** 13B 底模 `ltxv-13b-0.9.7-distilled.safetensors`（27.3GB，官方 Lightricks/LTX-Video）。
- ComfyUI 核心节点已够用：`LoraLoaderModelOnly`、`LTXVAddGuide`、`LTXVCropGuides`、`LTXVImgToVideoInplace`、`ManualSigmas`、`LoadVideo`。

## 网关（ai-studio）

`video.image_to_video` 增加 `control` 输入：

```json
{"control": {"type": "v2v|depth|pose|canny", "video": {"url": "…"}, "denoise": 0.92, "strength": 1.0, "pin_first": false}}
```

- 能力清单里 `control_types` 按本机实际权重动态报（现在是 `["v2v"]`）；要的方式没就绪就报「未就绪」，**不偷偷降级**。
- 工作流：`13-LTXV白模重绘`（id `ltxv_v2v`）、`14-LTXV-ICLoRA控制`（id `ltxv_iclora`）。
- 顺带修了两处：LoadVideo 会把输入视频挂成界面预览（type=input），以前会被当成成片返回；控制模式帧数按「含首尾」算（6 秒 = 145 帧，不再截成 137）。

## V1 白模重绘（v2v）调参实测（夜巷打斗，2B）

| 设置 | 结果 |
|---|---|
| denoise 0.72 ＋ 钉成片首帧 | 除首帧外基本照搬白模（灰人偶） |
| 0.88 ＋ 钉首帧 | 真人但整体偏灰；首帧与后面跳 |
| 0.95 ＋ 钉首帧 | 真人＋真实环境，但首帧（砖墙）与后面（自动生成的楼）对不上，1→2 帧跳；倒地的人在尾部丢了 |
| 0.90 ＋ 钉灰白模首帧 | 动作跟得最好（倒地躺着也在），但整段环境是灰的 |
| **0.92 ＋ 不钉首帧（默认）** | 整段连贯、真人、动作逐帧跟预演；外观对提示词的服从度一般 |

结论：**钉住的首帧决定整段的样子**。默认不钉；要锁角色身份（有角色库参考图）时，先用图像编辑把预演首帧画成成片（带参考图），再钉。

## 切到 13B IC-LoRA（depth / pose / canny）

1. 下载 `ltxv-13b-0.9.7-distilled.safetensors`（27.3GB）到 `models-hub/checkpoints/`。
2. 网关不用改：`control_types` 自动变成 `["v2v","depth","pose","canny"]`，3D-BOX 渲染面板里三种控制自动可选。
3. 预计耗时：按 2B 实测推算，4 秒片约 7–11 分钟。
4. 建议：打斗/舞蹈用 pose，场景/机位用 depth；配合钉住画好的首帧（IC-LoRA 官方用法是「参考首帧＋控制视频」）。

## 迁移到 LTX 2.5

上层（协议、编排、Blender 控制素材、RenderRequest）不动，只换适配器：

1. 网关：新增 LTX-2.5 工作流（22B 底模 `Lightricks/LTX-2.5`、IC-LoRA Union-Control / Motion-Track；官方示例
   `ComfyUI-LTXVideo/example_workflows/2.5/LTX-2.5_ICLoRA_Union_Control_Distilled.json`），接 `control.type="union"`。
2. `configs/director/ltx25.yaml` 调 union 各路强度；`DIRECTOR_LTX25_ENABLED=true`。
3. 成片请求 `renderer: "ltx_25"`；`LTX25Adapter.build_payload` 已按 union（depth＋pose＋canny 同时）、motion track、首帧、参考图、音轨开关组装，并有校验与 mock。
