"""motion.json：每个角色逐帧的根位置、OpenPose 18 点（画面像素＋场景 3D 坐标），以及语义动作清单。"""
from __future__ import annotations

import json

from ..motion.action_mapper import map_semantic

KEYPOINT_NAMES = ["nose", "neck", "r_shoulder", "r_elbow", "r_wrist", "l_shoulder", "l_elbow", "l_wrist",
                  "r_hip", "r_knee", "r_ankle", "l_hip", "l_knee", "l_ankle", "r_eye", "l_eye", "r_ear", "l_ear"]


def write(path: str, baked: dict, actors: dict, walk: dict, res: tuple[int, int]) -> str:
    out = {}
    for aid, a in actors.items():
        out[aid] = {
            "name": a["name"], "body": a["body"],
            "actions": map_semantic(baked.get("timeline") or [], aid),
            "frames": walk["actors"].get(aid, []),
        }
    doc = {"fps": baked["fps"], "frames": baked["frames"], "resolution": list(res),
           "keypoint_format": "openpose_coco18", "keypoint_names": KEYPOINT_NAMES,
           "coordinate_system": {"up": "+Y", "unit": "meter", "image": "pixels, origin top-left"},
           "actors": out}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    return path
