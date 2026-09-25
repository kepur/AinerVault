"""道具、建筑、交通工具、基本体、道路：部件表 → 网格，按父子关系挂好，摆到基础位姿。"""
from __future__ import annotations

import bpy

from ..common import material, new_object, parts_mesh, set_trs, strip_mesh
from ..loaders import asset_loader


def build_all(baked: dict, root, coll, media_root: str | None = None, on_character=None) -> dict[str, bpy.types.Object]:
    """按文档顺序建全部物体（父物体总在前面）。人物交给 on_character(b, parent) 建。返回 id → Blender 物体。"""
    objs: dict[str, bpy.types.Object] = {}
    for b in baked["objects"]:
        parent = objs.get(b["parent"]) if b.get("parent") else root
        if b["kind"] == "character":
            if on_character is not None and b.get("character"):
                objs[b["id"]] = on_character(b, parent or root)
            continue
        name = b["id"]
        if b.get("parts"):
            ob = new_object(name, parts_mesh(name, b["parts"]), parent or root, coll)
            img = b.get("image")
            path = asset_loader.local_media(img["url"], media_root) if img else None
            if path:
                asset_loader.board_face(f"{name}.image", img["width"], img["height"], path, ob, coll)
        elif b.get("strip"):
            s = b["strip"]
            me = strip_mesh(name, s["points"], s["width"], s["y"])
            me.materials.append(material(s["color"]))
            ob = new_object(name, me, parent or root, coll)
        else:
            ob = new_object(name, None, parent or root, coll)       # 组：空物体
            ob.empty_display_size = 0.3
        set_trs(ob, b["pos"], b["rot"], b["scale"])
        ob["ainer_id"] = b["id"]
        objs[b["id"]] = ob
    return objs
