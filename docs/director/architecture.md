# Ainer Director Core · V1 架构

> 目标：**协议先统一、Blender 先打通、LTX 先跑通**。
> V1 真正跑通的链路：**3D-BOX / LLM → Ainer Scene Protocol → Blender 控制素材 → LTX 成片**。
> UE、LTX 2.5 的代码都在（协议映射、参数校验、payload、mock），功能开关关着。

## 1. 总体

```
3D-BOX（ainer-studio）          LLM（免费 text.chat）
   │ 场景脚本 S.* ＋ 台上改动        │ JSON（协议 / JSON Patch / 提示词）
   ▼                                ▼
Ainer API（ainer-core FastAPI，/api/v2/director/*）
   ▼
Ainer Director Core（app/director）
   ├── protocol.py        Ainer Scene Protocol v1（Pydantic，JSON Schema）
   ├── convert.py         3D-BOX 场景文档 ⇄ 协议（协议 → 等价的 scene.js）
   ├── planner.py         LLM Planner：一句话 → 协议；修改 → JSON Patch；场景 → 成片提示词
   ├── store.py           Scene Store：director_scenes（协议快照、版本）
   ├── jobs.py            Job Orchestrator：director_jobs，单线程队列、进度、取消、重启恢复
   ├── outputs.py         Asset / Output Manager：director_outputs ＋ 媒体库资产
   ├── blender_adapter.py Blender Adapter（启用）：起无头进程、盯进度、卡死换进程
   ├── blender_worker/    在 Blender 里跑的 worker（loaders / scene_builders / motion / renderers / exporters）
   ├── renderers/         Renderer Adapter：ltx097（启用）、ltx25（预埋）、registry
   └── ue_worker/         UE Adapter（预埋）：translator / remote / scripts / adapter
          ▼
能力网关（ai-studio，本机）──► ComfyUI：ltxv_v2v（2B 白模重绘）、ltxv_iclora（13B IC-LoRA 控制）
```

## 2. 与 V1 方案的对照（融合时做的取舍）

| 方案 | 落地 | 为什么 |
|---|---|---|
| `apps/api` 新网关 | 挂在现有 ainer-core：`/api/v2/director/*` | 与系统其它接口同一套鉴权、数据库、版本号；不另起服务 |
| `apps/director`、`packages/*` 新仓库结构 | `app/director/` 一个包 | 一个仓库一个部署单元，少一层跨服务调用 |
| Redis + RQ/Celery | 进程内单线程队列 ＋ 数据库任务表 | 本机一块 GPU，本来就要一个一个跑；多一套 Redis 只多运维 |
| LLM 只输出 JSON | 保留两条路：① 协议 JSON（`/scenes:generate`、`:edit` 出 JSON Patch）② 3D-BOX 场景脚本 | 脚本跑在沙箱里（无文件、无网络、无 eval），产物就是 JSON；摆一整条街、一排路灯时 LLM 写循环比吐几百行坐标可靠。两条路落到同一份协议 |
| Blender 负责动作映射 | 动作库在 `ainer-studio/src/scene/rig.ts`，烘焙成逐帧关节角，Blender 只播放 | 预览和 Blender 必须同一份动作，否则 3D-BOX 里看到的和渲出来的对不上。语义动作名保留在协议 timeline 里，给 UE（将来映射到真动画资产） |
| `packages/motion_library` | `rig.ts` 的 MOTIONS（16 个 V1 动作＋turn_to） | 与预览、烘焙共用 |
| `packages/camera_library` | `cameraPresets.ts`（50 个，含新加的 side_follow / crane_down / dolly_out） | 同上 |
| LTX 0.9.7 吃 depth/pose/canny | 本机实际是 **ltxv-2b-0.9.8-distilled**；官方 IC-LoRA 只有 **13B 0.9.7** 版 | V1 默认走 2B 白模重绘（v2v）；三个 IC-LoRA 已下载，13B 底模到位即可切 depth/pose/canny（见 ltx_migration.md） |

## 3. 数据流（一次完整出片）

1. **场景**：3D-BOX 项目（脚本＋手动改动）编译成场景文档；`store.export_box` 导出协议快照（或 LLM 直接给协议，`store.create_from_protocol` 生成等价脚本和 3D-BOX 项目）。
2. **烘焙**（`app/scene3d/runner.py bake_scene`，node 沙箱里跑 `bake.ts`）：逐帧解算 → `scene_resolved.json`
   （几何部件表、物体逐帧位姿、人偶逐帧 39 个关节通道、主机位逐帧位置/看向/焦段/滚转、剪辑表、语义时间线）。
3. **Blender 任务**（`jobs.submit_blender`）：提交时把烘焙快照写进任务目录 → 排队 → `blender_adapter.render`
   起 `Blender -b --factory-startup --python worker.py -- job.json` → 产物登记成 `director_outputs`（视频/首帧另存进媒体库）。
4. **成片任务**（`jobs.submit_final`）：LLM 按协议写英文提示词 → `LTX097Adapter.generate` → 网关
   `video.image_to_video + control{type, video, denoise, pin_first}` → `final.mp4`。

## 4. 功能开关

`code/apps/ainer-core/configs/director/feature_flags.yaml`（环境变量 `DIRECTOR_<FLAG>` 可覆盖）：

```yaml
blender_enabled: true
ue_enabled: false
ltx097_enabled: true
ltx25_enabled: false
```

关着的后端：接口返回 409「未启用」；代码路径（翻译、payload、脚本生成、mock）照常可测。

## 5. 数据表（迁移 `c4d8e2f1a7b3`）

| 表 | 用途 |
|---|---|
| `director_scenes` | 协议快照：`source`（3dbox / api / llm）、`box_project_id`、`protocol_json`、`version`、`prompt` |
| `director_jobs` | 任务：`job_type`（blender_render / final_render / ue_render）、`status`、`backend`、`input_json`、`progress_json`、`output_manifest_json`、`parent_id` |
| `director_outputs` | 产物：`kind`、任务目录相对路径、媒体库资产 `asset_id` / `url` |

任务目录：`code/apps/ainer-core/var/director/jobs/<job_id>/`。

## 6. 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v2/director/system/features` | 开关、Blender 版本、LTX 可用控制方式 |
| GET | `/api/v2/director/protocol/schema` | 协议 JSON Schema |
| GET | `/api/v2/director/catalog` | 动作库、运镜库、体型、姿势 |
| POST | `/api/v2/director/scenes` | `{protocol}` 或 `{box_project_id}` |
| GET/PATCH | `/api/v2/director/scenes/{id}` | 读 / JSON Patch |
| POST | `/api/v2/director/scenes:generate` | 一句话 → 协议 → 3D-BOX 项目 |
| POST | `/api/v2/director/scenes/{id}:edit` | 一句话修改 → LLM 出 patch |
| POST | `/api/v2/director/jobs/blender-render` | `{scene_id / box_project_id, render_plan}` |
| GET | `/api/v2/director/jobs`、`/jobs/{id}` | 状态、进度、产物 |
| POST | `/api/v2/director/jobs/{id}/render-final` | 控制素材 → 成片 |
| GET | `/api/v2/director/jobs/{id}/artifacts`、`/files/{path}` | 产物清单、文件 |
| POST | `/api/v2/director/jobs/{id}:cancel` | 取消 |
| POST | `/api/v2/director/ue/plan`、`/ue/execute` | UE dry-run / 执行（V1 关闭） |

## 7. 约束（沿用系统约定）

- 本机单线程：Director 任务一个接一个；Blender 与视频模型不并发抢 GPU。
- 卡死就杀：Blender `stall_sec`（180s）没有进度就杀进程、换新进程重来（`retries`）。
- 子进程只拿 PATH/HOME/TMPDIR/LANG，不传数据库地址和任何密钥。
- 免费优先：LLM 走免费 text.chat 路由；出图、出视频都在本机；`CORE_ALLOW_PAID_MODELS=False`。
- LLM 不写 bpy / Unreal Python：Blender 只读 JSON；UE 脚本由模板生成，数据以 JSON 字面量嵌入。

## 8. 实测（2026-09-25，M2 Max 96GB，夜巷打斗 6 秒）

| 步骤 | 耗时 |
|---|---|
| 编译＋烘焙（145 帧） | 0.1 s |
| Blender 五路控制素材 1024×576×145 | 45 s（预演 EEVEE 16 采样占一半） |
| LTX 2B 白模重绘 768×448×145 | 约 100 s |

结论：动作、运镜、构图跟预演逐帧对得上；2B 的外观服从度有限（提示词写黑夹克，出来可能光膀子）。
要精确控制外观与身份：上 13B IC-LoRA（pose/depth）＋钉住用角色参考画好的首帧。
