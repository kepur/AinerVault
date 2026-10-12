"""骨架动作库：语义动作片段 → 标准人形骨架（Mixamo 命名）的关节角。

角度约定（角色在骨架静止空间里面朝 -Y、左侧 +X、Z 向上；每根骨骼的旋转是相对父骨骼、按静止姿态的
骨架坐标轴给出的欧拉角 [rx, ry, rz]，单位度，应用顺序 Z·Y·X）：
  rx>0  脊柱/头前屈、膝弯曲、上臂/大腿向后摆；rx<0  上臂/大腿向前抬、肘屈（前臂向前上）
  ry    左臂 <0 / 右臂 >0 为外展（侧平举）
  rz>0  向左转（头、躯干）
Blender worker 把 D 转成骨骼局部四元数 q = R_rest⁻¹·D·R_rest，因此这里的角度与具体骨骼的 roll 无关。
动作可被将来的 FBX/BVH（Mixamo 骨骼名相同）替换。
"""
from __future__ import annotations

import math

BONES = ["Hips", "Spine", "Spine1", "Spine2", "Neck", "Head",
         "LeftShoulder", "LeftArm", "LeftForeArm", "LeftHand", "RightShoulder", "RightArm", "RightForeArm", "RightHand",
         "LeftUpLeg", "LeftLeg", "LeftFoot", "RightUpLeg", "RightLeg", "RightFoot"]

#: 默认放松站姿：手臂略外展垂下
REST = {"LeftArm": [0, -8, 0], "RightArm": [0, 8, 0], "LeftForeArm": [-8, 0, 0], "RightForeArm": [-8, 0, 0]}


def _ease(u: float) -> float:
    u = min(1.0, max(0.0, u))
    return u * u * (3 - 2 * u)


def _env(u: float, a: float = 0.2, b: float = 0.2) -> float:
    """片段包络：前 a 渐入、后 b 渐出。"""
    if u < a:
        return _ease(u / a)
    if u > 1 - b:
        return _ease((1 - u) / b)
    return 1.0


def _add(pose: dict, bone: str, v, w: float = 1.0):
    cur = pose.setdefault(bone, [0.0, 0.0, 0.0])
    for i in range(3):
        cur[i] += v[i] * w


def walk(t_s: float, w: float, pose: dict, speed: float = 1.0):
    ph = 2 * math.pi * 1.8 * speed * t_s
    s = math.sin(ph)
    _add(pose, "LeftUpLeg", [-28 * s, 0, 0], w)
    _add(pose, "RightUpLeg", [28 * s, 0, 0], w)
    _add(pose, "LeftLeg", [max(0, 40 * math.sin(ph + 1.2)), 0, 0], w)
    _add(pose, "RightLeg", [max(0, -40 * math.sin(ph + 1.2)), 0, 0], w)
    _add(pose, "LeftArm", [22 * s, 0, 0], w)
    _add(pose, "RightArm", [-22 * s, 0, 0], w)
    _add(pose, "Spine", [3, 0, 4 * s], w)
    return 0.02 * abs(math.cos(ph)) * w     # 髋部上下起伏


def clip_pose(clip: str, u: float, t_s: float, intensity: float = 1.0) -> tuple[dict, float]:
    """单个片段在局部进度 u∈[0,1]、绝对时间 t_s 的 (关节角, 髋部下沉 m)。"""
    p: dict = {}
    dz = 0.0
    e = _env(u)
    br = math.sin(2 * math.pi * 0.35 * t_s)       # 呼吸
    if clip in ("walk", "back_away"):
        dz -= walk(t_s, 1.0 if clip == "walk" else 0.6, p, 1.0 if clip == "walk" else 0.7)
        if clip == "back_away":
            _add(p, "Spine1", [8, 0, 0], e)
            _add(p, "LeftArm", [-20, -10, 0], e)
            _add(p, "RightArm", [-20, 10, 0], e)
            _add(p, "LeftForeArm", [-50, 0, 0], e)
            _add(p, "RightForeArm", [-50, 0, 0], e)
    elif clip == "talk":
        a = intensity
        g = math.sin(2 * math.pi * 1.3 * t_s)
        _add(p, "Head", [4 * g * a, 0, 6 * math.sin(2 * math.pi * 0.6 * t_s) * a], e)
        _add(p, "RightArm", [-25 * a - 10 * g * a, 0, 0], e)
        _add(p, "RightForeArm", [-55 * a + 15 * g * a, 0, 0], e)
        _add(p, "Spine2", [3 * g * a, 0, 0], e)
    elif clip == "demand":
        _add(p, "RightArm", [-70, 10, 0], e)
        _add(p, "RightForeArm", [-25, 0, 0], e)
        _add(p, "Spine1", [6, 0, 0], e)
        _add(p, "Head", [8, 0, 0], e)
    elif clip == "cower":
        _add(p, "Spine", [10, 0, 0], e)
        _add(p, "Spine1", [10, 0, 0], e)
        _add(p, "Head", [22, 0, 0], e)
        _add(p, "LeftArm", [-25, 10, 0], e)
        _add(p, "RightArm", [-25, -10, 0], e)
        _add(p, "LeftForeArm", [-70, 0, 0], e)
        _add(p, "RightForeArm", [-70, 0, 0], e)
        _add(p, "LeftShoulder", [0, 0, 6], e)
        _add(p, "RightShoulder", [0, 0, -6], e)
        _add(p, "Spine2", [2 * br, 0, 0])
    elif clip == "slap":
        # 抬手（0–0.45）→ 挥下（0.45–0.6）→ 收手
        up = _ease(min(1, u / 0.45))
        sw = _ease(min(1, max(0, (u - 0.45) / 0.15)))
        back = _ease(max(0, (u - 0.75) / 0.25))
        k = (1 - back)
        _add(p, "RightArm", [(-80 * up + 30 * sw) * k, (60 * up - 90 * sw) * k, 0])
        _add(p, "RightForeArm", [(-60 * up + 50 * sw) * k, 0, 0])
        _add(p, "Spine1", [0, 0, (25 * up - 45 * sw) * k])
        _add(p, "Head", [0, 0, -10 * up * k])
    elif clip == "recoil":
        e2 = _env(u, 0.08, 0.5)
        _add(p, "Head", [-12, 0, 35], e2)
        _add(p, "Spine2", [-6, 0, 15], e2)
        _add(p, "LeftArm", [-40, -10, 0], e2)
        _add(p, "LeftForeArm", [-100, 0, 0], e2)
    elif clip == "hold_face":
        _add(p, "Head", [18, 0, 10], e)
        _add(p, "LeftArm", [-45, -15, 0], e)
        _add(p, "LeftForeArm", [-115, 0, 0], e)
        _add(p, "Spine1", [8, 0, 0], e)
        _add(p, "Spine2", [2 * br, 0, 0])
    elif clip == "laugh":
        g = math.sin(2 * math.pi * 4 * t_s)
        _add(p, "Spine1", [-8 + 4 * g, 0, 0], e)
        _add(p, "Head", [-15 + 5 * g, 0, 0], e)
        _add(p, "RightArm", [-20, 0, 0], e)
        _add(p, "RightForeArm", [-80, 0, 0], e)
    elif clip == "look_down":
        _add(p, "Head", [20, 0, 0], e)
        _add(p, "Spine2", [-4, 0, 0], e)
    elif clip == "turn_head":
        _add(p, "Head", [5, 0, 45], e)
        _add(p, "Spine2", [0, 0, 15], e)
    elif clip == "grab":
        r = _ease(min(1, u / 0.4))
        _add(p, "RightArm", [-80 * r, 5, 0])
        _add(p, "RightForeArm", [-20 * r, 0, 0])
        _add(p, "Spine1", [12 * r, 0, 0])
        _add(p, "LeftArm", [-30 * r, -5, 0])
    elif clip == "kick":
        cock = _ease(min(1, u / 0.35))
        ext = _ease(min(1, max(0, (u - 0.35) / 0.15)))
        ret = _ease(max(0, (u - 0.7) / 0.3))
        k = 1 - ret
        _add(p, "RightUpLeg", [(-55 * cock - 30 * ext) * k, 0, 0])
        _add(p, "RightLeg", [(90 * cock - 85 * ext) * k, 0, 0])
        _add(p, "Spine", [(-12 * ext) * k, 0, 0])
        _add(p, "LeftArm", [-30 * k, -25 * k, 0])
        _add(p, "RightArm", [20 * k, 25 * k, 0])
    elif clip == "double_over":
        _add(p, "Spine", [25, 0, 0], e)
        _add(p, "Spine1", [20, 0, 0], e)
        _add(p, "Head", [10, 0, 0], e)
        _add(p, "LeftArm", [-35, 0, 0], e)
        _add(p, "RightArm", [-35, 0, 0], e)
        _add(p, "LeftForeArm", [-70, 0, 0], e)
        _add(p, "RightForeArm", [-70, 0, 0], e)
        _add(p, "LeftLeg", [20, 0, 0], e)
        _add(p, "RightLeg", [20, 0, 0], e)
        _add(p, "LeftUpLeg", [-15, 0, 0], e)
        _add(p, "RightUpLeg", [-15, 0, 0], e)
        dz -= 0.08 * e
    elif clip in ("slump", "crouch"):
        d = _ease(min(1, u / 0.5)) if clip == "slump" else e
        _add(p, "LeftUpLeg", [-95 * d, -10 * d, 0])
        _add(p, "RightUpLeg", [-95 * d, 10 * d, 0])
        _add(p, "LeftLeg", [125 * d, 0, 0])
        _add(p, "RightLeg", [125 * d, 0, 0])
        _add(p, "LeftFoot", [-30 * d, 0, 0])
        _add(p, "RightFoot", [-30 * d, 0, 0])
        _add(p, "Spine", [25 * d, 0, 0])
        _add(p, "Head", [25 * d, 0, 0])
        _add(p, "LeftArm", [-40 * d, -10 * d, 0])
        _add(p, "RightArm", [-40 * d, 10 * d, 0])
        _add(p, "LeftForeArm", [-60 * d, 0, 0])
        _add(p, "RightForeArm", [-60 * d, 0, 0])
        dz -= 0.42 * d
    elif clip == "stand_up":
        d = 1 - _ease(u)
        sub, sdz = clip_pose("crouch", 0.5, t_s)
        for b, v in sub.items():
            _add(p, b, v, d)
        dz += sdz * d
    elif clip == "tremble":
        g = math.sin(2 * math.pi * 7 * t_s)
        _add(p, "Spine1", [12 + 2 * g, 0, 0], e)
        _add(p, "Head", [25 + 2 * g, 0, 2 * g], e)
        _add(p, "LeftArm", [-10, 8, 0], e)
        _add(p, "RightArm", [-10, -8, 0], e)
        _add(p, "LeftForeArm", [-40 + 3 * g, 0, 0], e)
        _add(p, "RightForeArm", [-40 - 3 * g, 0, 0], e)
    elif clip in ("pick_up", "take_money"):
        b = math.sin(math.pi * min(1, u))
        _add(p, "Spine", [45 * b, 0, 0])
        _add(p, "Spine1", [20 * b, 0, 0])
        _add(p, "RightArm", [-60 * b, 0, 0])
        _add(p, "LeftUpLeg", [-30 * b, 0, 0])
        _add(p, "RightUpLeg", [-30 * b, 0, 0])
        _add(p, "LeftLeg", [50 * b, 0, 0])
        _add(p, "RightLeg", [50 * b, 0, 0])
        dz -= 0.15 * b
    elif clip == "idle_arms_crossed":
        _add(p, "LeftArm", [-35, -5, -20], e)
        _add(p, "RightArm", [-35, 5, 20], e)
        _add(p, "LeftForeArm", [-100, 0, 0], e)
        _add(p, "RightForeArm", [-100, 0, 0], e)
        _add(p, "Head", [3 * br, 0, 6 * math.sin(2 * math.pi * 0.2 * t_s)], e)
    return p, dz


def pose_at(clips: list[dict], t_ms: float) -> tuple[dict, float]:
    """该时刻所有生效片段叠加 + 站姿 + 呼吸。"""
    t_s = t_ms / 1000.0
    pose = {b: list(v) for b, v in REST.items()}
    br = math.sin(2 * math.pi * 0.35 * t_s)
    _add(pose, "Spine2", [1.5 * br, 0, 0])
    _add(pose, "Head", [0, 0, 3 * math.sin(2 * math.pi * 0.17 * t_s + 1)])
    dz = 0.0
    for c in clips:
        if c["start_ms"] <= t_ms <= c["end_ms"]:
            u = (t_ms - c["start_ms"]) / max(1.0, c["end_ms"] - c["start_ms"])
            p, d = clip_pose(c["clip"], u, t_s, float(c.get("intensity", 1.0)))
            for b, v in p.items():
                _add(pose, b, v)
            dz += d
    return {b: [round(x, 2) for x in v] for b, v in pose.items()}, round(dz, 4)


KNOWN_CLIPS = {"walk", "back_away", "talk", "demand", "cower", "slap", "recoil", "hold_face", "laugh", "look_down",
               "turn_head", "grab", "kick", "double_over", "slump", "crouch", "stand_up", "tremble", "pick_up",
               "take_money", "idle_arms_crossed"}
