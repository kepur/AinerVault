"""Ainer Scene Protocol（＋烘焙数据）→ UE 关卡里的物体清单。

UE 里没有我们的程序化白模：预制件按 asset_map 换成 UE 资产；没配的用引擎自带立方体按包围盒缩放占位
（位置、朝向、大小都对，拿来摆机位够用）。人物统一用 UE 人偶骨骼网格体。
"""
from __future__ import annotations

from typing import Any

from app.director.ue_worker import coords
from app.pipelines.base import as_items

CUBE = "/Engine/BasicShapes/Cube.Cube"          # 100cm 立方体


def _bounds(parts: list[dict[str, Any]]) -> tuple[list[float], list[float]]:
    lo, hi = [1e9, 1e9, 1e9], [-1e9, -1e9, -1e9]
    for p in parts:
        for i in range(3):
            lo[i] = min(lo[i], p["pos"][i] - p["size"][i] / 2)
            hi[i] = max(hi[i], p["pos"][i] + p["size"][i] / 2)
    return lo, hi


def translate(protocol: dict[str, Any], baked: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    asset_map: dict[str, str] = cfg.get("asset_map") or {}
    mannequin = cfg.get("mannequin_asset") or "/Game/Characters/Mannequins/Meshes/SKM_Quinn_Simple"
    actors: list[dict[str, Any]] = []
    for o in as_items(baked, "objects"):
        base = {"id": o["id"], "label": o.get("name") or o["id"], "parent": o.get("parent"),
                "location": coords.location(o["pos"]), "rotation": coords.rotator(o["rot"]), "animated": o.get("animated", False)}
        if o["kind"] == "character":
            actors.append({**base, "kind": "skeletal_mesh", "asset": asset_map.get(f"mannequin/{o['character']['body']}", mannequin),
                           "scale": coords.scale3(o["scale"]), "height_cm": round(o["character"]["height"] * 100, 1),
                           "character_ref": o["character"].get("ref")})
        elif o.get("parts"):
            asset = asset_map.get(f"prefab/{o.get('prefab')}")
            if asset:
                actors.append({**base, "kind": "static_mesh", "asset": asset, "scale": coords.scale3(o["scale"])})
            else:
                lo, hi = _bounds(o["parts"])
                size = [max(0.02, hi[i] - lo[i]) * o["scale"][i] for i in range(3)]
                center = [(lo[i] + hi[i]) / 2 for i in range(3)]
                actors.append({**base, "kind": "static_mesh", "asset": CUBE, "placeholder": True, "prefab": o.get("prefab"),
                               "pivot_offset_cm": coords.location(center), "scale": coords.scale3(size)})
        elif o.get("strip"):
            actors.append({**base, "kind": "spline", "points_cm": [coords.location([p[0], 0.0, p[1]]) for p in o["strip"]["points"]],
                           "width_cm": round(o["strip"]["width"] * 100, 1), "strip_kind": o["strip"]["kind"]})
        else:
            actors.append({**base, "kind": "empty"})
    lights = []
    for lt in as_items(baked, "lights"):
        item = {"id": lt.get("id"), "kind": lt["kind"], "color": lt.get("color", "#ffffff"), "intensity": lt.get("intensity", 1)}
        if lt.get("at"):
            item["location"] = coords.location(lt["at"])
        if lt.get("dir"):
            d = lt["dir"]
            item["rotation"] = coords.look_rotator((0, 0, 0), d)
        lights.append(item)
    env = protocol.get("environment") or {}
    return {
        "level": cfg.get("level") or "/Game/Ainer/Maps/Previs",
        "environment": {"preset": env.get("preset"), "time_of_day": env.get("time_of_day"), "weather": env.get("weather"),
                        "fog": env.get("fog", 0), "ground_size_cm": round(float(env.get("ground_size", 120)) * 100, 1)},
        "actors": actors, "lights": lights,
    }
