"""逐帧关键帧：物体轨迹、机位。

烘焙数据已经是逐帧采样（整数帧），这里每帧打一个关键帧；渲染只在整数帧取值，
关键帧之间怎么插值无所谓，所以不去碰各版本 Blender 变来变去的 F-Curve 接口。
帧号从 1 开始（Blender 惯例）：烘焙的第 i 帧 = Blender 第 i+1 帧。
"""
from __future__ import annotations

import math

from ..common import look_rotation

ANIM_STRIDE = 9     # [px,py,pz, rx,ry,rz, sx,sy,sz]
CAM_STRIDE = 8      # [px,py,pz, lx,ly,lz, lens, roll]


def key_transforms(ob, data: list[float], frames: int) -> None:
    for i in range(frames):
        v = data[i * ANIM_STRIDE:(i + 1) * ANIM_STRIDE]
        f = i + 1
        ob.location = v[0:3]
        ob.rotation_euler = (math.radians(v[3]), math.radians(v[4]), math.radians(v[5]))
        ob.scale = v[6:9]
        ob.keyframe_insert("location", frame=f)
        ob.keyframe_insert("rotation_euler", frame=f)
        ob.keyframe_insert("scale", frame=f)


def key_camera(ob, data: list[float], frames: int) -> None:
    """位置＋看向点＋焦段＋滚转 → 位置、四元数朝向、焦段。"""
    for i in range(frames):
        v = data[i * CAM_STRIDE:(i + 1) * CAM_STRIDE]
        f = i + 1
        ob.location = v[0:3]
        ob.rotation_quaternion = look_rotation(v[0:3], v[3:6], v[7])
        ob.data.lens = max(1.0, v[6])
        ob.keyframe_insert("location", frame=f)
        ob.keyframe_insert("rotation_quaternion", frame=f)
        ob.data.keyframe_insert("lens", frame=f)


def camera_at(data: list[float], i: int) -> dict:
    v = data[i * CAM_STRIDE:(i + 1) * CAM_STRIDE]
    return {"position": v[0:3], "look_at": v[3:6], "lens_mm": v[6], "roll_deg": v[7]}
