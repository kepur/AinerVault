"""生成 Unreal Python：在当前关卡里摆出场景（物体、人偶、灯）。

生成的是纯文本脚本（离线调试：在 UE 的 Python 控制台里粘贴运行，或经 Remote Control 远程执行）。
数据以 JSON 字面量嵌进脚本，脚本本身不拼接任何外来字符串进代码 —— 只 json.loads 一段数据。
"""
from __future__ import annotations

import json
from typing import Any

TEMPLATE = '''# Ainer Director · 摆场景（由 ainer-core 生成，勿手改）
import json
import unreal

PLAN = json.loads({plan!r})
actors_sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
spawned = {{}}


def vec(v):
    return unreal.Vector(v[0], v[1], v[2])


def rot(r):
    return unreal.Rotator(roll=r["Roll"], pitch=r["Pitch"], yaw=r["Yaw"])


for a in PLAN["actors"]:
    if a["kind"] in ("static_mesh", "skeletal_mesh"):
        asset = unreal.EditorAssetLibrary.load_asset(a["asset"])
        if asset is None:
            unreal.log_warning("找不到资产 %s（%s），用空物体代替" % (a["asset"], a["id"]))
            actor = actors_sub.spawn_actor_from_class(unreal.Actor, vec(a["location"]), rot(a["rotation"]))
        else:
            actor = actors_sub.spawn_actor_from_object(asset, vec(a["location"]), rot(a["rotation"]))
        actor.set_actor_scale3d(vec(a.get("scale", [1, 1, 1])))
    else:
        actor = actors_sub.spawn_actor_from_class(unreal.Actor, vec(a["location"]), rot(a["rotation"]))
    actor.set_actor_label("ainer_" + a["id"])
    actor.tags = [unreal.Name("ainer"), unreal.Name("ainer_id:" + a["id"])]
    spawned[a["id"]] = actor

for a in PLAN["actors"]:
    if a.get("parent") and a["parent"] in spawned:
        spawned[a["id"]].attach_to_actor(spawned[a["parent"]], unreal.Name(""), unreal.AttachmentRule.KEEP_RELATIVE,
                                         unreal.AttachmentRule.KEEP_RELATIVE, unreal.AttachmentRule.KEEP_RELATIVE, False)

LIGHT = {{"sun": unreal.DirectionalLight, "point": unreal.PointLight, "spot": unreal.SpotLight}}
for lt in PLAN["lights"]:
    cls = LIGHT.get(lt["kind"])
    if cls is None:
        continue
    actor = actors_sub.spawn_actor_from_class(cls, vec(lt.get("location", [0, 0, 500])), rot(lt.get("rotation", {{"Pitch": -50, "Yaw": 0, "Roll": 0}})))
    actor.set_actor_label("ainer_light_" + str(lt.get("id")))

unreal.log("Ainer：摆好 %d 个物体、%d 盏灯" % (len(spawned), len(PLAN["lights"])))
'''


def generate(level_plan: dict[str, Any]) -> str:
    return TEMPLATE.format(plan=json.dumps(level_plan, ensure_ascii=False))
