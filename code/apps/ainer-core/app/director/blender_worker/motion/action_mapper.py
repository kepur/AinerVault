"""动作映射：场景里的语义动作（right_punch、dodge_left、fall_backward……）→ 人偶骨架。

V1：动作库在 ainer-studio/src/scene/rig.ts（3D-BOX 预览用的同一份），烘焙时已经逐帧解算成关节角
（rigs[id]，通道顺序见 rigChannels）。这里只把通道写到对应的关节空物体上 —— Blender 不需要再懂动作。

以后换真模型（绑好骨骼的 glTF/FBX）时，这一层改成「语义动作名 → 动作资产片段（NLA strip）」：
timeline 里的 actor.play_action 保留了动作名、起止时间、目标，足够做这件事（见 map_semantic）。
"""
from __future__ import annotations

import math

JOINTS = ["spine", "head", "lSh", "lEl", "rSh", "rEl", "lHip", "lKn", "rHip", "rKn"]


def apply_rig(actor: dict, channels: list[str], data: list[float], frames: int) -> None:
    n = len(channels)
    idx = {c: i for i, c in enumerate(channels)}
    b = actor["bones"]
    for i in range(frames):
        v = data[i * n:(i + 1) * n]
        f = i + 1

        def g(c: str) -> float:
            return v[idx[c]]
        mv = b["move"]
        mv.location = (g("offset.x"), g("offset.y"), g("offset.z"))
        mv.rotation_euler = (0.0, math.radians(g("yaw")), 0.0)
        mv.keyframe_insert("location", frame=f)
        mv.keyframe_insert("rotation_euler", frame=f)
        rt = b["root"]
        rt.location = (0.0, g("rootY"), 0.0)
        rt.rotation_euler = (math.radians(g("root.x")), math.radians(g("root.y")), math.radians(g("root.z")))
        rt.keyframe_insert("location", frame=f)
        rt.keyframe_insert("rotation_euler", frame=f)
        pv = b["pelvis"]
        pv.location = (0.0, g("pelvisY"), 0.0)
        pv.keyframe_insert("location", frame=f)
        for j in JOINTS:
            ob = b[j]
            ob.rotation_euler = (math.radians(g(f"{j}.x")), math.radians(g(f"{j}.y")), math.radians(g(f"{j}.z")))
            ob.keyframe_insert("rotation_euler", frame=f)


# 以后接真动作资产用：语义动作 → 资产片段名（V1 没有资产，不启用）
SEMANTIC_CLIPS = {
    "idle": "Idle", "walk_forward": "Walk_Fwd", "run_forward": "Run_Fwd", "turn_left": "Turn_L90", "turn_right": "Turn_R90",
    "look_back": "LookBack", "right_punch": "Punch_R", "left_punch": "Punch_L", "front_kick": "Kick_Front",
    "dodge_left": "Dodge_L", "dodge_right": "Dodge_R", "block_high": "Block_High", "hit_react_back": "HitReact_Back",
    "hit_react_left": "HitReact_L", "fall_backward": "Fall_Back", "stand_up": "GetUp",
}


def map_semantic(timeline: list[dict], actor_id: str) -> list[dict]:
    """某个角色的语义动作清单（给以后的资产片段映射用）：[{clip, start, duration, target}]。"""
    out = []
    for op in timeline:
        if op.get("op") == "actor.play_action" and op.get("actor") == actor_id:
            out.append({"clip": SEMANTIC_CLIPS.get(op["action"], op["action"]), "start": op["t"],
                        "duration": op.get("duration"), "target": op.get("target_actor")})
    return out
