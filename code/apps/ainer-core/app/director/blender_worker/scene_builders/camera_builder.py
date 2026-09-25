"""机位：渲染用的「主机位」（按剪辑表逐帧切好）＋每台机位各自一份（存进 .blend 给人接手）。

焦段按 36mm 宽全画幅、水平适配 —— 与 3D-BOX 的 tan(半水平视场) = 18/lens 一致。
"""
from __future__ import annotations

import bpy

from ..common import new_object


def _camera(name: str, root, coll) -> bpy.types.Object:
    data = bpy.data.cameras.new(name)
    data.sensor_fit = "HORIZONTAL"
    data.sensor_width = 36.0
    data.clip_start = 0.05
    data.clip_end = 3000.0
    ob = new_object(name, data, root, coll)
    ob.rotation_mode = "QUATERNION"
    return ob


def build(baked: dict, root, coll) -> tuple[bpy.types.Object, dict[str, bpy.types.Object]]:
    main = _camera("AINER_主机位", root, coll)
    others = {cid: _camera(f"机位·{c['name']}", root, coll) for cid, c in (baked.get("cameras") or {}).items()}
    return main, others
