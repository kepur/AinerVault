"""camera.json：逐帧机位。两套坐标都给 —— 场景坐标（Y 向上，与协议一致）和 Blender 世界矩阵（Z 向上）。"""
from __future__ import annotations

import json
import math

from ..motion.trajectory_tools import camera_at


def write(path: str, baked: dict, walk: dict, res: tuple[int, int]) -> str:
    W, H = res
    fps = baked["fps"]
    ids = baked["camera"]["ids"]
    frames = []
    for i in range(baked["frames"]):
        c = camera_at(baked["camera"]["frames"], i)
        lens = c["lens_mm"]
        fov_h = 2 * math.degrees(math.atan(18.0 / lens))
        fov_v = 2 * math.degrees(math.atan(18.0 / lens * H / W))
        frames.append({
            "frame": i + 1, "time": round(baked["t0"] + i / fps, 4), "camera_id": ids[i] if i < len(ids) else "",
            **c, "fov_h_deg": round(fov_h, 3), "fov_v_deg": round(fov_v, 3),
            "blender_matrix_world": walk["camera"][i]["matrix_world"] if i < len(walk.get("camera", [])) else None,
        })
    doc = {
        "fps": fps, "frames": baked["frames"], "resolution": [W, H],
        "sensor": {"width_mm": 36.0, "fit": "horizontal"},
        "coordinate_system": {"up": "+Y", "forward": "+Z", "handedness": "right", "unit": "meter",
                              "blender": "Z-up; scene (x, y, z) = blender (x, -z, y)"},
        "cuts": baked.get("cuts") or [],
        "cameras": {cid: c["name"] for cid, c in (baked.get("cameras") or {}).items()},
        "frames_data": frames,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    return path
