"""人物：角色空物体（承接轨迹位姿）＋人偶骨架（承接逐帧关节）。"""
from __future__ import annotations

import bpy

from ..common import new_object, set_trs
from ..loaders import character_loader


class ActorBuilder:
    """给 prop_builder.build_all 当 on_character 用：建一个人，记下骨架和关键点。"""

    def __init__(self, coll):
        self.coll = coll
        self.actors: dict[str, dict] = {}

    def __call__(self, b: dict, parent) -> bpy.types.Object:
        ob = new_object(b["id"], None, parent, self.coll)
        ob.empty_display_size = 0.4
        set_trs(ob, b["pos"], b["rot"], b["scale"])
        ob["ainer_id"] = b["id"]
        rig = character_loader.build_mannequin(b["id"], b["character"], ob, self.coll)
        self.actors[b["id"]] = {"obj": ob, "name": b["name"], "body": b["character"]["body"], **rig}
        return ob
