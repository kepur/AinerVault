"""3D-BOX 场景智能体：用对话让 LLM 写场景脚本、看诊断、自己修，直到能跑。

text.chat 没有原生工具调用，所以用 JSON 动作协议：每一轮模型只输出一个 JSON ——
{thought, say, actions:[{tool, args}], done}。我们按顺序执行动作，把结果（编译报错带行号、
警告、概要、俯视字符地图）作为下一条消息喂回去。换哪家免费模型都能跑，不依赖厂商的 tools 字段。

一次「运行」在后台线程里跑（最多 MAX_STEPS 轮），事件实时写进内存供 SSE 推送；
每一步落库（文件、编译结果、对话记录），界面刷新就能看到场景跟着变。
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.capability.router import resolve_routes
from app.capability.schemas import Capability
from app.capability.service import submit_task
from app.db import SessionLocal
from app.ids import new_id
from app.models import SceneMessage, SceneProject, TaskStatus
from app.pipelines.base import as_items
from app.scene3d import service
from app.scene3d.runner import SceneRunError, catalog, shot_reports
from app.scene3d.templates import TEMPLATES

log = logging.getLogger(__name__)

SKILLS_DIR = Path(__file__).with_name("skills")
MAX_STEPS = 14
MAX_ACTIONS = 4
PURPOSE = "scene_director"
TOOLS = ["x_list", "x_read", "x_write", "x_edit", "x_run", "skill", "prefabs",
         "camera_presets", "inspect", "view_shot", "set_object", "set_camera"]

ACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["actions", "done"],
    "properties": {
        "thought": {"type": "string", "description": "给自己的简短思考，导演看不到"},
        "say": {"type": "string", "description": "给导演看的话；做完时写总结"},
        "actions": {
            "type": "array", "maxItems": MAX_ACTIONS,
            "items": {"type": "object", "required": ["tool", "args"], "properties": {
                "tool": {"type": "string", "enum": TOOLS},
                "args": {"type": "object"},
            }},
        },
        "done": {"type": "boolean", "description": "活干完了就 true（此时 actions 为空）"},
    },
}


class AgentError(RuntimeError):
    pass


def skill_text(name: str) -> str:
    name = (name or "").strip()
    if name.startswith("example:"):
        key = name.split(":", 1)[1]
        t = TEMPLATES.get(key)
        if not t:
            return f"没有范例「{key}」。可选：{', '.join(TEMPLATES)}"
        return f"范例「{t['name']}」（{t['desc']}）：\n```js\n{t['script']}```"
    path = SKILLS_DIR / f"{name}.md"
    if not path.exists():
        return f"没有 skill「{name}」。可选：studio-director、scene-api、cinematography、example:<{'|'.join(TEMPLATES)}>"
    return path.read_text(encoding="utf-8")


def system_prompt() -> str:
    return "\n\n".join([
        "你是 3D-BOX 的预演导演智能体。你通过写场景脚本 scene.js 来搭 3D 白模场景、编排人物车辆的动作、设计机位运镜和剪辑时间表。"
        "你只能通过下面的工具操作项目，每一轮只输出一个 JSON 对象。",
        "## 回复格式（只输出一个 JSON 对象，不要围栏）\n"
        '{"thought": "给自己的简短思考", "say": "给导演看的话（可空）", "actions": [{"tool": "x_write", "args": {…}}], "done": false}\n'
        f"- 每轮最多 {MAX_ACTIONS} 个动作，按顺序执行；执行结果在下一条消息里给你。\n"
        "- 活干完了：actions 为空、done=true、say 写总结（两三句：场景里有什么、机位怎么切、还能怎么调）。\n"
        "- scene.js 的完整内容放在 x_write 的 content 里（JSON 字符串：换行写 \\n，双引号写 \\\"）。\n"
        "- say 是说给导演听的中文，别贴代码。",
        "## 工具\n"
        '- x_list {} 列出项目文件\n'
        '- x_read {"path": "scene.js"} 读文件（带行号）\n'
        '- x_write {"path": "scene.js", "content": "完整内容"} 写整个文件；写 scene.js 自动编译并返回诊断\n'
        '- x_edit {"path": "scene.js", "old": "原文（逐字一致且唯一）", "new": "新文"} 精确替换；scene.js 自动编译\n'
        '- x_run {} 重新编译，返回报错（带行号）、警告、概要、俯视字符地图\n'
        '- skill {"name": "studio-director|cinematography|scene-api|example:<模板>"} 读工作方法、镜头语言、API、范例\n'
        '- prefabs {"category": "建筑|街道|交通|自然|室内|道具|标记|动物"} 预制件目录（可省 category）\n'
        '- camera_presets {} 运镜预设目录\n'
        '- inspect {"id": "物体或机位 id"} 看某个物体/机位的详细数据\n'
        '- view_shot {"camera": "机位 id", "t": 秒} 看这台机位在这一刻拍到了什么：画面里有谁、在画面哪里、占多大、被谁挡住。'
        "你看不到画面，设计或改完机位后用它确认（t 不写就取这台机位在剪辑表里开始的时刻）\n"
        '- set_object {"id": "…", "pos": [x,y,z], "rot": [0,yaw,0], "scale": [1,1,1], "color": "#rrggbb", "hidden": false} '
        "单独改一个物体（不改脚本，用于批量摆放出来的某一个）\n"
        '- set_camera {"id": "机位 id", "keys": [关键帧…]} 直接换掉一台机位的关键帧（不改脚本）',
        skill_text("scene-api"),
        "## 工作方法（节选，完整版 skill studio-director）\n"
        "1. 新场景：先在 notes.md 写规划（片长、节拍、布局坐标、镜头表），再一次 x_write 写完整 scene.js。\n"
        "2. 看编译诊断：有报错用 x_edit 修；看俯视地图检查布局（路在哪、建筑有没有压路、人车方向对不对）。\n"
        "3. 镜头：每段 1.5–4 秒，全景交代→中景→特写；运镜有动机；同场戏机位在 180° 轴线同侧。\n"
        "4. 改场景：先弄清现状；小改 x_edit，大改 x_write；导演选中批量摆放的某个物体时用 set_object。\n"
        "5. 信息不全按常理先做一个，say 里说清你的假设。重要物体和机位都起中文名。",
    ])


# ── 运行 ────────────────────────────────────────────────

@dataclass
class AgentRun:
    id: str
    project_id: str
    status: str = "running"            # running / done / error / stopped
    events: list[dict[str, Any]] = field(default_factory=list)
    cancel: bool = False
    started: float = field(default_factory=time.time)
    cond: threading.Condition = field(default_factory=threading.Condition)

    def emit(self, type_: str, **data: Any) -> None:
        with self.cond:
            self.events.append({"seq": len(self.events) + 1, "type": type_, "at": round(time.time() - self.started, 2), **data})
            self.cond.notify_all()

    def after(self, seq: int) -> tuple[list[dict[str, Any]], bool]:
        with self.cond:
            return [e for e in self.events if e["seq"] > seq], self.status != "running"

    def wait(self, seq: int, timeout: float) -> None:
        with self.cond:
            if len(self.events) <= seq and self.status == "running":
                self.cond.wait(timeout)


RUNS: dict[str, AgentRun] = {}
_LOCK = threading.Lock()


def get_run(run_id: str) -> AgentRun | None:
    return RUNS.get(run_id)


def active_run(project_id: str) -> AgentRun | None:
    return next((r for r in RUNS.values() if r.project_id == project_id and r.status == "running"), None)


def start_run(project_id: str, message: str, *, selected: list[str] | None = None,
              sketches: list[dict[str, Any]] | None = None, model: str | None = None,
              llm: Any = None) -> AgentRun:
    """起一次运行。llm 可注入（测试用），签名 llm(db, messages, model) -> dict。"""
    with _LOCK:
        if active_run(project_id):
            raise AgentError("这个场景的智能体正在工作，等它做完或先停止")
        run = AgentRun(id=new_id("run"), project_id=project_id)
        RUNS[run.id] = run
        for rid in [r.id for r in sorted(RUNS.values(), key=lambda r: r.started)][:-60]:
            RUNS.pop(rid, None)
    t = threading.Thread(target=_loop, args=(run, message, selected or [], sketches or [], model, llm or _llm),
                         daemon=True, name=f"scene-agent-{run.id}")
    t.start()
    return run


def stop_run(run_id: str) -> bool:
    run = RUNS.get(run_id)
    if not run or run.status != "running":
        return False
    run.cancel = True
    return True


def _llm(db: Any, messages: list[dict[str, str]], model: str | None) -> dict[str, Any]:
    route = None
    if model:
        route = next((r for r in resolve_routes(db, Capability.text_chat, PURPOSE, None) if r.model == model), None)
        if route is None:
            raise AgentError(f"没有可用的模型「{model}」")
    task = submit_task(
        db, Capability.text_chat,
        {"messages": messages, "temperature": 0.4, "max_tokens": 8192,
         "response_format": {"type": "json_schema", "schema": ACTION_SCHEMA}},
        purpose=PURPOSE, sync=True, route=route, force=True, ref_kind="scene_project",
    )
    if task.status != TaskStatus.succeeded:
        err = task.error_json or {}
        raise AgentError(f"模型调用失败 [{err.get('code')}]: {err.get('message')}")
    data = (task.result_json or {}).get("json")
    if not isinstance(data, dict):
        raise AgentError("模型没有按格式返回 JSON 对象")
    return data


def _history(db: Any, project_id: str, limit: int = 8) -> str:
    rows = db.query(SceneMessage).filter(
        SceneMessage.project_id == project_id,
        SceneMessage.role.in_(["user", "assistant"]),
    ).order_by(SceneMessage.created_at.desc()).limit(limit * 3).all()
    lines: list[str] = []
    for m in reversed(rows):
        if m.role == "assistant" and not (m.meta_json or {}).get("final"):
            continue
        who = "导演" if m.role == "user" else "你"
        lines.append(f"{who}：{m.content[:600]}")
    return "\n".join(lines[-limit * 2:])


def _brief_doc(doc: dict[str, Any] | None, ids: list[str]) -> list[dict[str, Any]]:
    if not doc:
        return []
    out = []
    for i in ids:
        o = next((x for x in doc.get("objects", []) if x["id"] == i), None)
        if o:
            out.append({"id": o["id"], "name": o["name"], "kind": o["kind"], "prefab": o.get("prefab"),
                        "pos": [round(v, 2) for v in o["transform"]["pos"]], "rot": o["transform"]["rot"],
                        "size": [round(v, 2) for v in o["size"]], "animated": bool(o.get("track"))})
            continue
        c = next((x for x in doc.get("cameras", []) if x["id"] == i), None)
        if c:
            out.append({"id": c["id"], "name": c["name"], "kind": "camera", "lens": c["lens"], "keys": c["keys"][:6]})
    return out


def format_diag(r: dict[str, Any], *, with_map: bool = True) -> str:
    lines: list[str] = []
    if r.get("ok"):
        lines.append(f"✅ 编译通过（{r.get('ms', '?')}ms）")
    else:
        lines.append("❌ 编译失败：")
        for e in as_items(r, "errors"):
            lines.append(f"  第 {e.get('line')} 行：{e.get('message')}" if e.get("line") else f"  {e.get('message')}")
    for w in (r.get("warnings") or [])[:8]:
        lines.append(f"⚠ {w}")
    s = r.get("summary") or {}
    if s:
        counts = "、".join(f"{k}×{v}" for k, v in sorted((s.get("counts") or {}).items(), key=lambda kv: -kv[1])[:14])
        lines.append(f"片长 {s.get('duration')}s；物体 {s.get('objects')} 个：{counts}")
        for c in as_items(s, "characters"):
            lines.append(f"  人物 {c['id']}（{c['body']}）{c['from']} → {c['to']}" + (f" {c['action']}" if c.get("action") else ""))
        for v in as_items(s, "vehicles"):
            lines.append(f"  载具 {v['id']} {v['from']} → {v['to']}")
        for c in as_items(s, "cameras"):
            lines.append(f"  机位 {c['id']}：{c['keys']} 个关键帧，{c['span'][0]}–{c['span'][1]}s，{'/'.join(c['kinds'])}"
                         + (f"，预设 {','.join(c['presets'])}" if c.get("presets") else ""))
        if s.get("cuts"):
            lines.append("  切点：" + " → ".join(f"{c['t']}s {c['camera']}" for c in s["cuts"]))
        if with_map and s.get("map"):
            lines.append(s["map"])
    return "\n".join(lines)


def _context(p: SceneProject, selected: list[str], sketches: list[dict[str, Any]]) -> str:
    parts = [f"项目「{p.title}」。文件：" + "，".join(f"{f['path']}（{f['lines']} 行）" for f in service.list_files(p))]
    if p.diagnostics_json:
        parts.append("当前场景编译结果：\n" + format_diag(p.diagnostics_json))
    ov = p.overrides_json or {}
    if ov.get("objects") or ov.get("cameras"):
        parts.append(f"导演在台上手动改过：物体 {list((ov.get('objects') or {}).keys())[:20]}，"
                     f"机位 {list((ov.get('cameras') or {}).keys())}（这些改动叠在脚本之上）")
    if selected:
        parts.append("导演选中了：" + json.dumps(_brief_doc(p.compiled_json, selected), ensure_ascii=False))
    for i, sk in enumerate(sketches[:6]):
        pts = sk.get("points") or []
        parts.append(f"导演画的第 {i + 1} 笔（{sk.get('tool', 'pen')}，{sk.get('color', '')}，投到地面的世界坐标 [x,z]）："
                     + json.dumps([[round(x, 1), round(z, 1)] for x, z in pts[:40]]))
    return "\n\n".join(parts)


def _args_brief(tool: str, args: dict[str, Any]) -> str:
    if tool == "x_write":
        c = str(args.get("content", ""))
        return f"{args.get('path')}（{c.count(chr(10)) + 1} 行）"
    if tool == "x_edit":
        return f"{args.get('path')}：{str(args.get('old', '')).strip().splitlines()[0][:40] if str(args.get('old', '')).strip() else ''}…"
    if tool in ("x_read", "skill", "inspect", "set_object", "set_camera"):
        return str(args.get("path") or args.get("name") or args.get("id") or "")
    return json.dumps(args, ensure_ascii=False)[:80]


def execute(db: Any, p: SceneProject, tool: str, args: dict[str, Any]) -> tuple[str, bool, bool]:
    """执行一个动作。返回（给模型看的结果、场景是否变了、是否成功）。"""
    try:
        if tool == "x_list":
            return "\n".join(f"{f['path']}  {f['lines']} 行" for f in service.list_files(p)) or "（空）", False, True
        if tool == "x_read":
            text = service.read_file(p, str(args.get("path", "scene.js")))
            lines = text.splitlines()
            body = "\n".join(f"{i + 1:4d}| {ln}" for i, ln in enumerate(lines[:500]))
            return (body + ("\n…（后面还有）" if len(lines) > 500 else ""))[:24000], False, True
        if tool == "x_write":
            path = str(args.get("path", "scene.js"))
            service.write_file(p, path, str(args.get("content", "")), by="agent", note=str(args.get("note", "")))
            if path == service.ENTRY:
                r = service.compile_project(p)
                return format_diag(r), True, bool(r.get("ok"))
            return f"已写入 {path}", False, True
        if tool == "x_edit":
            path = str(args.get("path", "scene.js"))
            line = service.edit_file(p, path, str(args.get("old", "")), str(args.get("new", "")), by="agent")
            if path == service.ENTRY:
                r = service.compile_project(p)
                return f"已改第 {line} 行。\n" + format_diag(r), True, bool(r.get("ok"))
            return f"已改 {path} 第 {line} 行", False, True
        if tool == "x_run":
            r = service.compile_project(p)
            return format_diag(r), True, bool(r.get("ok"))
        if tool == "skill":
            return skill_text(str(args.get("name", "studio-director")))[:20000], False, True
        if tool == "prefabs":
            cat = catalog()
            want = str(args.get("category") or "")
            rows = []
            for pf in cat["prefabs"]:
                if want and pf["category"] != want:
                    continue
                ps = "；".join(f"{k}={v['default']}" + (f"（{'/'.join(v['options'])}）" if v.get("options") else "") + f" {v['doc']}"
                              for k, v in pf["params"].items())
                rows.append(f"{pf['name']}（{pf['zh']}，{pf['category']}）尺寸 {pf['size']}m — {pf['doc']}" + (f"｜参数：{ps}" if ps else ""))
            rows.append("人物体型：" + "、".join(f"{b['name']}（{b['zh']} {b['height']}m）" for b in cat["bodies"]))
            rows.append("姿势：" + "、".join(f"{x['name']}（{x['zh']}）" for x in cat["poses"]))
            return "\n".join(rows), False, True
        if tool == "camera_presets":
            return "\n".join(f"{c['id']}（{c['zh']}，{c['group']}）— {c['doc']}" for c in catalog()["cameraPresets"]), False, True
        if tool == "inspect":
            doc = p.compiled_json or {}
            i = str(args.get("id", ""))
            o = next((x for x in doc.get("objects", []) if x["id"] == i or x["name"] == i), None) \
                or next((x for x in doc.get("cameras", []) if x["id"] == i or x["name"] == i), None)
            if not o:
                return f"找不到「{i}」", False, False
            return json.dumps(o, ensure_ascii=False)[:6000], False, True
        if tool == "view_shot":
            doc = p.compiled_json or {}
            cams = doc.get("cameras") or []
            cid = str(args.get("camera") or args.get("id") or "")
            cam = next((c for c in cams if c["id"] == cid or c["name"] == cid), None)
            if not cam:
                return f"没有机位「{cid}」。现有：{', '.join(c['id'] for c in cams)}", False, False
            return "\n\n".join(shot_reports(doc, [{"camera": cam["id"], "t": _shot_time(doc, cam, args.get("t"))}])), False, True
        if tool == "set_object":
            doc = p.compiled_json or {}
            i = str(args.get("id", ""))
            if not any(x["id"] == i for x in doc.get("objects", [])):
                return f"找不到物体「{i}」（用 inspect 或概要里的 id）", False, False
            ov = dict(p.overrides_json or {})
            objs = dict(ov.get("objects") or {})
            cur = dict(objs.get(i) or {})
            for k in ("pos", "rot", "scale"):
                if k in args:
                    v = args[k]
                    if not (isinstance(v, list) and len(v) == 3 and all(isinstance(x, (int, float)) for x in v)):
                        return f"{k} 要写成 [x, y, z]", False, False
                    cur[k] = v
            if "color" in args:
                cur["color"] = str(args["color"])
            if "hidden" in args:
                cur["hidden"] = bool(args["hidden"])
            objs[i] = cur
            ov["objects"] = objs
            service.set_overrides(p, ov)
            r = service.compile_project(p)
            return f"已单独改了 {i}。\n" + format_diag(r, with_map=False), True, bool(r.get("ok"))
        if tool == "set_camera":
            doc = p.compiled_json or {}
            i = str(args.get("id", ""))
            if not any(x["id"] == i for x in doc.get("cameras", [])):
                return f"找不到机位「{i}」", False, False
            keys = args.get("keys")
            if not isinstance(keys, list) or not keys or not all(isinstance(k, dict) and "t" in k for k in keys):
                return "keys 要写成关键帧数组 [{t, at|follow|orbit, look, lens}]", False, False
            ov = dict(p.overrides_json or {})
            cams = dict(ov.get("cameras") or {})
            cams[i] = {**(cams.get(i) or {}), "keys": keys}
            ov["cameras"] = cams
            service.set_overrides(p, ov)
            r = service.compile_project(p)
            text = f"已换掉机位 {i} 的关键帧。\n" + format_diag(r, with_map=False)
            cam = next((c for c in (p.compiled_json or {}).get("cameras", []) if c["id"] == i), None)
            if cam and r.get("ok"):
                ts = sorted({_shot_time(p.compiled_json, cam, None), float(cam["keys"][-1]["t"])})
                text += "\n\n改完之后拍到的：\n" + "\n\n".join(shot_reports(p.compiled_json, [{"camera": i, "t": t} for t in ts]))
            return text, True, bool(r.get("ok"))
        return f"没有工具「{tool}」。可用：{', '.join(TOOLS)}", False, False
    except service.SceneFileError as exc:
        return f"失败：{exc}", False, False
    except SceneRunError as exc:
        return f"执行器出错：{exc}", False, False


def _shot_time(doc: dict[str, Any], cam: dict[str, Any], t: Any) -> float:
    """view_shot 不给时间时取这台机位在剪辑表里开始的时刻（没进剪辑表就取第一个关键帧）。"""
    if isinstance(t, (int, float)):
        return float(t)
    cuts = [c["t"] for c in (doc.get("cuts") or []) if c["camera"] == cam["id"]]
    if cuts:
        return float(min(cuts)) + 0.05
    return float(cam["keys"][0]["t"]) if cam.get("keys") else 0.0


def _signature(actions: list[dict[str, Any]]) -> str:
    return json.dumps([[a.get("tool"), a.get("args")] for a in actions], ensure_ascii=False, sort_keys=True)


def _loop(run: AgentRun, message: str, selected: list[str], sketches: list[dict[str, Any]],
          model: str | None, llm: Any) -> None:
    db = SessionLocal()
    final_said = False
    try:
        p = db.get(SceneProject, run.project_id)
        if p is None:
            raise AgentError("场景项目不存在")
        history = _history(db, p.id)
        db.add(SceneMessage(id=new_id("sm"), project_id=p.id, run_id=run.id, role="user", content=message,
                            meta_json={"selected": selected, "sketches": len(sketches), "model": model}))
        db.commit()
        first = "\n\n".join(x for x in [
            f"此前的对话：\n{history}" if history else "",
            "上下文：\n" + _context(p, selected, sketches),
            f"导演的要求：{message}",
        ] if x)
        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt()},
                                          {"role": "user", "content": first}]
        run.emit("status", text="已加载 studio-director 工作方法，开始规划")
        last_sig, repeats = "", 0
        for step in range(MAX_STEPS):
            if run.cancel:
                run.status = "stopped"
                run.emit("stopped", text="已停止")
                break
            run.emit("thinking", step=step + 1)
            try:
                out = llm(db, messages, model)
            except Exception as exc:          # noqa: BLE001 —— 模型挂了要告诉导演，不能静默
                log.exception("scene agent llm failed")
                db.rollback()
                raise AgentError(str(exc)) from exc
            say = str(out.get("say") or "").strip()
            actions = [a for a in (out.get("actions") or []) if isinstance(a, dict)][:MAX_ACTIONS]
            done = bool(out.get("done"))
            messages.append({"role": "assistant", "content": json.dumps(out, ensure_ascii=False)[:30000]})
            if say:
                run.emit("say", text=say, final=done and not actions)
                db.add(SceneMessage(id=new_id("sm"), project_id=p.id, run_id=run.id, role="assistant", content=say,
                                    meta_json={"final": done and not actions, "thought": str(out.get("thought") or "")[:500]}))
                final_said = final_said or (done and not actions)
            if not actions:
                db.commit()
                if done or step > 0:
                    break
                messages.append({"role": "user", "content": "你还没有做任何事。请用工具开始干活（通常先 x_write 写 scene.js）。"})
                continue
            sig = _signature(actions)
            repeats = repeats + 1 if sig == last_sig else 0
            last_sig = sig
            if repeats >= 2:
                # 同一组动作连发三遍：结果不会变，它在原地打转。收尾，别把步数耗完
                run.emit("say", text=say or "这一步已经改好了。", final=True)
                final_said = True
                break
            if repeats == 1:
                messages.append({"role": "user", "content":
                                 "你这一轮的动作和上一轮完全一样 —— 重复执行结果不会变。"
                                 "如果上一轮已经达到导演的要求，就 actions 为空、done=true、写总结；"
                                 "如果没达到，先用 view_shot / inspect 看清现状，换一种改法。"})
                continue
            results: list[str] = []
            any_fail = False
            for a in actions:
                tool = str(a.get("tool", ""))
                args = a.get("args") if isinstance(a.get("args"), dict) else {}
                brief = _args_brief(tool, args)
                run.emit("tool", tool=tool, brief=brief)
                text, changed, ok = execute(db, p, tool, args)
                any_fail = any_fail or not ok
                db.add(SceneMessage(id=new_id("sm"), project_id=p.id, run_id=run.id, role="tool",
                                    content=f"已执行 {tool}", meta_json={"tool": tool, "brief": brief, "ok": ok,
                                                                        "result": text[:1500]}))
                db.commit()
                run.emit("tool_result", tool=tool, ok=ok, brief=brief, result=text[:1200])
                if changed:
                    run.emit("scene", ok=bool((p.diagnostics_json or {}).get("ok")))
                results.append(f"【{tool} {brief}】\n{text}")
            if done and not any_fail:
                if not final_said:
                    run.emit("say", text=say or "场景已更新。", final=True)
                    final_said = True
                break
            messages.append({"role": "user", "content": "工具结果：\n\n" + "\n\n".join(results)
                             + ("\n\n有失败的动作，先把它修好。" if any_fail else "")})
            # 早先的工具结果压短：上下文别无限长
            _compact(messages)
        else:
            run.emit("say", text="步数用完了。场景已保存到当前进度，你可以看看再告诉我怎么继续。", final=True)
            final_said = True
        if run.status == "running":
            run.status = "done"
            if not final_said:
                run.emit("say", text="好了。", final=True)
    except Exception as exc:                  # noqa: BLE001
        run.status = "error"
        run.emit("error", text=str(exc)[:500])
        try:
            db.rollback()
            db.add(SceneMessage(id=new_id("sm"), project_id=run.project_id, run_id=run.id, role="error", content=str(exc)[:1000]))
            db.commit()
        except Exception:                     # noqa: BLE001
            log.exception("记录智能体错误失败")
    finally:
        run.emit("done", status=run.status)
        with run.cond:
            run.cond.notify_all()
        db.close()


def _compact(messages: list[dict[str, str]], budget: int = 60000) -> None:
    """总长超过预算时，把最早的工具结果换成一句话（保留 system 和第一条要求）。"""
    total = sum(len(m["content"]) for m in messages)
    i = 2
    while total > budget and i < len(messages) - 2:
        m = messages[i]
        if m["role"] == "user" and m["content"].startswith("工具结果") and len(m["content"]) > 400:
            total -= len(m["content"]) - 60
            m["content"] = "工具结果：（较早的结果已省略，以最新一次为准）"
        i += 1
