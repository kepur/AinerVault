# UE 适配（V1 预埋、不启用）

开关：`feature_flags.ue_enabled=false`。关着时 `POST /api/v2/director/ue/plan` 照常可用（dry-run：看翻译结果、拿脚本离线调试），
`/ue/execute` 返回 409。配置：`configs/director/ue.yaml`。

## 模块

```
ue_worker/
├── coords.py                      Ainer → UE 坐标
├── translator/scene_to_ue.py      物体、人偶、灯 → 关卡物体清单
├── translator/timeline_to_sequencer.py   逐帧位移轨＋语义动作 → 动画段
├── translator/camera_to_sequencer.py     CineCamera 逐帧变换/焦距＋剪辑轨
├── remote/http_client.py          Remote Control HTTP（/remote/info、object/call、object/property、batch）
├── remote/websocket_client.py     Remote Control WebSocket（{MessageName:"http", Id, Parameters}）
├── scripts/build_level.py         生成 Unreal Python：摆场景
├── scripts/setup_camera.py        生成 Unreal Python：Level Sequence、机位、剪辑轨、动作段
├── scripts/render_queue.py        生成 Unreal Python：Movie Render Queue
└── adapter.py                     plan()（纯函数）/ execute()（要开关）
```

## 坐标换算

我们：Y 上、米、右手系，人面朝 +Z 时右手在 -X。UE：Z 上、厘米、左手系、X 向前、Y 向右。

```
UE.X = z·100   UE.Y = −x·100   UE.Z = y·100      （行列式 −1：右手系 → 左手系）
UE.Yaw = −yaw
```

## 映射策略

- 预制件 → `asset_map["prefab/<名字>"]`；没配的用 `/Engine/BasicShapes/Cube` 按部件包围盒缩放占位（位置、朝向、大小都对，摆机位够用）。
- 人物 → `mannequin_asset`（或 `asset_map["mannequin/<体型>"]`）；位移走逐帧 transform 轨。
- 语义动作 → `motion_map`（默认 `/Game/Ainer/Anims/Punch_R` 等），挂骨骼动画轨；资产不存在时脚本只记日志。
- 机位 → CineCameraActor，胶片背 36×24mm，逐帧变换＋CurrentFocalLength；剪辑轨按剪辑表分段。

## 启用步骤

1. UE 项目里开 **Remote Control API**、**Python Editor Script Plugin**，Remote Control 设置里允许远程执行 Python。
2. 准备资产：人偶骨骼网格、动作动画（按 `motion_map` 命名或改映射）、常用预制件对应的静态网格（`asset_map`）。
3. `ue.yaml` 填 remote_control 地址、关卡、序列目录、MRQ 预设。
4. `DIRECTOR_UE_ENABLED=true`（或改 feature_flags.yaml），先用 `/ue/plan` 看翻译，再 `/ue/execute`。

## 测试

`tests/test_director_backends.py`：坐标、占位缩放、剪辑轨合并、动作段帧号、脚本语法、开关、HTTP 封包（MockTransport）、WebSocket 封包（假连接）。
