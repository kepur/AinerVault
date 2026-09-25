"""机位 → CineCameraActor 轨道＋剪辑轨（Camera Cut Track）。

胶片背：36×24mm（与 3D-BOX／Blender 同一套焦段含义：水平视场 tan = 18/lens）。
每台机位逐帧变换＋焦距；剪辑轨按 cuts 切成若干段（帧号从 0 起，半开区间）。
"""
from __future__ import annotations

from typing import Any

from app.director.ue_worker import coords

CAM_STRIDE = 8


def camera_tracks(baked: dict[str, Any], step: int = 1) -> dict[str, dict[str, Any]]:
    out = {}
    n = baked["frames"]
    for cid, cam in (baked.get("cameras") or {}).items():
        data = cam["frames"]
        keys = []
        for i in list(range(0, n, step)) + ([n - 1] if (n - 1) % step else []):
            v = data[i * CAM_STRIDE:(i + 1) * CAM_STRIDE]
            keys.append({"frame": i, "location": coords.location(v[0:3]), "rotation": coords.look_rotator(v[0:3], v[3:6], v[7]),
                         "focal_length": round(v[6], 3)})
        out[cid] = {"name": cam["name"], "filmback_mm": [36.0, 24.0], "keys": keys}
    return out


def camera_cuts(baked: dict[str, Any]) -> list[dict[str, Any]]:
    """逐帧用哪台机位 → [{camera, start_frame, end_frame}]。"""
    ids = baked.get("camera", {}).get("ids") or []
    out: list[dict[str, Any]] = []
    for i, cid in enumerate(ids):
        if not cid:
            continue
        if out and out[-1]["camera"] == cid and out[-1]["end_frame"] == i:
            out[-1]["end_frame"] = i + 1
        else:
            out.append({"camera": cid, "start_frame": i, "end_frame": i + 1})
    return out


def translate(baked: dict[str, Any], *, key_step: int = 1) -> dict[str, Any]:
    return {"cameras": camera_tracks(baked, key_step), "cuts": camera_cuts(baked)}
