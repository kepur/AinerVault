"""3D-BOX ⇄ Ainer Scene Protocol。

两种写法，最后都落到同一份协议、同一套烘焙：
  脚本优先（3D-BOX）：LLM／人写 scene.js（沙箱里的 S.* 构建器）→ 场景文档 → doc_to_protocol 导出协议。
      摆一整条街、十二盏路灯、一排车流，LLM 写循环比吐几百行坐标 JSON 可靠得多。
  JSON 优先（API／LLM JSON 模式）：直接给协议 → protocol_to_script 生成等价的 scene.js →
      同一个沙箱跑出场景文档（于是 3D-BOX 能打开、能拖、能接着让智能体改）。
"""
from __future__ import annotations

import json
from typing import Any

from app.director.protocol import PROTOCOL, SceneProtocol
from app.pipelines.base import as_items

#: 协议里算「演员」的预制件：会朝运动方向走的车、船、动物
STEERED = {"car", "police_car", "truck", "bus", "motorcycle", "bicycle", "boat", "horse", "horse_cart", "helicopter", "bird", "dog", "cart"}
ANIMALS = {"horse", "bird", "dog"}
_TIME_OF_DAY = {"day": "day", "dawn": "dawn", "dusk": "dusk", "night": "night", "overcast": "day", "studio": "day"}


def _v3(v) -> list[float]:
    return [round(float(x), 4) for x in v]


# ── 场景文档 → 协议 ───────────────────────────────────────

def _camera_key(k: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"t": k["t"]}
    if k.get("at") is not None:
        out["position"] = _v3(k["at"])
    for f in ("follow", "orbit", "angle", "radius", "height", "roll"):
        if k.get(f) is not None:
            out[f] = k[f]
    if k.get("offset") is not None:
        out["offset"] = _v3(k["offset"])
    if k.get("look") is not None:
        out["look_at"] = k["look"]
    if k.get("lens") is not None:
        out["lens_mm"] = k["lens"]
    return out


def _op(o: dict[str, Any]) -> dict[str, Any] | None:
    """运行时记下的语义时间线 → 协议指令（字段改名，t → time）。"""
    name = o.get("op", "")
    base = {"op": name, "time": round(float(o.get("t") or 0), 4)}
    who = {k: o[k] for k in ("actor", "prop") if o.get(k)}
    if name in ("actor.move_to", "prop.move_to"):
        return {**base, **who, "target_position": _v3(o["to"]), "duration": o.get("duration"), "gait": o.get("action")}
    if name in ("actor.move_along", "prop.move_along"):
        return {**base, **who, "path": [_v3(p) for p in o["path"]], "duration": o.get("duration"), "gait": o.get("action")}
    if name in ("actor.move", "prop.move"):
        return {**base, **who, "keys": o.get("keys") or [], "gait": o.get("action")}
    if name == "actor.play_action":
        return {**base, "actor": o["actor"], "action": o["action"], "duration": o.get("duration"),
                **({"target_actor": o["target_actor"]} if o.get("target_actor") else {})}
    if name == "actor.set_pose":
        return {**base, "actor": o["actor"], "pose": o["pose"]}
    if name == "actor.look_at":
        return {**base, "actor": o["actor"], "target_actor": o["target_actor"], "duration": o.get("duration")}
    if name == "camera.follow":
        return {**base, "camera": o["camera"], "target_actor": o["target_actor"], "style": o.get("style", "back"),
                "duration": o.get("duration"), "distance": o.get("distance"), "height": o.get("height"),
                "side": 1 if (o.get("side") or 1) > 0 else -1}
    if name == "camera.move":
        t = o.get("target")
        return {**base, "camera": o["camera"], "preset": o["preset"], "target": _v3(t) if isinstance(t, list) else t,
                "duration": o.get("duration") or 4, **({"side": 1 if o["side"] > 0 else -1} if o.get("side") is not None else {}),
                **({"angle": o["angle"]} if o.get("angle") is not None else {})}
    if name == "camera.keys":
        return {**base, "camera": o["camera"], "keys": [_camera_key(k) for k in o.get("keys") or []]}
    if name == "camera.frame":
        return {**base, "camera": o["camera"], "target": o["target"], "size": o.get("size", "ms"), "angle": o.get("angle")}
    return None          # camera.cut 以最终的剪辑表为准（可能被手动改过），另外生成


def doc_to_protocol(doc: dict[str, Any], *, scene_id: str, title: str, source: dict[str, Any] | None = None,
                    baked: dict[str, Any] | None = None) -> dict[str, Any]:
    """编译好的 3D-BOX 场景文档（含手动改动）→ 协议 JSON（已校验）。baked 有的话，机位起幅按 t=0 实际位置写。"""
    env = doc.get("env") or {}
    objs = doc.get("objects") or []
    assets: dict[str, dict[str, Any]] = {}
    actors, props = [], []
    for o in objs:
        t = o.get("transform") or {}
        spawn = {"position": _v3(t.get("pos", [0, 0, 0])), "rotation": _v3(t.get("rot", [0, 0, 0])),
                 "scale": _v3(t.get("scale", [1, 1, 1]))}
        if o["kind"] == "character":
            body = o.get("body") or "male"
            assets.setdefault(f"mannequin:{body}", {"id": f"mannequin:{body}", "type": "mannequin", "ref": body})
            if o.get("ref"):
                assets.setdefault(f"character:{o['ref']}", {"id": f"character:{o['ref']}", "type": "character_ref", "ref": o["ref"]})
            poses = o.get("poses") or []
            actors.append({"id": o["id"], "name": o.get("name"), "type": "human", "model_ref": f"mannequin/{body}",
                           "character_ref": o.get("ref"), "spawn": spawn, "parent": o.get("parent"),
                           "appearance": {k: v for k, v in {"color": o.get("color")}.items() if v},
                           "pose": poses[0]["pose"] if poses and poses[0].get("t", 0) <= 0 else None})
            continue
        if o.get("prefab"):
            assets.setdefault(f"prefab:{o['prefab']}", {"id": f"prefab:{o['prefab']}", "type": "procedural_prefab", "ref": o["prefab"]})
        if o.get("prefab") in STEERED:
            actors.append({"id": o["id"], "name": o.get("name"), "type": "animal" if o["prefab"] in ANIMALS else "vehicle",
                           "model_ref": f"prefab/{o['prefab']}", "spawn": spawn, "params": o.get("params") or {},
                           "parent": o.get("parent"), "appearance": {k: v for k, v in {"color": o.get("color")}.items() if v}})
            continue
        prop: dict[str, Any] = {"id": o["id"], "name": o.get("name"), "spawn": spawn, "color": o.get("color"),
                                "parent": o.get("parent"), "hidden": "hidden" in (o.get("tags") or [])}
        if o["kind"] == "prefab":
            prop.update(prefab=o["prefab"], params=o.get("params") or {})
        elif o["kind"] == "prim":
            prop.update(primitive=o.get("prim"), size=_v3(o.get("size") or [1, 1, 1]))
        elif o["kind"] == "strip":
            prop["strip"] = o.get("strip")
        props.append(prop)

    cameras = []
    for c in as_items(doc, "cameras"):
        cam: dict[str, Any] = {"id": c["id"], "name": c.get("name"), "lens_mm": c.get("lens", 35), "shake": c.get("shake", 0),
                               "keys": [_camera_key(k) for k in c.get("keys") or []], "presets": c.get("presets") or [],
                               "type": "handheld" if (c.get("shake") or 0) > 0.3 else
                               "follow" if any(k.get("follow") for k in c.get("keys") or []) else "cinematic"}
        if baked and c["id"] in (baked.get("cameras") or {}):
            f = baked["cameras"][c["id"]]["frames"][:8]
            cam["transform"] = {"position": _v3(f[0:3]), "rotation": [0.0, 0.0, round(f[7], 3)], "scale": [1, 1, 1]}
        cameras.append(cam)

    timeline = [x for x in (_op(o) for o in doc.get("timeline") or []) if x]
    timeline += [{"op": "camera.cut", "time": c["t"], "camera": c["camera"]} for c in doc.get("cuts") or []]
    timeline = [{k: v for k, v in op.items() if v is not None} for op in timeline]
    timeline.sort(key=lambda x: x["time"])

    lights = [{"id": lt.get("id"), "kind": lt["kind"], "color": lt.get("color", "#ffffff"), "intensity": lt.get("intensity", 1),
               "position": lt.get("at"), "direction": lt.get("dir"), "range": lt.get("range")} for lt in doc.get("lights") or []]
    sky = env.get("sky", "day")
    out = {
        "protocol": PROTOCOL, "scene_id": scene_id,
        "meta": {"title": title, "fps": doc.get("fps", 24), "duration_sec": doc.get("duration", 6),
                 "aspect": doc.get("aspect", 16 / 9), "source": source},
        "environment": {"sky": sky, "ground": env.get("ground", "grid"), "ground_size": env.get("groundSize", 120),
                        "fog": env.get("fog", 0), "time_of_day": _TIME_OF_DAY.get(sky, "day"),
                        "weather": "fog" if (env.get("fog") or 0) > 0.5 else ("overcast" if sky == "overcast" else "clear"),
                        "preset": f"{env.get('ground', 'grid')}_{sky}", "lights": lights},
        "assets": list(assets.values()), "actors": actors, "props": props, "cameras": cameras, "timeline": timeline,
    }
    return SceneProtocol.model_validate(out).model_dump(mode="json", exclude_none=True)


# ── 协议 → 场景脚本 ───────────────────────────────────────

def _j(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False)


def _key_js(k: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"t": k["t"]}
    if k.get("position") is not None:
        out["at"] = k["position"]
    for f in ("follow", "offset", "orbit", "angle", "radius", "height", "roll"):
        if k.get(f) is not None:
            out[f] = k[f]
    if k.get("look_at") is not None:
        out["look"] = k["look_at"]
    if k.get("lens_mm") is not None:
        out["lens"] = k["lens_mm"]
    if not any(f in out for f in ("at", "follow", "orbit")):
        out["at"] = [0, 1.6, 8]
    return out


def protocol_to_script(p: SceneProtocol | dict[str, Any]) -> str:
    """协议 → 等价的 scene.js。生成的脚本只用公开的 S.* 构建器，照样在沙箱里跑、照样能在 3D-BOX 里改。"""
    sp = p if isinstance(p, SceneProtocol) else SceneProtocol.model_validate(p)
    d = sp.model_dump(mode="json", exclude_none=True)
    m, env = d["meta"], d["environment"]
    L = [f"// 由 Ainer Scene Protocol 生成：{m['title']}（{sp.scene_id}）",
         f"S.setup({{ duration: {m['duration_sec']}, fps: {m['fps']}, aspect: {round(m['aspect'], 5)} }});",
         f"S.environment({_j({'sky': env['sky'], 'ground': env['ground'], 'groundSize': env['ground_size'], 'fog': env['fog']})});"]
    for lt in as_items(env, "lights"):
        o = {"color": lt.get("color", "#ffffff"), "intensity": lt.get("intensity", 1)}
        if lt.get("position"):
            o["at"] = lt["position"]
        if lt.get("direction"):
            o["dir"] = lt["direction"]
        if lt.get("range"):
            o["range"] = lt["range"]
        L.append(f"S.light({_j(lt['kind'])}, {_j(o)});")
    if d["props"]:
        L.append("\n// 场景物体")
    for pr in d["props"]:
        sp_ = pr.get("spawn") or {}
        o: dict[str, Any] = {"id": pr["id"], "name": pr.get("name") or pr["id"], "at": sp_.get("position", [0, 0, 0]),
                             "rot": sp_.get("rotation", [0, 0, 0]), "scale": sp_.get("scale", [1, 1, 1])}
        if pr.get("color"):
            o["color"] = pr["color"]
        if pr.get("parent"):
            o["parent"] = pr["parent"]
        if pr.get("strip"):
            s = pr["strip"]
            L.append(f"S.road({_j({'name': pr.get('name') or pr['id'], 'path': s.get('points'), 'width': s.get('width', 8), 'kind': s.get('kind', 'asphalt'), 'lines': s.get('lines', True)})});")
        elif pr.get("primitive"):
            size = pr.get("size") or [1, 1, 1]
            kind = {"capsule": "cylinder", "prism": "box"}.get(pr["primitive"], pr["primitive"])
            if kind == "box":
                o["size"] = size
            elif kind == "plane":
                o["size"] = [size[0], size[2]]
            elif kind == "sphere":
                o["r"] = size[0] / 2
            elif kind == "torus":
                o["r"], o["tube"] = size[0] / 2, size[2] / 2
            else:
                o["r"], o["h"] = size[0] / 2, size[1]
            L.append(f"S.{kind}({_j(o)});")
        elif pr.get("prefab"):
            L.append(f"S.add({_j(pr['prefab'])}, {_j({**(pr.get('params') or {}), **o})});")
        if pr.get("hidden"):
            L.append(f"// 「{pr['id']}」在协议里是隐藏的：成片不画")
    if d["actors"]:
        L.append("\n// 演员")
    for a in d["actors"]:
        sp_ = a.get("spawn") or {}
        o = {"id": a["id"], "at": sp_.get("position", [0, 0, 0]), "rot": sp_.get("rotation", [0, 0, 0])}
        if (a.get("appearance") or {}).get("color"):
            o["color"] = a["appearance"]["color"]
        if a.get("parent"):
            o["parent"] = a["parent"]
        if a.get("type", "human") == "human":
            ref = a.get("model_ref", "mannequin/male")
            o["body"] = ref.split("/", 1)[1] if ref.startswith("mannequin/") else "male"
            if a.get("character_ref"):
                o["ref"] = a["character_ref"]
            L.append(f"S.character({_j(a.get('name') or a['id'])}, {_j(o)});")
            if a.get("pose"):
                L.append(f"S.pose({_j(a['id'])}, {_j(a['pose'])}, 0);")
        else:
            prefab = a.get("model_ref", "prefab/car").split("/", 1)[-1]
            L.append(f"S.add({_j(prefab)}, {_j({**(a.get('params') or {}), **o, 'name': a.get('name') or a['id']})});")
    if d["cameras"]:
        L.append("\n// 机位")
    for c in d["cameras"]:
        L.append(f"S.camera({_j(c.get('name') or c['id'])}, {_j({'id': c['id'], 'lens': c.get('lens_mm', 35), 'shake': c.get('shake', 0)})});")
        if c.get("keys"):
            L.append(f"S.cameraKeys({_j(c['id'])}, {_j([_key_js(k) for k in c['keys']])});")
    if d["timeline"]:
        L.append("\n// 时间线")
    # 机位已经带着最终关键帧（运镜预设展开后的、手动改过的）就以关键帧为准：
    # 时间线里这台机位的运镜指令只是「怎么来的」的记录，再执行一遍关键帧就重复了
    keyed = {c["id"] for c in d["cameras"] if c.get("keys")}
    for op in d["timeline"]:
        t, name = op["time"], op["op"]
        if name.startswith("camera.") and name != "camera.cut" and op.get("camera") in keyed:
            continue
        who = op.get("actor") or op.get("prop")
        if name in ("actor.move_to", "prop.move_to"):
            o = {"t": t, **({"duration": op["duration"]} if op.get("duration") else {}), **({"speed": op["speed"]} if op.get("speed") else {}),
                 **({"action": op["gait"]} if op.get("gait") else {})}
            L.append(f"S.moveTo({_j(who)}, {_j(op['target_position'])}, {_j(o)});")
        elif name in ("actor.move_along", "prop.move_along"):
            o = {"path": op["path"], "start": t, **({"duration": op["duration"]} if op.get("duration") else {}),
                 **({"speed": op["speed"]} if op.get("speed") else {}), **({"action": op["gait"]} if op.get("gait") else {})}
            L.append(f"S.moveAlong({_j(who)}, {_j(o)});")
        elif name in ("actor.move", "prop.move"):
            keys = [{k: v for k, v in kk.items() if k in ("t", "at", "rot", "scale") and v is not None} for kk in op["keys"]]
            L.append(f"S.move({_j(who)}, {_j(keys)}, {_j({'action': op['gait']} if op.get('gait') else {})});")
        elif name == "actor.play_action":
            o = {"t": t, **({"duration": op["duration"]} if op.get("duration") else {}),
                 **({"target": op["target_actor"]} if op.get("target_actor") else {})}
            L.append(f"S.action({_j(who)}, {_j(op['action'])}, {_j(o)});")
        elif name == "actor.set_pose":
            L.append(f"S.pose({_j(who)}, {_j(op['pose'])}, {t});")
        elif name == "actor.look_at":
            L.append(f"S.face({_j(who)}, {_j(op['target_actor'])}, {_j({'t': t, **({'duration': op['duration']} if op.get('duration') else {})})});")
        elif name == "camera.follow":
            style = {"side_follow": "side"}.get(op.get("style", "back"), op.get("style", "back"))
            o = {"mode": style, "start": t, "side": op.get("side", 1),
                 **({"end": t + op["duration"]} if op.get("duration") else {}),
                 **({"distance": op["distance"]} if op.get("distance") else {}),
                 **({"height": op["height"]} if op.get("height") is not None else {})}
            L.append(f"S.cameraFollow({_j(op['camera'])}, {_j(op['target_actor'])}, {_j(o)});")
        elif name == "camera.move":
            o = {"start": t, "duration": op.get("duration", 4), **({"target": op["target"]} if op.get("target") is not None else {}),
                 **({"side": op["side"]} if op.get("side") is not None else {}), **({"angle": op["angle"]} if op.get("angle") is not None else {})}
            L.append(f"S.cameraPreset({_j(op['camera'])}, {_j(op['preset'])}, {_j(o)});")
        elif name == "camera.keys":
            L.append(f"S.cameraKeys({_j(op['camera'])}, {_j([_key_js(k) for k in op['keys']])});")
        elif name == "camera.frame":
            L.append(f"S.frame({_j(op['camera'])}, {t}, {_j(op['target'])}, {_j(op.get('size', 'ms'))}, {_j({'angle': op['angle']} if op.get('angle') is not None else {})});")
        elif name == "camera.cut":
            L.append(f"S.cut({t}, {_j(op['camera'])});")
    return "\n".join(L) + "\n"
