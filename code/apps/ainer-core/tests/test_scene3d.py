"""3D-BOX：场景脚本沙箱、模板、智能体的工具与循环。

脚本多半是 LLM 写的：沙箱要挡住逃逸、掐掉死循环，报错要带行号（智能体靠它自己修）。
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from app.scene3d import agent, service
from app.scene3d.runner import catalog, compile_scene
from app.scene3d.templates import TEMPLATES

pytestmark = pytest.mark.skipif(
    not __import__("shutil").which("node") and not __import__("os").path.exists("/opt/homebrew/bin/node"),
    reason="这台机器上没有 node")


# ── 沙箱 ────────────────────────────────────────────────

@pytest.mark.parametrize("js", [
    'S.constructor.constructor("return process")()',
    'globalThis.constructor.constructor("return process")()',
    'eval("1+1")',
    'new Function("return 1")()',
])
def test_code_generation_is_blocked(js):
    """经典的 vm 逃逸都要走 Function 构造器 —— 沙箱里从字符串生成代码一律禁止。"""
    r = compile_scene(js)
    assert not r["ok"] and "Code generation from strings disallowed" in r["errors"][0]["message"]


def test_no_node_globals():
    for js in ('require("fs")', "process.exit(1)"):
        r = compile_scene(js)
        assert not r["ok"] and "is not defined" in r["errors"][0]["message"]


def test_infinite_loops_are_cut():
    for js in ("while (true) {}", "const f = () => Promise.resolve().then(f); f();"):
        r = compile_scene(js, timeout_ms=800)
        assert not r["ok"] and "超时" in r["errors"][0]["message"]


def test_errors_point_at_the_script_line():
    """智能体靠行号用 x_edit 修 —— 行号错一行，它就改错地方。"""
    r = compile_scene('S.add("house");\nS.add("tree");\nS.move("不存在", [{t:0, at:[0,0]}]);')
    assert r["errors"][0]["line"] == 3
    assert "找不到物体「不存在」" in r["errors"][0]["message"]


def test_a_misspelled_prefab_gets_a_suggestion():
    r = compile_scene('S.add("hose", {at: [0, 0]})')
    assert "house" in r["errors"][0]["message"]


def test_same_script_same_scene():
    """Math.random 是按 seed 可复现的：导演看到的场景不能每次刷新都变。"""
    js = 'for (let i = 0; i < 5; i++) S.add("tree", {at: [Math.random() * 20, S.rand(-5, 5)]});'
    a, b = compile_scene(js), compile_scene(js)
    assert [o["transform"]["pos"] for o in a["doc"]["objects"]] == [o["transform"]["pos"] for o in b["doc"]["objects"]]
    c = compile_scene(js, seed=2)
    assert [o["transform"]["pos"] for o in a["doc"]["objects"]] != [o["transform"]["pos"] for o in c["doc"]["objects"]]


def test_every_template_compiles_cleanly():
    for key, t in TEMPLATES.items():
        r = compile_scene(t["script"])
        assert r["ok"], (key, r["errors"])
        assert not r["warnings"], (key, r["warnings"])
        assert r["doc"]["cameras"], key


def test_catalog_covers_the_libtv_lists():
    cat = catalog()
    names = {p["name"] for p in cat["prefabs"]}
    assert {"house", "building", "car", "police_car", "tree", "bridge", "boat", "streetlamp", "bench", "table"} <= names
    presets = {p["id"] for p in cat["cameraPresets"]}
    # LibTV 导演台 24 个里的代表＋运镜广场的
    assert {"follow_back", "follow_back_close", "follow_front", "follow_side_push", "front_to_back", "top_to_follow",
            "extreme_wide_to_close", "orbit_twice", "spiral_up", "spiral_down", "dolly_zoom", "drone", "aerial_high",
            "roll", "first_person", "whip_pan"} <= presets
    assert {b["name"] for b in cat["bodies"]} >= {"male", "female", "child", "teen", "chibi", "slim", "muscular", "broad"}


def test_camera_presets_follow_a_target_added_later():
    """预设在脚本跑完后才展开：先写机位、后写车的动画，跟拍照样跟得上。"""
    js = """
const cam = S.camera("跟车");
const car = S.add("car", {name: "车", at: [0, 0]});
S.cameraPreset(cam, "follow_back", {target: car, start: 0, duration: 4});
S.moveAlong(car, {path: [[0, 0], [0, -40]], duration: 4});
"""
    r = compile_scene(js)
    keys = r["doc"]["cameras"][0]["keys"]
    assert r["ok"] and all(k.get("follow") == "车" for k in keys)


def test_overrides_survive_a_rerun():
    js = 'const h = S.add("house", {name: "张家", at: [0, 0]});\nconst c = S.camera("机位");\nS.cameraKeys(c, [{t:0, at:[0,2,10], look: h}]);'
    ov = {"objects": {"张家": {"pos": [5, 0, -3]}}, "cameras": {"机位": {"keys": [{"t": 0, "at": [1, 1, 1]}]}}}
    r = compile_scene(js, overrides=ov)
    assert r["doc"]["objects"][0]["transform"]["pos"] == [5, 0, -3]
    assert r["doc"]["cameras"][0]["keys"] == [{"t": 0, "at": [1, 1, 1]}]
    stale = compile_scene(js, overrides={"objects": {"李家": {"pos": [1, 0, 1]}}})
    assert any("李家" in w for w in stale["warnings"])


# ── 智能体：工具 ────────────────────────────────────────

def _project(script: str = TEMPLATES["blank"]["script"]):
    p = SimpleNamespace(id="sc_test", title="测试", files_json={"scene.js": script, "notes.md": ""},
                        overrides_json={}, versions_json=[], seed=1, compiled_json=None, diagnostics_json=None)
    service.compile_project(p)
    return p


def test_x_write_compiles_and_reports():
    p = _project()
    text, changed, ok = agent.execute(None, p, "x_write", {"path": "scene.js", "content": 'S.add("house", {name: "屋"})'})
    assert changed and ok and "编译通过" in text and "house" in text
    assert p.versions_json and p.versions_json[-1]["by"] == "agent"


def test_x_edit_needs_an_exact_unique_match():
    p = _project('S.add("tree", {at: [0, 0]});\nS.add("tree", {at: [0, 0]});\n')
    text, _, ok = agent.execute(None, p, "x_edit", {"path": "scene.js", "old": 'S.add("tree", {at: [0, 0]});', "new": "x"})
    assert not ok and "出现了 2 次" in text
    text, _, ok = agent.execute(None, p, "x_edit", {"path": "scene.js", "old": "S.add('tree')", "new": "x"})
    assert not ok and "找不到" in text


def test_set_object_moves_one_instance_without_touching_the_script():
    p = _project('S.row("tree", {from: [0, 0], to: [10, 0], count: 3});')
    before = dict(p.files_json)
    tree = p.compiled_json["objects"][1]["id"]
    text, changed, ok = agent.execute(None, p, "set_object", {"id": tree, "pos": [3, 0, 7]})
    assert ok and changed and p.files_json == before
    assert next(o for o in p.compiled_json["objects"] if o["id"] == tree)["transform"]["pos"] == [3, 0, 7]


def test_unknown_tool_is_reported_not_crashed():
    text, _, ok = agent.execute(None, _project(), "rm_rf", {})
    assert not ok and "没有工具" in text


# ── 智能体：循环（假模型）────────────────────────────────

class _FakeQuery:
    def filter(self, *a, **k): return self
    def order_by(self, *a, **k): return self
    def limit(self, *a, **k): return self
    def all(self): return []


class _FakeDB:
    def __init__(self, p): self.p, self.added = p, []
    def get(self, model, key): return self.p if key == self.p.id else None
    def add(self, x): self.added.append(x)
    def commit(self): pass
    def rollback(self): pass
    def close(self): pass
    def query(self, *a): return _FakeQuery()


def test_the_loop_fixes_its_own_error(monkeypatch):
    """写错 → 看到带行号的报错 → x_edit 修好 → 收尾。这是智能体最基本的自愈回路。"""
    p = _project()
    db = _FakeDB(p)
    monkeypatch.setattr(agent, "SessionLocal", lambda: db)
    seen: list[str] = []
    replies = iter([
        {"say": "先搭一个版本", "actions": [{"tool": "x_write", "args": {"path": "scene.js",
            "content": 'S.add("hose", {at: [0, 0]});\nconst c = S.camera("全景");\nS.cameraKeys(c, [{t: 0, at: [0, 3, 12], look: [0, 1, 0]}]);'}}], "done": False},
        {"say": "预制件名写错了，改掉", "actions": [{"tool": "x_edit", "args": {"path": "scene.js", "old": '"hose"', "new": '"house"'}}], "done": False},
        {"say": "好了：一栋民居，一台全景机位。", "actions": [], "done": True},
    ])

    def fake_llm(_db, messages, _model):
        seen.append(messages[-1]["content"])
        return next(replies)

    run = agent.start_run(p.id, "搭一个民居", llm=fake_llm)
    for _ in range(100):
        if run.status != "running":
            break
        time.sleep(0.05)
    assert run.status == "done", run.events
    assert "第 1 行" in seen[1] and "hose" in seen[1]          # 第二轮看到了带行号的报错
    assert p.diagnostics_json["ok"] and '"house"' in p.files_json["scene.js"]
    kinds = [e["type"] for e in run.events]
    assert kinds.count("tool") == 2 and "scene" in kinds and kinds[-1] == "done"
    assert any(e["type"] == "say" and e.get("final") for e in run.events)
    roles = [m.role for m in db.added]
    assert roles[0] == "user" and roles.count("tool") == 2 and "assistant" in roles


def test_one_run_at_a_time(monkeypatch):
    p = _project()
    monkeypatch.setattr(agent, "SessionLocal", lambda: _FakeDB(p))

    def slow(_db, _m, _model):
        time.sleep(0.4)
        return {"actions": [], "done": True, "say": "ok"}

    first = agent.start_run(p.id, "a", llm=slow)
    with pytest.raises(agent.AgentError):
        agent.start_run(p.id, "b", llm=slow)
    for _ in range(40):
        if first.status != "running":
            break
        time.sleep(0.05)


def test_view_shot_reports_what_the_camera_sees():
    """智能体看不到画面，改完机位靠这份报告确认：谁在画面里、多大、有没有被挡。"""
    p = _project("""
const cop = S.add("police_car", {name: "警车", at: [0, 0]});
S.add("truck", {name: "货车", at: [0, 6]});
const c = S.camera("正面", {lens: 35});
S.cameraKeys(c, [{t: 0, at: [0, 1.2, 14], look: cop}]);
""")
    text, _, ok = agent.execute(None, p, "view_shot", {"camera": "正面", "t": 0})
    assert ok and "警车" in text and "被挡住：货车" in text


def test_a_repeated_action_ends_the_run_instead_of_burning_every_step(monkeypatch):
    """实测：同一个 set_camera 连发 14 遍直到步数用完。连发三遍就收尾。"""
    p = _project(TEMPLATES["dialogue2"]["script"])
    monkeypatch.setattr(agent, "SessionLocal", lambda: _FakeDB(p))
    calls = {"n": 0}
    same = {"say": "改好了", "actions": [{"tool": "set_camera", "args": {"id": "双人中景", "keys": [{"t": 0, "at": [0, 1.5, 5], "look": [0, 1.3, 0]}]}}], "done": False}

    def looping(_db, _m, _model):
        calls["n"] += 1
        return same

    run = agent.start_run(p.id, "双人中景拉远一点", llm=looping)
    for _ in range(200):
        if run.status != "running":
            break
        time.sleep(0.05)
    assert run.status == "done" and calls["n"] <= 4
    assert any(e["type"] == "say" and e.get("final") for e in run.events)
