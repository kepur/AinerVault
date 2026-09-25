# Ainer Scene Protocol v1

定义：`code/apps/ainer-core/app/director/protocol.py`（Pydantic；JSON Schema 见 `GET /api/v2/director/protocol/schema`）。

## 约定

- **坐标**：Y 向上，单位米，右手系，地面 y=0；位置 `[x, y, z]`。
- **朝向**：`rotation = [0, yaw, 0]`（度，欧拉 XYZ）。yaw 0 面向 +Z，yaw 90 面向 +X，yaw 180 面向 -Z。
- **人物局部系**：人面朝 +Z 时，他的左手在 +X（动作库的位移按这个写：dodge_left = +X 方向 0.6 米）。
- **机位**：看向 -Z、上方 +Y；`lens_mm` 按 36mm 宽全画幅、水平视场（tan(半水平视场) = 18 / lens）。
- **时间**：秒，从 0 起；`time` 不能超过 `meta.duration_sec`。

## 顶层

```json
{
  "protocol": "ainer.scene/v1",
  "scene_id": "scene_001",
  "meta": {"title": "…", "fps": 24, "duration_sec": 6, "unit": "meter", "aspect": 1.7778, "source": {"kind": "3dbox|llm|api"}},
  "environment": {"preset": "alley_night", "weather": "rain", "time_of_day": "night", "sky": "night", "ground": "asphalt",
                  "ground_size": 120, "fog": 0.2, "lights": [{"kind": "point", "position": [0, 4, 0], "color": "#ffd9a0", "intensity": 2}]},
  "assets": [{"id": "prefab:building", "type": "procedural_prefab", "ref": "building"}],
  "actors": [], "props": [], "cameras": [], "timeline": [], "render_plan": {}
}
```

## actors / props / cameras

```json
{"id": "A", "type": "human", "model_ref": "mannequin/male", "character_ref": "e:ent_…",
 "spawn": {"position": [0, 0, -6], "rotation": [0, 0, 0], "scale": [1, 1, 1]},
 "rig": "ainer_mannequin_v1", "appearance": {"look": "lean young man, black leather jacket"}, "pose": "stand"}
```

- `type`：human / vehicle / animal；车、马、船等会动的写进 actors，`model_ref = "prefab/<名字>"`。
- `character_ref`：角色库里的角色（成片阶段拿它的立绘当身份参考）。
- props：`prefab`（程序化白模预制件，目录见 `/catalog`）或 `primitive`＋`size`，或 `strip`（道路、河）。
- cameras：`{id, name, lens_mm, keys?, shake?}`。`keys` 每个关键帧位置三选一：`position` / `follow+offset` / `orbit+angle+radius+height`。
  **机位带 `keys` 时以 `keys` 为准**，时间线里这台机位的运镜指令只是「怎么来的」记录。

## timeline

| op | 字段 | 说明 |
|---|---|---|
| `actor.move_to` / `prop.move_to` | `target_position, duration?, speed?, gait?` | 走/跑/开到某处；不写 duration 按步速（走 1.4、跑 4.5 m/s） |
| `actor.move_along` / `prop.move_along` | `path[], duration?, speed?, gait?` | 沿路径匀速 |
| `actor.move` / `prop.move` | `keys[{t, at, rot}]` | 关键帧移动 |
| `actor.play_action` | `action, duration?, target_actor?, target_bone?` | 动作库；带 target 的出拳踢腿先转身面向对手 |
| `actor.set_pose` | `pose` | 换姿势 |
| `actor.look_at` | `target_actor, duration?` | 原地转身面向 |
| `camera.move` | `preset, target, duration, side?, angle?` | 运镜库预设 |
| `camera.follow` | `target_actor, style(back/front/side/top/first/side_follow), duration?` | 跟拍 |
| `camera.keys` | `keys[]` | 关键帧 |
| `camera.frame` | `target, size(els…ecu), angle?` | 景别关键帧 |
| `camera.cut` | `camera` | 从 time 起切到这台（至少一条 time=0） |

### 动作库（V1）

`idle` 待机、`walk_forward` 向前走、`run_forward` 向前跑、`turn_left` / `turn_right` 转身 90°、`look_back` 回头、
`right_punch` / `left_punch` 直拳、`front_kick` 前踢、`dodge_left` / `dodge_right` 闪避 0.6 米、`block_high` 高位格挡、
`hit_react_back` 受击后仰（退 0.4 米）、`hit_react_left` 受击侧偏、`fall_backward` 倒地（一直躺到 `stand_up`）、`stand_up` 起身。
（`turn_to` 是 `actor.look_at` 的内部实现。）

### 运镜库（V1 要求的都在）

static、follow、**side_follow**、dolly_in、**dolly_out**、orbit_left、orbit_right、crane_up、**crane_down**，以及其余 41 个（推拉摇移、跟拍、环绕、航拍、特殊），共 50 个。

## render_plan

```json
{"preview": true, "passes": ["preview", "clay", "depth", "pose", "canny"], "output_resolution": [1024, 576],
 "fps": 24, "camera": "cut", "export_camera_json": true, "export_motion_json": true,
 "final_renderer": "ltx_097", "control_type": "v2v"}
```

分辨率自动落到 32 的倍数；`camera` 是 `"cut"`（按剪辑表切主机位）或某台机位 id。

## 修改：JSON Patch（RFC 6902）

`PATCH /api/v2/director/scenes/{id}`，body `{"patch": [...]}`：

```json
[{"op": "replace", "path": "/cameras/0/lens_mm", "value": 50},
 {"op": "add", "path": "/timeline/-", "value": {"op": "camera.move", "time": 2, "camera": "cam_01", "preset": "orbit_left", "target": "A", "duration": 3}}]
```

打完重新校验；失败整份作废。对 3D-BOX 来源的场景打补丁：改动落在协议上、并重新生成项目的 scene.js（原脚本进版本史），场景转成 JSON 优先。

## 两种写法

- **脚本优先**（3D-BOX）：脚本＋台上改动是真身，协议是导出快照（`POST /scenes {box_project_id}`）。
- **JSON 优先**（API / LLM）：协议是真身，自动生成等价的 3D-BOX 项目，可以在台上看、拖、让智能体继续改。
