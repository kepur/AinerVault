"""时间线 → Level Sequence 轨道。

两层都给：
  transform 轨：烘焙出的逐帧位姿（与 3D-BOX／Blender 完全一致，人偶走位、车辆轨迹都在里面）
  animation 段：语义动作（actor.play_action）按 motion_map 换成 UE 动画资产片段，挂在人物的骨骼动画轨上
V1 的人偶关节角不进 UE（UE 用自己的骨骼动画）；等配好动画资产，动作片段就能对上。
"""
from __future__ import annotations

from typing import Any

from app.director.ue_worker import coords
from app.pipelines.base import as_items

ANIM_STRIDE = 9

DEFAULT_MOTION_MAP = {
    "idle": "/Game/Ainer/Anims/Idle", "walk_forward": "/Game/Ainer/Anims/Walk_Fwd", "run_forward": "/Game/Ainer/Anims/Run_Fwd",
    "turn_left": "/Game/Ainer/Anims/Turn_L90", "turn_right": "/Game/Ainer/Anims/Turn_R90", "look_back": "/Game/Ainer/Anims/LookBack",
    "right_punch": "/Game/Ainer/Anims/Punch_R", "left_punch": "/Game/Ainer/Anims/Punch_L", "front_kick": "/Game/Ainer/Anims/Kick_Front",
    "dodge_left": "/Game/Ainer/Anims/Dodge_L", "dodge_right": "/Game/Ainer/Anims/Dodge_R", "block_high": "/Game/Ainer/Anims/Block_High",
    "hit_react_back": "/Game/Ainer/Anims/HitReact_Back", "hit_react_left": "/Game/Ainer/Anims/HitReact_L",
    "fall_backward": "/Game/Ainer/Anims/Fall_Back", "stand_up": "/Game/Ainer/Anims/GetUp", "turn_to": "/Game/Ainer/Anims/Turn_L90",
}


def transform_tracks(baked: dict[str, Any], step: int = 1) -> dict[str, list[dict[str, Any]]]:
    """id → [{frame, location, rotation, scale}]（step 抽帧，UE 在帧之间插值）。帧号从 0 起。"""
    out: dict[str, list[dict[str, Any]]] = {}
    n = baked["frames"]
    for oid, data in (baked.get("anim") or {}).items():
        keys = []
        for i in list(range(0, n, step)) + ([n - 1] if (n - 1) % step else []):
            v = data[i * ANIM_STRIDE:(i + 1) * ANIM_STRIDE]
            keys.append({"frame": i, "location": coords.location(v[0:3]), "rotation": coords.rotator(v[3:6]), "scale": coords.scale3(v[6:9])})
        out[oid] = keys
    return out


def animation_sections(protocol: dict[str, Any], fps: int, motion_map: dict[str, str] | None = None) -> list[dict[str, Any]]:
    mm = {**DEFAULT_MOTION_MAP, **(motion_map or {})}
    out = []
    for op in as_items(protocol, "timeline"):
        if op.get("op") != "actor.play_action":
            continue
        start = int(round(op["time"] * fps))
        dur = float(op.get("duration") or 1.0)
        out.append({"actor": op["actor"], "action": op["action"], "anim_asset": mm.get(op["action"]),
                    "start_frame": start, "end_frame": start + max(1, int(round(dur * fps))),
                    "target_actor": op.get("target_actor"), "target_bone": op.get("target_bone")})
    return out


def translate(protocol: dict[str, Any], baked: dict[str, Any], cfg: dict[str, Any], *, key_step: int = 2) -> dict[str, Any]:
    fps = int(baked["fps"])
    return {
        "name": f"LS_{protocol.get('scene_id', 'scene')}",
        "root": cfg.get("sequence_root") or "/Game/Ainer/Sequences",
        "fps": fps, "frames": baked["frames"], "duration_sec": baked["duration"],
        "transforms": transform_tracks(baked, key_step),
        "animations": animation_sections(protocol, fps, cfg.get("motion_map")),
    }
