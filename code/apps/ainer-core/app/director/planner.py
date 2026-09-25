"""LLM Planner：自然语言 → Ainer Scene JSON；修改指令 → JSON Patch；场景 → 成片提示词。

LLM 只输出结构化 JSON，不写 bpy、不写 Unreal Python、不碰文件和命令。
校验不过就把错误原样交还给它改（最多 planner_max_repairs 次）。
模型走免费的 text.chat 路由（与 3D-BOX 智能体同一个 purpose）。
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.capability.router import resolve_routes
from app.capability.schemas import Capability
from app.capability.service import submit_task
from app.director import config
from app.director import patch as jpatch
from app.director.protocol import PROTOCOL, SceneProtocol, catalog_ids
from app.models import TaskStatus
from app.pipelines.base import as_items


class PlannerError(RuntimeError):
    pass


def _purpose() -> str:
    return str(config.load("director").get("llm_purpose") or "scene_director")


def _llm_json(db: Session, system: str, user: str, *, model: str | None = None, temperature: float = 0.3) -> dict[str, Any]:
    route = None
    if model:
        route = next((r for r in resolve_routes(db, Capability.text_chat, _purpose(), None) if r.model == model), None)
        if route is None:
            raise PlannerError(f"没有可用的模型「{model}」")
    task = submit_task(
        db, Capability.text_chat,
        {"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
         "temperature": temperature, "max_tokens": 8192,
         "response_format": {"type": "json_schema", "schema": {"type": "object"}}},
        purpose=_purpose(), sync=True, route=route, force=True, ref_kind="director_planner",
    )
    if task.status != TaskStatus.succeeded:
        err = task.error_json or {}
        raise PlannerError(f"模型调用失败 [{err.get('code')}]: {err.get('message')}")
    data = (task.result_json or {}).get("json")
    if not isinstance(data, dict):
        text = (task.result_json or {}).get("text") or ""
        try:
            data = json.loads(text[text.index("{"):text.rindex("}") + 1])
        except (ValueError, json.JSONDecodeError) as exc:
            raise PlannerError("模型没有返回 JSON 对象") from exc
    return data


def _catalog_text() -> str:
    ids = catalog_ids()
    try:
        from app.scene3d.runner import catalog
        cat = catalog()
        motions = "、".join(f"{m['id']}（{m['zh']}{'，可带 target' if m.get('target') else ''}）" for m in cat.get("motions", []))
        cams = "、".join(f"{p['id']}（{p['zh']}）" for p in cat.get("cameraPresets", []))
        prefabs = "、".join(f"{p['name']}（{p['zh']}）" for p in cat.get("prefabs", []))
        bodies = "、".join(f"{b['name']}（{b['zh']}）" for b in cat.get("bodies", []))
        poses = "、".join(f"{p['name']}（{p['zh']}）" for p in cat.get("poses", []))
    except Exception:            # noqa: BLE001
        motions, cams = "、".join(ids["motions"]), "、".join(ids["camera_presets"])
        prefabs, bodies, poses = "、".join(ids["prefabs"]), "、".join(ids["bodies"]), "、".join(ids["poses"])
    return (f"动作库（actor.play_action.action）：{motions}\n运镜库（camera.move.preset）：{cams}\n"
            f"预制件（props[].prefab；车、马、船等会动的写进 actors，type=vehicle/animal，model_ref=prefab/<名字>）：{prefabs}\n"
            f"人物体型（actors[].model_ref=mannequin/<体型>）：{bodies}\n姿势（actors[].pose / actor.set_pose）：{poses}")


EXAMPLE = {
    "protocol": PROTOCOL, "scene_id": "scene_example",
    "meta": {"title": "夜巷打斗", "fps": 24, "duration_sec": 6},
    "environment": {"preset": "alley_night", "weather": "rain", "time_of_day": "night", "sky": "night", "ground": "asphalt", "fog": 0.2},
    "actors": [
        {"id": "A", "name": "A", "type": "human", "model_ref": "mannequin/male", "spawn": {"position": [0, 0, -6], "rotation": [0, 0, 0]},
         "appearance": {"look": "lean young man, black leather jacket"}},
        {"id": "B", "name": "B", "type": "human", "model_ref": "mannequin/muscular", "spawn": {"position": [0, 0, 1], "rotation": [0, 180, 0]},
         "pose": "fight", "appearance": {"look": "muscular bald man, white tank top"}},
    ],
    "props": [
        {"id": "wall_left", "prefab": "building", "spawn": {"position": [-13, 0, 0], "rotation": [0, 90, 0]}},
        {"id": "wall_right", "prefab": "building", "spawn": {"position": [13, 0, 0], "rotation": [0, -90, 0]}},
    ],
    "cameras": [{"id": "cam_01", "name": "侧跟", "lens_mm": 35}],
    "timeline": [
        {"op": "actor.move_to", "time": 0, "actor": "A", "target_position": [0, 0, 0], "gait": "run"},
        {"op": "actor.play_action", "time": 1.5, "actor": "A", "action": "right_punch", "target_actor": "B"},
        {"op": "actor.play_action", "time": 1.6, "actor": "B", "action": "dodge_left"},
        {"op": "actor.play_action", "time": 2.4, "actor": "B", "action": "front_kick", "target_actor": "A"},
        {"op": "actor.play_action", "time": 2.75, "actor": "A", "action": "hit_react_back"},
        {"op": "actor.play_action", "time": 3.4, "actor": "A", "action": "fall_backward"},
        {"op": "camera.move", "time": 0, "camera": "cam_01", "preset": "side_follow", "target": "A", "duration": 6},
        {"op": "camera.cut", "time": 0, "camera": "cam_01"},
    ],
}

SYSTEM_GENERATE = f"""你是影视预演（previs）的场景规划器。把导演的一句话变成一份 Ainer Scene Protocol v1 的 JSON。
只输出这一个 JSON 对象，不要解释。

坐标：Y 向上，单位米，地面 y=0；位置写 [x, y, z]，y 一般是 0；朝向写 rotation=[0, yaw, 0]（度），
yaw 0 面向 +Z、yaw 90 面向 +X、yaw 180 面向 -Z。两个人对打时要面对面（朝向相差 180°），间距 1–1.5 米起手。

结构：
  meta {{title, fps, duration_sec}}
  environment {{preset, weather: clear|rain|fog|snow|overcast, time_of_day: day|dawn|dusk|night,
               sky: day|dawn|dusk|night|overcast|studio, ground: grid|asphalt|grass|sand|snow|water|stone|floor|dirt, fog 0–1}}
  actors [{{id, name, type: human|vehicle|animal, model_ref, spawn {{position, rotation}}, pose?, appearance {{look: 英文外观描述}}}}]
  props [{{id, prefab, spawn {{position, rotation}}, params?}}]  —— 布景：建筑、路灯、树、车（不动的车也可以放这里）
  cameras [{{id, name, lens_mm}}]  —— 机位先不写 keys，用时间线里的 camera.* 指令安排运镜
  timeline（time 秒，从 0 起）：
    actor.move_to {{actor, target_position, gait: walk|run, duration?}}     走/跑到某处（不写 duration 按步速算）
    actor.play_action {{actor, action, duration?, target_actor?}}          动作库里的动作；出拳踢腿写 target_actor
    actor.set_pose {{actor, pose}}                                         换姿势
    actor.look_at {{actor, target_actor}}                                  转身面向
    camera.move {{camera, preset, target, duration}}                       运镜库里的运镜
    camera.follow {{camera, target_actor, style: back|front|side, duration?}}
    camera.cut {{camera}}                                                  从 time 起切到这台机位（至少要有一条 time=0 的）
  render_plan 不用写。

规则：时间线里引用的 id 必须在 actors/props/cameras 里；time 不能超过 duration_sec；
动作之间给够时间（出拳 0.6 秒、前踢 0.8 秒、倒地 1.2 秒）；布景别挡住机位（侧跟机位离人约 5 米）。

{{CATALOG}}

示例（「夜晚巷子里两人打斗，A 跑近右拳，B 闪避后前踢，A 倒地，侧面跟拍，6 秒」）：
{json.dumps(EXAMPLE, ensure_ascii=False)}
"""


def _system_generate() -> str:
    return SYSTEM_GENERATE.replace("{CATALOG}", _catalog_text())


def _errors(exc: Exception) -> str:
    return str(exc)[:1500]


def generate_protocol(db: Session, prompt: str, *, duration: float | None = None, model: str | None = None,
                      scene_id: str | None = None) -> tuple[dict[str, Any], list[str]]:
    """一句话 → 协议 JSON（已校验）。返回 (协议, 修改记录)。"""
    user = f"导演的要求：{prompt.strip()}" + (f"\n时长：{duration} 秒" if duration else "")
    tries = int(config.load("director").get("planner_max_repairs") or 2)
    log: list[str] = []
    data = _llm_json(db, _system_generate(), user, model=model)
    for attempt in range(tries + 1):
        data["protocol"] = PROTOCOL
        data["scene_id"] = scene_id or data.get("scene_id") or "scene_llm"
        data.setdefault("meta", {}).setdefault("source", {"kind": "llm", "prompt": prompt[:500]})
        try:
            sp = SceneProtocol.model_validate(data)
            return sp.model_dump(mode="json", exclude_none=True), log
        except Exception as exc:          # noqa: BLE001
            msg = _errors(exc)
            log.append(msg)
            if attempt >= tries:
                raise PlannerError(f"模型给的场景 {tries + 1} 次都没通过校验：{msg}") from exc
            data = _llm_json(db, _system_generate(),
                             f"{user}\n\n你上一次给的 JSON：\n{json.dumps(data, ensure_ascii=False)[:12000]}\n\n"
                             f"校验错误：\n{msg}\n\n改好后输出完整的 JSON。", model=model)
    raise PlannerError("不可达")


SYSTEM_EDIT = """你改一份 Ainer Scene Protocol v1 场景。只输出 {"say": "一句话说明改了什么", "patch": [JSON Patch 操作…]}。
patch 是 RFC 6902：{"op": "replace"|"add"|"remove", "path": "/actors/0/spawn/position", "value": …}，
数组末尾追加用 "-"（如 "/timeline/-"）。只改要求的部分，别动其它。动作名、运镜名只能用目录里的。
{CATALOG}"""


def edit_patch(db: Session, protocol: dict[str, Any], instruction: str, *, model: str | None = None) -> tuple[list[dict[str, Any]], str]:
    """修改指令 → JSON Patch（已验证打得上、打完合法）。返回 (patch, 说明)。"""
    system = SYSTEM_EDIT.replace("{CATALOG}", _catalog_text())
    user = f"当前场景：\n{json.dumps(protocol, ensure_ascii=False)[:24000]}\n\n修改要求：{instruction.strip()}"
    tries = int(config.load("director").get("planner_max_repairs") or 2)
    data = _llm_json(db, system, user, model=model, temperature=0.2)
    for attempt in range(tries + 1):
        ops = data.get("patch") or []
        try:
            new = jpatch.apply(protocol, ops)
            SceneProtocol.model_validate(new)
            return ops, str(data.get("say") or "")
        except Exception as exc:          # noqa: BLE001
            if attempt >= tries:
                raise PlannerError(f"模型给的 patch 打不上：{_errors(exc)}") from exc
            data = _llm_json(db, system, f"{user}\n\n你上一次的 patch：{json.dumps(ops, ensure_ascii=False)[:6000]}\n"
                                         f"错误：{_errors(exc)}\n改好后重新输出。", model=model, temperature=0.2)
    raise PlannerError("不可达")


# ── 成片提示词 ──────────────────────────────────────────────

_ACTION_EN = {
    "right_punch": "throws a right punch", "left_punch": "throws a left punch", "front_kick": "front-kicks",
    "dodge_left": "dodges to the side", "dodge_right": "dodges to the side", "block_high": "blocks high",
    "hit_react_back": "staggers back from the hit", "hit_react_left": "reels sideways from the hit",
    "fall_backward": "falls backward onto the ground", "stand_up": "gets back up", "look_back": "looks back over the shoulder",
    "turn_left": "turns", "turn_right": "turns", "turn_to": "turns to face", "idle": "stands still",
}
_CAM_EN = {"side_follow": "side tracking shot", "follow": "tracking shot from behind", "follow_back": "tracking shot from behind",
           "follow_front": "leading shot in front of the subject", "orbit": "orbiting shot", "orbit_left": "orbiting shot",
           "orbit_right": "orbiting shot", "push_in": "slow push-in", "dolly_in": "dolly-in", "pull_out": "pull-out",
           "dolly_out": "dolly-out", "crane_up": "crane shot rising", "crane_down": "crane shot descending",
           "static": "static shot", "handheld": "handheld shot", "drone": "drone shot"}
_BODY_EN = {"male": "a man", "female": "a woman", "teen": "a teenager", "child": "a child", "muscular": "a muscular man",
            "slim": "a slim person", "broad": "a heavyset man", "elder": "an elderly person", "chibi": "a small cartoonish figure"}
_TIME_EN = {"night": "at night", "dusk": "at dusk", "dawn": "at dawn", "day": "in daylight"}


def template_prompt(protocol: dict[str, Any], extra: str = "") -> dict[str, str]:
    """不用 LLM 也能出的提示词：人（外观）、动作（按时间顺序）、环境、运镜。"""
    actors = {a["id"]: a for a in protocol.get("actors") or []}

    def who(aid: str | None) -> str:
        a = actors.get(aid or "")
        if not a:
            return "someone"
        look = (a.get("appearance") or {}).get("look")
        if look:
            return f"the {look}"
        body = str(a.get("model_ref", "mannequin/male")).split("/")[-1]
        return _BODY_EN.get(body, "a person").replace("a ", "the ", 1)

    beats = []
    for op in as_items(protocol, "timeline"):
        if op["op"] == "actor.play_action" and op.get("action") in _ACTION_EN:
            tgt = f" at {who(op.get('target_actor'))}" if op.get("target_actor") and "punch" in op["action"] else (
                f" {who(op.get('target_actor'))}" if op.get("target_actor") else "")
            beats.append(f"{who(op['actor'])} {_ACTION_EN[op['action']]}{tgt}")
        elif op["op"] in ("actor.move_to", "actor.move_along") and op.get("actor") in actors:
            beats.append(f"{who(op['actor'])} {'runs' if op.get('gait') == 'run' else 'walks'} forward")
    cams = [op.get("preset") or op.get("style") for op in protocol.get("timeline") or [] if op["op"] in ("camera.move", "camera.follow")]
    env = protocol.get("environment") or {}
    place = {"asphalt": "on an asphalt street", "grass": "on a grassy field", "floor": "indoors", "stone": "on a stone plaza",
             "sand": "on sand", "snow": "in the snow", "dirt": "on a dirt road"}.get(env.get("ground", ""), "")
    weather = {"rain": "in the rain", "fog": "in fog", "snow": "in falling snow"}.get(env.get("weather", ""), "")
    people = ", ".join(sorted({who(a) for a in actors})) if actors else ""
    parts = [extra.strip(), f"Cinematic {_CAM_EN.get(cams[0], 'shot') if cams else 'shot'} {place} {_TIME_EN.get(env.get('time_of_day', ''), '')} {weather}".strip(),
             ("; ".join(beats) + ".") if beats else "", "Realistic people, realistic motion, film grain."]
    subject = f"Replace the grey mannequins with {people}." if people else ""
    return {"prompt": " ".join(p for p in parts if p).replace("  ", " ")[:1800], "subject": subject}


SYSTEM_PROMPT = """你给视频模型写英文提示词。输入是一份预演场景（人物、动作时间线、环境、运镜）和导演的补充要求。
输出 {"prompt": "…", "subject": "…"}：
  prompt：一段英文，写成片画面：环境与光线、每个人的外观（按 appearance.look，没有就按体型合理设定）、
          按时间顺序发生的动作、运镜方式、画风。不超过 120 个词。不要提 mannequin、3D、previs。
  subject：一句英文祈使句，告诉图像编辑模型把首帧里的灰色人偶换成谁（例如 "Replace the grey mannequin on the left with …"）。"""


def render_prompt(db: Session, protocol: dict[str, Any], extra: str = "", *, use_llm: bool = True) -> dict[str, str]:
    base = template_prompt(protocol, extra)
    if not use_llm:
        return base
    try:
        slim = {k: protocol.get(k) for k in ("meta", "environment", "actors", "timeline")}
        data = _llm_json(db, SYSTEM_PROMPT, f"场景：{json.dumps(slim, ensure_ascii=False)[:12000]}\n导演补充：{extra or '（无）'}",
                         temperature=0.5)
        p = str(data.get("prompt") or "").strip()
        if len(p) > 20:
            return {"prompt": p[:1800], "subject": str(data.get("subject") or base["subject"])[:600], "by": "llm"}
    except Exception:            # noqa: BLE001 —— LLM 不可用就用模板，不挡成片
        pass
    return {**base, "by": "template"}
