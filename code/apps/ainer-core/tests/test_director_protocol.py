"""Ainer Scene Protocol v1：校验、JSON Schema、JSON Patch、与 3D-BOX 场景互转、成片提示词模板。"""
from __future__ import annotations

import copy
import os
import shutil

import pytest

from app.director import patch as jpatch
from app.director.planner import EXAMPLE, template_prompt
from app.director.protocol import SceneProtocol, json_schema

HAS_NODE = bool(shutil.which("node") or os.path.exists("/opt/homebrew/bin/node"))
needs_node = pytest.mark.skipif(not HAS_NODE, reason="这台机器上没有 node")


def _p(**over):
    d = copy.deepcopy(EXAMPLE)
    d.update(over)
    return d


# ── 校验 ────────────────────────────────────────────────

def test_the_planner_example_is_a_valid_scene():
    sp = SceneProtocol.model_validate(EXAMPLE)
    assert sp.protocol == "ainer.scene/v1"
    assert [op.op for op in sp.timeline][:2] == ["actor.move_to", "actor.play_action"]


def test_timeline_must_reference_existing_things():
    d = _p()
    d["timeline"].append({"op": "actor.play_action", "time": 1, "actor": "C", "action": "right_punch"})
    with pytest.raises(ValueError, match="没有这个人物「C」"):
        SceneProtocol.model_validate(d)


def test_unknown_actions_are_rejected_with_the_catalog():
    d = _p()
    d["timeline"][1]["action"] = "uppercut"
    with pytest.raises(ValueError, match="动作库里没有「uppercut」"):
        SceneProtocol.model_validate(d)


def test_ops_past_the_end_of_the_clip_are_rejected():
    d = _p()
    d["timeline"][-2]["time"] = 9
    with pytest.raises(ValueError, match="超出片长"):
        SceneProtocol.model_validate(d)


def test_duplicate_ids_are_rejected():
    d = _p()
    d["props"][1]["id"] = "A"
    with pytest.raises(ValueError, match="id 重复"):
        SceneProtocol.model_validate(d)


def test_render_resolution_snaps_to_multiples_of_32():
    """视频模型要 32 的倍数：给 1000×570 就落到 992×544。"""
    d = _p(render_plan={"output_resolution": [1000, 570]})
    assert SceneProtocol.model_validate(d).render_plan.output_resolution == (992, 544)


def test_json_schema_describes_the_ops():
    s = json_schema()
    assert s["title"] == "Ainer Scene Protocol v1"
    text = str(s)
    for op in ("actor.move_to", "actor.play_action", "camera.follow", "camera.move", "camera.cut"):
        assert op in text


# ── JSON Patch ──────────────────────────────────────────

def test_patch_replace_add_remove_move():
    doc = {"cameras": [{"id": "c", "lens_mm": 35}], "timeline": [{"op": "a"}, {"op": "b"}]}
    out = jpatch.apply(doc, [
        {"op": "replace", "path": "/cameras/0/lens_mm", "value": 50},
        {"op": "add", "path": "/timeline/-", "value": {"op": "c"}},
        {"op": "remove", "path": "/timeline/0"},
        {"op": "move", "from": "/timeline/0", "path": "/timeline/1"},
        {"op": "test", "path": "/cameras/0/lens_mm", "value": 50},
    ])
    assert out["cameras"][0]["lens_mm"] == 50
    assert [x["op"] for x in out["timeline"]] == ["c", "b"]
    assert doc["cameras"][0]["lens_mm"] == 35          # 原文档不动


def test_patch_failure_names_the_step_and_changes_nothing():
    doc = {"a": [1]}
    with pytest.raises(jpatch.PatchError, match="第 1 条"):
        jpatch.apply(doc, [{"op": "add", "path": "/a/-", "value": 2}, {"op": "replace", "path": "/nope/0", "value": 1}])
    assert doc == {"a": [1]}


def test_patch_pointer_escapes():
    assert jpatch.apply({"a/b": {"~k": 1}}, [{"op": "replace", "path": "/a~1b/~0k", "value": 2}]) == {"a/b": {"~k": 2}}


# ── 提示词模板（LLM 不可用时的兜底）─────────────────────────

def test_template_prompt_orders_the_beats_and_names_the_camera():
    p = template_prompt(EXAMPLE)["prompt"]
    assert p.startswith("Cinematic side tracking shot on an asphalt street at night in the rain")
    i_punch, i_kick, i_fall = p.index("right punch"), p.index("front-kicks"), p.index("falls backward")
    assert i_punch < i_kick < i_fall
    assert "lean young man, black leather jacket" in p


# ── 3D-BOX ⇄ 协议 ──────────────────────────────────────

FIGHT = """
S.setup({ duration: 6 });
S.environment({ sky: "night", ground: "asphalt", fog: 0.2 });
S.row("building", { from: [-13, -14], to: [-13, 14], count: 2, rot: 90 });
const A = S.character("A", { body: "male", at: [0, -6], facing: [0, 1] });
const B = S.character("B", { body: "muscular", at: [0, 1], facing: [0, -6] });
S.pose(B, "fight");
S.moveTo(A, [0, 0], { t: 0, action: "run" });
S.action(A, "right_punch", { t: 1.5, target: B });
S.action(B, "front_kick", { t: 2.4, target: A });
S.action(A, "fall_backward", { t: 3.4 });
const cam = S.camera("侧跟", { lens: 35 });
S.cameraPreset(cam, "side_follow", { target: A, start: 0, duration: 6 });
"""


@needs_node
def test_scene_round_trips_through_the_protocol():
    """3D-BOX 场景 → 协议 → 生成的脚本 → 再编译：人物位置、关节、机位逐帧一致（只差时长的四舍五入）。"""
    from app.director.convert import doc_to_protocol, protocol_to_script
    from app.scene3d.runner import bake_scene, compile_scene

    r = compile_scene(FIGHT)
    assert r["ok"], r["errors"]
    b = bake_scene(r["doc"])
    p = doc_to_protocol(r["doc"], scene_id="t", title="夜巷", baked=b)
    assert {a["id"] for a in p["actors"]} == {"A", "B"}
    assert [o["op"] for o in p["timeline"]].count("actor.play_action") == 3
    assert any(o["op"] == "camera.cut" and o["time"] == 0 for o in p["timeline"])
    js = protocol_to_script(p)
    r2 = compile_scene(js)
    assert r2["ok"], (r2["errors"], js)
    b2 = bake_scene(r2["doc"])

    def diff(x, y):
        return max(abs(a - c) for a, c in zip(x, y))
    assert diff(b["anim"]["A"], b2["anim"]["A"]) < 0.01
    assert diff(b["rigs"]["B"], b2["rigs"]["B"]) < 1e-6
    assert diff(b["camera"]["frames"], b2["camera"]["frames"]) < 0.01


@needs_node
def test_generated_script_uses_camera_keys_not_both_keys_and_presets():
    """机位带着最终关键帧时，时间线里的运镜指令只是记录 —— 两样都执行，关键帧就重复了。"""
    from app.director.convert import doc_to_protocol, protocol_to_script
    from app.scene3d.runner import compile_scene

    r = compile_scene(FIGHT)
    p = doc_to_protocol(r["doc"], scene_id="t", title="夜巷")
    js = protocol_to_script(p)
    assert "S.cameraKeys(" in js and "S.cameraPreset(" not in js


@needs_node
def test_json_first_scene_compiles_with_actions_and_camera_ops():
    """LLM 直接给的协议（机位没写 keys，只有 camera.move）→ 脚本里用预设运镜。"""
    from app.director.convert import protocol_to_script
    from app.scene3d.runner import compile_scene

    js = protocol_to_script(EXAMPLE)
    assert 'S.cameraPreset("cam_01", "side_follow"' in js and 'S.action("A", "right_punch"' in js
    r = compile_scene(js)
    assert r["ok"], r["errors"]
    a = next(o for o in r["doc"]["objects"] if o["id"] == "A")
    assert [x["name"] for x in a["actions"]] == ["right_punch", "hit_react_back", "fall_backward"]


def test_visibility_from_motion_json():
    """谁在第几秒入画：从 Blender 实际投影的关键点算，给写提示词的 LLM 用（开场不在画面里的人别在第一帧画出来）。"""
    from app.director.planner import visibility

    seen = [[10, 10, 1]] * 18
    unseen = [[0, 0, 0]] * 18
    motion = {"fps": 24, "actors": {
        "A": {"frames": [{"keypoints_2d": seen}] * 48},
        "B": {"frames": [{"keypoints_2d": unseen}] * 24 + [{"keypoints_2d": seen}] * 24},
        "C": {"frames": [{"keypoints_2d": unseen}] * 48},
    }}
    assert visibility(motion) == {"A": {"first": 0.0, "last": 1.96}, "B": {"first": 1.0, "last": 1.96}}
    assert visibility(None) == {}
