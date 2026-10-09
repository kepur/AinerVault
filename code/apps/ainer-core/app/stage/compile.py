"""舞台（SceneStage）与镜头覆盖（CoverageShot）到 3D 场景协议（SceneProtocol）的编译器。

实现 planA.md 第 9 节与第 10 节规范：
1. 剧情舞台 (SceneStage) -> 空间与表演展开 -> SceneProtocol (3D-BOX / Blender 可消费)；
2. 统一三种时间：场景时间 (Scene Time, [0, T])，镜头窗映射 (Coverage Time Window [t0, t1])，毫秒与帧对齐；
3. 白模站位与物理轨迹：平面坐标 [x, y] 映射到 3D 空间 [x, 0, y]，动量与速度上限检查；
4. 运镜与机位编译：按 CameraSpec (setup, move, lens_mm, height, of, on) 生成摄影机起止轨迹与时间线切换；
5. state_at(stage, t)：任意时刻连续空间与表演状态推演采样。
"""
from __future__ import annotations

import math
from typing import Any

from app.director.protocol import PROTOCOL, SceneProtocol
from app.stage.actions import ACTIONS, SPEED_LIMIT
from app.stage.schema import CoverageShot, Landmark, SceneStage, StageCast, StageProp

# 景别距离映射 (米，以 1.75m 人体为基准)
SHOT_DISTANCES = {
    "ecu": 0.7,
    "cu": 1.3,
    "mcu": 1.9,
    "ms": 2.8,
    "fs": 5.2,
    "ws": 11.0,
    "els": 25.0,
}

# 机位高度映射 (米)
CAMERA_HEIGHTS = {
    "low": 0.4,
    "eye": 1.55,
    "high": 3.2,
    "overhead": 6.5,
}


def _coord2d_to_3d(pos2d: list[float] | tuple[float, float]) -> list[float]:
    """舞台平面坐标 [x, y]（米）-> 3D 世界坐标 [x, 0, y]（米，右手系，Y向上，Z为平面第二轴）。"""
    if len(pos2d) >= 3:
        return [round(float(pos2d[0]), 3), round(float(pos2d[1]), 3), round(float(pos2d[2]), 3)]
    return [round(float(pos2d[0]), 3), 0.0, round(float(pos2d[1]), 3)]


def _protocol_positions(actors, props, timeline, duration, when):
    """Planning camera/target positions must also use the render evaluator."""
    from app.director.convert import protocol_to_script
    from app.scene3d.runner import compile_scene, _call
    protocol = {"scene_id": "stage_planning", "meta": {"duration_sec": duration},
        "actors": actors, "props": props, "timeline": [op for op in timeline if not op["op"].startswith("camera.")]}
    compiled = compile_scene(protocol_to_script(protocol))
    if not compiled.get("ok"):
        raise ValueError("动作协议不能被预演运行时消费")
    sampled = _call({"mode": "state", "doc": compiled["doc"], "time": when}, wall_timeout=20)
    if sampled.get("errors"):
        raise ValueError("动作站位采样失败")
    ids = {a["id"] for a in actors}
    return {"actors": {i["id"]: {"pos": [i["world"]["pos"][0], i["world"]["pos"][2]]}
        for i in sampled["instances"] if i["id"] in ids}}


def _plan_state_at(stage: SceneStage, t: float) -> dict[str, Any]:
    """推演采样场景在时刻 t（秒）的连续空间与表演状态。

    返回演员位置、朝向、姿态、道具持有以及活动特效。
    """
    t = max(0.0, float(t))
    actor_positions: dict[str, list[float]] = {}
    actor_facings: dict[str, float] = {}
    actor_postures: dict[str, str] = {}
    actor_poses: dict[str, str] = {}
    actor_effects: dict[str, list[str]] = {}

    for c in stage.cast:
        start_pos = list(c.start) if c.start else [0.0, 0.0]
        actor_positions[c.actor] = start_pos
        actor_facings[c.actor] = float(c.facing_deg or 0.0)
        actor_postures[c.actor] = "standing"
        actor_poses[c.actor] = "stand"
        actor_effects[c.actor] = []

    # 按时间顺序遍历 beats，回放计算截止到 t 的位姿变化与插值
    for b in sorted(stage.beats, key=lambda x: x.t[0]):
        t_start, t_end = b.t
        dur = max(0.01, t_end - t_start)

        for act in b.do:
            actor = act.actor
            if actor not in actor_positions:
                continue

            op_def = ACTIONS.get(act.op)
            if not op_def:
                continue

            # 移动类动作：计算插值位置
            if op_def.moves and act.target is not None:
                curr_pos = actor_positions[actor]
                tgt_pos = None
                if isinstance(act.target, list) and len(act.target) >= 2:
                    tgt_pos = [float(act.target[0]), float(act.target[1])]
                elif isinstance(act.target, str) and act.target in actor_positions:
                    tgt_pos = list(actor_positions[act.target])
                elif isinstance(act.target, str):
                    for lm in stage.set.landmarks:
                        if lm.id == act.target:
                            tgt_pos = [float(lm.pos[0]), float(lm.pos[1])]
                            break

                if tgt_pos:
                    if t >= t_end:
                        actor_positions[actor] = tgt_pos
                        # 更新朝向
                        dx, dy = tgt_pos[0] - curr_pos[0], tgt_pos[1] - curr_pos[1]
                        if math.hypot(dx, dy) > 0.01:
                            actor_facings[actor] = round(math.degrees(math.atan2(dx, dy)), 1)
                    elif t >= t_start:
                        ratio = (t - t_start) / dur
                        interp_x = curr_pos[0] + (tgt_pos[0] - curr_pos[0]) * ratio
                        interp_y = curr_pos[1] + (tgt_pos[1] - curr_pos[1]) * ratio
                        actor_positions[actor] = [round(interp_x, 3), round(interp_y, 3)]
                        dx, dy = tgt_pos[0] - curr_pos[0], tgt_pos[1] - curr_pos[1]
                        if math.hypot(dx, dy) > 0.01:
                            actor_facings[actor] = round(math.degrees(math.atan2(dx, dy)), 1)

            # 姿态演化
            if t >= t_start:
                if op_def.rig_pose:
                    actor_poses[actor] = op_def.rig_pose
                elif op_def.rig_motion:
                    actor_poses[actor] = op_def.rig_motion

                if t >= t_end and op_def.posture_after:
                    actor_postures[actor] = op_def.posture_after

                # 对方受击反应与姿态
                if (
                    isinstance(act.target, str)
                    and act.target in actor_positions
                    and op_def.target_posture_after
                    and t >= t_end
                ):
                    actor_postures[act.target] = op_def.target_posture_after

        # 特效检查
        for eff in b.effects:
            eff_start = eff.from_t if eff.from_t is not None else t_start
            eff_end = eff.to_t if eff.to_t is not None else t_end
            if eff_start <= t <= eff_end and eff.on in actor_effects:
                if eff.kind not in actor_effects[eff.on]:
                    actor_effects[eff.on].append(eff.kind)

    # 道具状态
    props_status: dict[str, dict[str, Any]] = {}
    for p in stage.props:
        props_status[p.id] = {
            "holder": p.holder,
            "slot": p.slot,
            "pos": list(p.pos) if p.pos else (list(actor_positions.get(p.holder, [0.0, 0.0])) if p.holder else [0.0, 0.0]),
        }

    return {
        "t": round(t, 3),
        "actors": {
            a: {
                "pos": actor_positions[a],
                "facing_deg": actor_facings[a],
                "posture": actor_postures[a],
                "pose": actor_poses[a],
                "effects": actor_effects[a],
            }
            for a in actor_positions
        },
        "props": props_status,
    }


def compile_stage_to_protocol(
    stage: SceneStage,
    shots: list[CoverageShot] | None = None,
    *,
    fps: int = 24,
    aspect: float = 16 / 9,
    title: str | None = None,
) -> dict[str, Any]:
    """将 SceneStage 与 CoverageShots 编译为标准 SceneProtocol 结构。

    生成的协议可直接保存、被 3D-BOX 解释或提交给 Blender/LTX 渲染。
    """
    shots = sorted(shots or [], key=lambda s: s.order_no)
    max_shot_t = max((s.window[1] for s in shots), default=0.0)
    total_dur = max(stage.duration, max_shot_t, 2.0)

    # 环境与地面材质映射
    preset = stage.set.preset or "blank_stage"
    ground = "grid"
    if "ski" in preset or "snow" in preset:
        ground = "snow"
    elif "alley" in preset or "street" in preset:
        ground = "asphalt"
    elif "indoor" in preset or "room" in preset:
        ground = "floor"

    environment: dict[str, Any] = {
        "preset": preset,
        "sky": "day" if "night" not in preset else "night",
        "ground": ground,
        "ground_size": float(stage.set.size_m[0]) if stage.set.size_m else 120.0,
        "fog": 0.1 if "snow" in preset else 0.0,
        "lights": [
            {
                "kind": "sun",
                "color": "#ffffff",
                "intensity": 1.2,
                "direction": [-0.5, -1.0, -0.3],
            }
        ],
    }

    # 场景道具与地标
    props: list[dict[str, Any]] = []
    for lm in stage.set.landmarks:
        props.append({
            "id": lm.id,
            "name": lm.label or lm.id,
            "primitive": "box",
            "size": [0.4, 0.4, 0.4],
            "spawn": {
                "position": _coord2d_to_3d(lm.pos),
                "rotation": [0.0, 0.0, 0.0],
                "scale": [1.0, 1.0, 1.0],
            },
        })

    for pr in stage.props:
        p_pos = pr.pos if pr.pos else ([0.0, 0.0] if not pr.holder else [0.0, 0.0])
        props.append({
            "id": pr.id,
            "name": pr.id,
            "primitive": "box",
            "size": [0.2, 0.2, 0.2],
            "spawn": {
                "position": _coord2d_to_3d(p_pos),
                "rotation": [0.0, 0.0, 0.0],
                "scale": [1.0, 1.0, 1.0],
            },
        })

    # 演员初始化
    actors: list[dict[str, Any]] = []
    for c in stage.cast:
        start_3d = _coord2d_to_3d(c.start or [0.0, 0.0])
        actors.append({
            "id": c.actor,
            "name": c.actor,
            "type": "human",
            "model_ref": "mannequin/male",
            "character_ref": c.card if c.card.startswith("e:") else f"e:{c.card}",
            "spawn": {
                "position": start_3d,
                "rotation": [0.0, float(c.facing_deg or 0.0), 0.0],
                "scale": [1.0, 1.0, 1.0],
            },
            "pose": "stand",
        })

    # 时间线指令展开
    timeline: list[dict[str, Any]] = []
    for b in sorted(stage.beats, key=lambda x: x.t[0]):
        t0, t1 = b.t
        dur = max(0.01, round(t1 - t0, 3))

        for act in b.do:
            op_def = ACTIONS.get(act.op)
            if not op_def:
                continue

            # 移动指令
            if op_def.moves and act.target is not None:
                tgt_pos3d = [0.0, 0.0, 0.0]
                if isinstance(act.target, list) and len(act.target) >= 2:
                    tgt_pos3d = _coord2d_to_3d(act.target)
                elif isinstance(act.target, str):
                    s_state = _protocol_positions(actors, props, timeline, total_dur, t0)
                    if act.target in s_state["actors"]:
                        tgt_pos3d = _coord2d_to_3d(s_state["actors"][act.target]["pos"])
                    else:
                        for lm in stage.set.landmarks:
                            if lm.id == act.target:
                                tgt_pos3d = _coord2d_to_3d(lm.pos)
                                break

                gait = act.speed or ("run" if act.op in ("run_to", "ski_downhill") else "walk")
                if gait not in ("walk", "run", "drive", "fly", "swim"):
                    gait = "run" if str(gait).lower() == "ski" else "walk"
                timeline.append({
                    "op": "actor.move_to",
                    "time": round(t0, 3),
                    "actor": act.actor,
                    "target_position": tgt_pos3d,
                    "duration": dur,
                    "gait": gait,
                })

            # 动作与姿势
            if op_def.rig_motion:
                timeline.append({
                    "op": "actor.play_action",
                    "time": round(t0, 3),
                    "actor": act.actor,
                    "action": op_def.rig_motion,
                    "duration": min(op_def.default_s, dur),
                    **({"target_actor": act.target} if isinstance(act.target, str) else {}),
                })
                # 受击反应
                if op_def.target_reacts and isinstance(act.target, str):
                    timeline.append({
                        "op": "actor.play_action",
                        "time": round(t0 + 0.15, 3),
                        "actor": act.target,
                        "action": op_def.target_reacts,
                        "duration": min(op_def.default_s, dur),
                    })

            if op_def.rig_pose:
                timeline.append({
                    "op": "actor.set_pose",
                    "time": round(t0, 3),
                    "actor": act.actor,
                    "pose": op_def.rig_pose,
                })

            if act.op in ("turn_to", "look_at") and isinstance(act.target, str):
                timeline.append({
                    "op": "actor.look_at",
                    "time": round(t0, 3),
                    "actor": act.actor,
                    "target_actor": act.target,
                    "duration": dur,
                })

    # 机位编译
    cameras: list[dict[str, Any]] = []
    if not shots:
        # 默认中景机位
        cameras.append({
            "id": "cam_main",
            "name": "主机位",
            "lens_mm": 35.0,
            "keys": [
                {"t": 0.0, "position": [0.0, 1.55, 4.0], "look_at": [0.0, 1.2, 0.0], "lens_mm": 35.0},
                {"t": round(total_dur, 2), "position": [0.0, 1.55, 4.0], "look_at": [0.0, 1.2, 0.0], "lens_mm": 35.0},
            ],
        })
        timeline.append({"op": "camera.cut", "time": 0.0, "camera": "cam_main"})
    else:
        for idx, shot in enumerate(shots):
            cid = f"cam_{shot.order_no:02d}"
            t_in, t_out = shot.window
            dur_shot = max(0.1, round(t_out - t_in, 3))

            # 目标焦点
            focus_id = shot.focus or shot.camera.on or (stage.cast[0].actor if stage.cast else None)
            f_state = _protocol_positions(actors, props, timeline, total_dur, t_in)
            if focus_id and focus_id in f_state["actors"]:
                tgt_pos2d = f_state["actors"][focus_id]["pos"]
            else:
                tgt_pos2d = [0.0, 0.0]

            tgt_3d = [tgt_pos2d[0], 1.2, tgt_pos2d[1]]

            # 景别与距离
            dist = SHOT_DISTANCES.get(shot.size, SHOT_DISTANCES["ms"])
            h_cam = CAMERA_HEIGHTS.get(shot.camera.height, CAMERA_HEIGHTS["eye"])
            lens = float(shot.camera.lens_mm or (35.0 if shot.size in ("ms", "fs", "ws") else 50.0))

            # Always initialize per shot; low/high shots must not reuse a preceding shot.
            cam_start_pos = [tgt_3d[0], h_cam, tgt_3d[2] + dist]
            # 初始机位放置
            setup = shot.camera.setup
            if setup == "low_angle":
                h_cam = 0.35
            elif setup == "high_angle":
                h_cam = 3.5
            elif setup == "over_shoulder" and shot.camera.of:
                of_pos = f_state["actors"].get(shot.camera.of, {}).get("pos", [0.0, 0.0])
                cam_start_pos = [of_pos[0] + 0.3, 1.45, of_pos[1] - 0.5]
            else:
                cam_start_pos = [tgt_3d[0], h_cam, tgt_3d[2] + dist]

            cam_start_pos[1] = h_cam if setup != "over_shoulder" else cam_start_pos[1]
            cam_end_pos = list(cam_start_pos)
            cam_end_look = list(tgt_3d)

            # 运镜轨迹计算
            move = shot.camera.move
            if move == "push_in":
                # 向目标前推 18%
                cam_end_pos = [
                    cam_start_pos[0] + 0.18 * (tgt_3d[0] - cam_start_pos[0]),
                    cam_start_pos[1] + 0.18 * (tgt_3d[1] - cam_start_pos[1]),
                    cam_start_pos[2] + 0.18 * (tgt_3d[2] - cam_start_pos[2]),
                ]
            elif move in ("pull_out", "pull_back"):
                # 远离目标后拉 22%
                cam_end_pos = [
                    cam_start_pos[0] - 0.22 * (tgt_3d[0] - cam_start_pos[0]),
                    cam_start_pos[1] - 0.22 * (tgt_3d[1] - cam_start_pos[1]) + 0.1,
                    cam_start_pos[2] - 0.22 * (tgt_3d[2] - cam_start_pos[2]),
                ]
            elif move == "pan":
                # 水平摇动视线
                cam_end_look = [tgt_3d[0] + 0.8, tgt_3d[1], tgt_3d[2]]
            elif move == "track":
                # 跟踪目标在镜头结束时刻的位置
                f_state_end = _protocol_positions(actors, props, timeline, total_dur, t_out)
                if focus_id and focus_id in f_state_end["actors"]:
                    end_pos2d = f_state_end["actors"][focus_id]["pos"]
                    dx, dy = end_pos2d[0] - tgt_pos2d[0], end_pos2d[1] - tgt_pos2d[1]
                    cam_end_pos = [cam_start_pos[0] + dx, cam_start_pos[1], cam_start_pos[2] + dy]
                    cam_end_look = [tgt_3d[0] + dx, tgt_3d[1], tgt_3d[2] + dy]

            camera_keys = [
                {
                    "t": round(t_in, 3),
                    "position": [round(x, 3) for x in cam_start_pos],
                    "look_at": [round(x, 3) for x in tgt_3d],
                    "lens_mm": lens,
                },
                {
                    "t": round(t_out, 3),
                    "position": [round(x, 3) for x in cam_end_pos],
                    "look_at": [round(x, 3) for x in cam_end_look],
                    "lens_mm": lens,
                },
            ]

            cameras.append({
                "id": cid,
                "name": f"镜头 {shot.order_no} 机位",
                "lens_mm": lens,
                "shake": 0.4 if move == "handheld" else 0.0,
                "keys": camera_keys,
            })

            timeline.append({"op": "camera.cut", "time": round(t_in, 3), "camera": cid})
            preset_map = {
                "push_in": "push_in",
                "pull_out": "pull_out",
                "pull_back": "pull_out",
                "pan": "pan_left",
                "track": "side_follow",
                "handheld": "handheld",
            }
            if move in preset_map:
                timeline.append({
                    "op": "camera.move",
                    "time": round(t_in, 3),
                    "camera": cid,
                    "preset": preset_map[move],
                    "duration": dur_shot,
                })

    protocol = {
        "protocol": PROTOCOL,
        "scene_id": f"scene_{stage.scene_id}",
        "meta": {
            "title": title or f"舞台场景 {stage.scene_id}",
            "fps": fps,
            "duration_sec": round(total_dur, 2),
            "unit": "meter",
            "aspect": round(aspect, 5),
            "coordinate_system": {"up": "+Y", "forward": "+Z", "handedness": "right"},
        },
        "environment": environment,
        "props": props,
        "actors": actors,
        "cameras": cameras,
        "timeline": sorted(timeline, key=lambda x: x["time"]),
    }

    # Runtime S.moveTo/S.moveAlong replace a prior root track. Refuse ambiguous
    # multiple tracks until the author merges them into one explicit trajectory.
    moved = set()
    for op in timeline:
        if op["op"].startswith("actor.move"):
            if op["actor"] in moved:
                raise ValueError("同一演员的多段位移需合并为一条共享关键帧轨；当前编译器不能静默覆盖前段")
            moved.add(op["actor"])
    protocol["meta"]["source"] = {
        "kind": "narrative_stage",
        "proxy_props": [p.id for p in stage.props],
        "unconsumed": ["prop_attachment", "effects", "contact_ik_collision", "physical_asset_dimensions"],
    }
    # 协议校验
    SceneProtocol.model_validate(protocol)
    return protocol


def state_at(stage: SceneStage, t: float) -> dict[str, Any]:
    """Compatibility response; physical positions and rig come from the render runtime.

    The beat replay supplies semantic posture/effects only. It is not a second
    authoritative interpolation or an attachment/particle simulation.
    """
    from app.director.convert import protocol_to_script
    from app.scene3d.runner import compile_scene, _call

    protocol = compile_stage_to_protocol(stage)
    when = float(t)
    if not math.isfinite(when) or not 0 <= when <= protocol["meta"]["duration_sec"]:
        raise ValueError("场景时间超出舞台范围")
    result = compile_scene(protocol_to_script(protocol))
    if not result.get("ok") or not result.get("doc"):
        raise ValueError("舞台协议不能被真实预演运行时消费：" + "；".join(e.get("message", "") for e in result.get("errors", [])))
    physical = _call({"mode": "state", "doc": result["doc"], "time": when}, wall_timeout=20)
    if physical.get("errors"):
        raise ValueError("舞台状态采样失败")
    semantic = _plan_state_at(stage, when)
    poses = {i["id"]: i for i in physical["instances"]}
    for actor, item in semantic["actors"].items():
        world = poses[actor]["world"]
        item["pos"] = [world["pos"][0], world["pos"][2]]
        item["facing_deg"] = world["rot"][1]
        item["rig"] = poses[actor]["rig"]
        item["posture_effects_source"] = "semantic_only"
    for prop, item in semantic["props"].items():
        if prop in poses:
            item["pos"] = [poses[prop]["world"]["pos"][0], poses[prop]["world"]["pos"][2]]
        item["attachment_consumed"] = False
    semantic["physical"] = physical
    semantic["consumption"] = {"position_camera_rig": "shared_runtime",
        "posture_effects_holding": "semantic_only", "contact_ik_collision": "not_implemented"}
    return semantic
