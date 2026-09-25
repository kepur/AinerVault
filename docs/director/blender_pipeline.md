# Blender 管线（V1 启用）

## 启动

```
Blender -b --factory-startup --python app/director/blender_worker/worker.py -- job.json
```

由 `app/director/blender_adapter.py` 起。一次一个进程；逐行读 stdout：`AINER_STAGE / AINER_PROGRESS / AINER_DONE / AINER_ERROR`（JSON）。
`stall_sec`（默认 180）秒没有新进度 → 杀进程、换新进程重来（`retries` 次）。子进程只拿 PATH/HOME/TMPDIR/LANG。
配置：`configs/director/blender.yaml`（binary、超时、分辨率、通道、EEVEE 采样、是否存 .blend）。

## job.json

```json
{"job_id": "…", "scene_id": "…", "out_dir": "…/var/director/jobs/<id>", "baked_path": "…/scene_resolved.json",
 "resolution": [1024, 576], "passes": ["preview", "clay", "depth", "pose", "canny"], "ffmpeg": "/opt/homebrew/bin/ffmpeg",
 "media_root": "…/var/media", "preview_samples": 16, "save_blend": true}
```

## worker 分层

```
blender_worker/
├── worker.py                 读 job → 建场景 → 渲各通道 → 合成 mp4 → 导出 json → manifest
├── common.py                 坐标根节点、欧拉角、颜色、材质、基本体网格（与 geom.ts 一一对应）
├── png.py                    PNG 写入、OpenPose 骨架图（纯 numpy；Blender 里没有 PIL）
├── loaders/                  environment_loader（天光、地面、灯）· asset_loader（图片板贴图、glTF/FBX 导入口子）· character_loader（人偶）
├── scene_builders/           prop_builder（部件表 → 网格、父子关系）· actor_builder · camera_builder（主机位＋各机位）
├── motion/                   trajectory_tools（逐帧关键帧）· action_mapper（关节通道 → 骨架；语义动作 → 资产片段的映射表）
├── renderers/                sequence（序列渲染、进度、mp4 合成）· preview · clay · depth · pose · canny
└── exporters/                camera_exporter · motion_exporter · manifest_exporter
```

## 坐标

烘焙数据是 Y 向上（three）。所有物体挂在绕 X 轴 +90° 的根节点 `AINER_ROOT` 下，里面沿用 Y 向上坐标：
(x, y, z)场景 ↦ (x, -z, y)Blender。three 的 XYZ 欧拉（Rx·Ry·Rz）= Blender 的 `ZYX` 旋转模式。相机、灯看向局部 -Z、上方 +Y，两边一致。

## 通道

| 通道 | 引擎 | 做法 |
|---|---|---|
| preview | EEVEE | 白模本色＋天光＋太阳阴影；边缘图的来源 |
| clay | Workbench | 单色棚拍光＋cavity 描边 |
| depth | EEVEE＋材质替换 | 自发光 = (1/z − 1/far)/(1/near − 1/far)，近白远黑（视差形态，同 Depth Anything）；色彩变换 Raw；near = 人物距离 5 分位×0.7，far = 物体距离 90 分位×1.6，**整段固定**（逐帧归一化会闪） |
| pose | —（Blender 投影＋numpy 画） | 每个人偶挂 18 个关键点空物体，`world_to_camera_view` 投到画面，按 OpenPose COCO-18 画法（连线表、配色同 controlnet_aux） |
| canny | ffmpeg edgedetect | 对预演（没有就白模）逐帧 Canny |

## 产物（任务目录）

`preview.mp4 clay.mp4 depth.mp4 pose.mp4 canny.mp4 first_frame.png camera.json motion.json scene.blend manifest.json frames/<pass>/0001.png…`

- **camera.json**：逐帧 `position / look_at / lens_mm / roll_deg / fov_h_deg / fov_v_deg / blender_matrix_world`、剪辑表。
- **motion.json**：每个角色逐帧 `root`、`keypoints_2d`（像素＋可见度）、`keypoints_3d`（场景坐标），以及语义动作清单。
- **scene.blend**：带全部关键帧的工程，美术可以直接打开接着改（机位、灯、材质）。

## 实测（1024×576，145 帧）

build 0.3s · 骨架 0.6s · preview 约 22s · clay 约 4s · depth 约 12s · canny 1s · 合成 2s，合计约 45s。
