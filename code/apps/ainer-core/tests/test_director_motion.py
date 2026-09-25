"""动作库与烘焙：3D-BOX 预览和 Blender 渲染读的是同一份逐帧数据，这里钉住它的形态。"""
from __future__ import annotations

import os
import shutil

import pytest

from app.scene3d.runner import bake_scene, catalog, compile_scene

pytestmark = pytest.mark.skipif(not (shutil.which("node") or os.path.exists("/opt/homebrew/bin/node")),
                                reason="这台机器上没有 node")

FIGHT = """
S.setup({ duration: 6 });
const A = S.character("A", { body: "male", at: [0, -6], facing: [0, 1] });
const B = S.character("B", { body: "muscular", at: [0, 1], facing: [0, -6] });
S.moveTo(A, [0, 0], { t: 0, action: "run" });
S.action(A, "right_punch", { t: 1.5, target: B });
S.action(B, "dodge_left", { t: 1.6 });
S.action(A, "hit_react_back", { t: 2.75 });
S.action(A, "fall_backward", { t: 3.4 });
S.action(A, "stand_up", { t: 5 });
const cam = S.camera("c", { lens: 35 });
S.cameraPreset(cam, "side_follow", { target: A, start: 0, duration: 6 });
"""


def _bake():
    r = compile_scene(FIGHT)
    assert r["ok"], r["errors"]
    return r, bake_scene(r["doc"])


def _chan(b, who, frame):
    ch = b["rigChannels"]
    n = len(ch)
    return dict(zip(ch, b["rigs"][who][frame * n:(frame + 1) * n]))


def test_the_catalog_lists_the_v1_motions_and_camera_moves():
    cat = catalog()
    motions = {m["id"] for m in cat["motions"]}
    assert {"idle", "walk_forward", "run_forward", "turn_left", "turn_right", "look_back", "right_punch", "left_punch",
            "front_kick", "dodge_left", "dodge_right", "block_high", "hit_react_back", "hit_react_left",
            "fall_backward", "stand_up"} <= motions
    cams = {p["id"] for p in cat["cameraPresets"]}
    assert {"static", "follow", "side_follow", "dolly_in", "dolly_out", "orbit_left", "orbit_right", "crane_up", "crane_down"} <= cams


def test_frames_are_8n_plus_1_for_the_video_model():
    """6 秒 @24fps → 145 帧：视频模型要 8n+1，少一帧多一帧都会被裁。"""
    _, b = _bake()
    assert b["frames"] == 145 and (b["frames"] - 1) % 8 == 0
    assert len(b["rigChannels"]) == 39
    assert len(b["rigs"]["A"]) == 145 * 39


def test_run_then_punch_then_knocked_down_then_up():
    _, b = _bake()
    fps = b["fps"]
    a_pos = lambda f: b["anim"]["A"][f * 9:f * 9 + 3]  # noqa: E731
    assert a_pos(0)[2] == -6 and abs(a_pos(int(1.4 * fps))[2]) < 1e-6          # 跑到位
    punch = _chan(b, "A", int(1.8 * fps))
    assert punch["rSh.x"] < -60 and punch["spine.y"] > 15                       # 右拳打出去：右肩前抬、上身左拧
    assert abs(_chan(b, "A", int(4.8 * fps))["root.x"] + 90) < 1e-6             # 倒地后躺着
    assert _chan(b, "A", int(4.8 * fps))["rootY"] > 0                           # 躺着要抬离地面半个身位
    up = _chan(b, "A", 144)
    assert abs(up["root.x"]) < 1e-6                                             # 起身后站直
    assert up["offset.z"] < -1.4                                                # 被打退＋倒地的位移留着


def test_dodge_moves_the_defender_to_his_left_and_stays():
    _, b = _bake()
    before, after = _chan(b, "B", int(1.5 * 24)), _chan(b, "B", int(2.4 * 24))
    assert before["offset.x"] == 0 and abs(after["offset.x"] - 0.6) < 1e-6      # +X 是他的左手


def test_the_semantic_timeline_is_recorded_for_the_protocol():
    r, _ = _bake()
    ops = [(o["op"], o["t"]) for o in r["doc"]["timeline"]]
    assert ("actor.move_to", 0) in ops and ("camera.move", 0) in ops
    assert [o["action"] for o in r["doc"]["timeline"] if o["op"] == "actor.play_action"] == \
        ["right_punch", "dodge_left", "hit_react_back", "fall_backward", "stand_up"]


@pytest.mark.parametrize("js, msg", [
    ('const a = S.character("a"); S.action(a, "uppercut");', "right_punch"),
    ('const a = S.add("tree"); S.action(a, "right_punch");', "不是人物"),
    ('const a = S.character("a"); S.action(a, "right_punch", { target: a });', "不能是自己"),
])
def test_bad_actions_explain_themselves(js, msg):
    """智能体写错动作要能自己改：报错带最接近的名字、说清楚错在哪。"""
    r = compile_scene(js)
    assert not r["ok"] and msg in r["errors"][0]["message"]


def test_move_to_chains_segments_with_pauses():
    """两段 moveTo 中间停 1 秒：多段轨迹不能整段缓动，否则停顿被吃掉。"""
    r = compile_scene('const a = S.character("a", { at: [0, 0] });\n'
                      'S.moveTo(a, [0, 4], { t: 0, duration: 2 });\nS.moveTo(a, [4, 4], { t: 3, duration: 2 });')
    b = bake_scene(r["doc"])
    z = lambda f: b["anim"]["a"][f * 9 + 2]  # noqa: E731
    x = lambda f: b["anim"]["a"][f * 9]  # noqa: E731
    assert abs(z(48) - 4) < 1e-6 and abs(z(60) - 4) < 1e-6 and abs(x(60)) < 1e-6   # 2–3 秒停着
    assert abs(x(120) - 4) < 1e-6


def test_bake_can_lock_one_camera():
    r, _ = _bake()
    b = bake_scene(r["doc"], camera="c", frames=9)
    assert b["frames"] == 9 and set(b["camera"]["ids"]) == {"c"}
    with pytest.raises(Exception):
        bake_scene(r["doc"], camera="nope")
