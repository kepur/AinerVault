"""舞台编译 (SceneStage -> SceneProtocol) 与状态推演 (state_at) 自动化测试。"""
from __future__ import annotations

import pytest

from app.director.protocol import SceneProtocol
from app.stage.compile import compile_stage_to_protocol, state_at
from app.stage.schema import CameraSpec, CoverageShot, Landmark, SceneStage


def _sample_stage() -> SceneStage:
    return SceneStage.model_validate({
        "scene_id": "ski_slope_01",
        "set": {
            "preset": "ski_slope",
            "size_m": [80.0, 40.0],
            "landmarks": [
                {"id": "finish_line", "pos": [0.0, 30.0], "label": "终点线"},
                {"id": "pine_tree", "pos": [-5.0, 15.0], "label": "松树"},
            ],
        },
        "cast": [
            {"actor": "p1", "card": "e:brad_miller", "start": [0.0, 0.0], "facing_deg": 0.0},
            {"actor": "p2", "card": "e:coach", "start": [2.0, 0.0], "facing_deg": 180.0},
        ],
        "props": [
            {"id": "skis_p1", "card": "p:skis", "holder": "p1", "slot": "feet"},
        ],
        "beats": [
            {
                "t": [0.0, 3.0],
                "text": "李爽滑雪冲刺下坡",
                "do": [
                    {"actor": "p1", "op": "ski_downhill", "target": [0.0, 12.0], "speed": "ski"},
                ],
                "effects": [
                    {"kind": "snow_spray", "on": "p1", "where": "skis"},
                ],
            },
            {
                "t": [3.0, 4.5],
                "text": "李爽失衡扑倒在雪地里",
                "do": [
                    {"actor": "p1", "op": "fall"},
                ],
                "effects": [
                    {"kind": "snow_spray", "on": "p1"},
                ],
            },
            {
                "t": [4.5, 6.0],
                "text": "李爽在雪地里仰面释怀大笑",
                "do": [
                    {"actor": "p1", "op": "laugh"},
                ],
            },
        ],
        "axis": {"a": "p1", "b": "p2"},
    })


def test_state_at_interpolation_and_posture_evolution():
    stage = _sample_stage()

    # t=0: 开场状态
    s0 = state_at(stage, 0.0)
    assert s0["t"] == 0.0
    assert s0["actors"]["p1"]["pos"] == [0.0, 0.0]
    assert s0["actors"]["p1"]["posture"] == "standing"

    # t=1.5: 正在滑行中途 (0.0 -> 12.0 插值)
    s15 = state_at(stage, 1.5)
    assert s15["actors"]["p1"]["pos"][0] == 0.0
    assert 5.0 <= s15["actors"]["p1"]["pos"][1] <= 7.0
    assert "snow_spray" in s15["actors"]["p1"]["effects"]

    # t=3.0: 到达滑行终点
    s30 = state_at(stage, 3.0)
    assert s30["actors"]["p1"]["pos"] == [0.0, 12.0]

    # t=4.5: 摔倒之后姿态变为 lying
    s45 = state_at(stage, 4.5)
    assert s45["actors"]["p1"]["posture"] == "lying"


def test_compile_stage_to_valid_scene_protocol():
    stage = _sample_stage()
    shots = [
        CoverageShot.model_validate({
            "shot_id": "shot_01",
            "order_no": 1,
            "window": [0.0, 3.0],
            "size": "ws",
            "camera": {"setup": "tracking", "move": "track", "lens_mm": 28.0, "height": "eye", "on": "p1"},
            "focus": "p1",
        }),
        CoverageShot.model_validate({
            "shot_id": "shot_02",
            "order_no": 2,
            "window": [3.0, 4.5],
            "size": "cu",
            "camera": {"setup": "low_angle", "move": "pan", "lens_mm": 50.0, "height": "low", "on": "p1"},
            "focus": "p1",
            "transition_in": "match_action",
        }),
        CoverageShot.model_validate({
            "shot_id": "shot_03",
            "order_no": 3,
            "window": [4.5, 6.0],
            "size": "ms",
            "camera": {"setup": "single", "move": "pull_out", "lens_mm": 35.0, "height": "eye", "on": "p1"},
            "focus": "p1",
        }),
    ]

    proto = compile_stage_to_protocol(stage, shots, title="滑雪测试场景")

    # 1. 符合 SceneProtocol 数据契约
    sp = SceneProtocol.model_validate(proto)
    assert sp.meta.duration_sec >= 6.0
    assert sp.meta.fps == 24
    assert sp.environment.ground == "snow"

    # 2. 演员与初始站位 (Y 向上，平面第二轴转到 Z)
    assert len(sp.actors) == 2
    p1 = next(a for a in sp.actors if a.id == "p1")
    assert p1.spawn.position == (0.0, 0.0, 0.0)
    assert p1.character_ref == "e:brad_miller"

    # 3. 摄影机与多机位切换
    assert len(sp.cameras) == 3
    cam1 = next(c for c in sp.cameras if c.id == "cam_01")
    assert len(cam1.keys) == 2
    assert cam1.keys[0].t == 0.0
    assert cam1.keys[1].t == 3.0
    assert cam1.lens_mm == 28.0

    # 4. 时间线指令包含运镜、切镜与表演动作
    ops = [op.op for op in sp.timeline]
    assert "camera.cut" in ops
    assert "camera.move" in ops
    assert "actor.move_to" in ops
    assert "actor.play_action" in ops


def test_auto_frame_preserves_motion_and_movement_keys(monkeypatch):
    from types import SimpleNamespace
    from app.director import blender_adapter, from_shot, store
    from app.scene3d import runner

    proto = {
        "protocol": "ainer.scene/v1",
        "scene_id": "test_sc_01",
        "meta": {"title": "test", "fps": 24, "duration_sec": 3.0},
        "environment": {"ground": "snow"},
        "actors": [
            {"id": "p1", "name": "Brad", "type": "human", "character_ref": "e:brad_01",
             "spawn": {"position": [0, 0, 0], "rotation": [0, 0, 0], "scale": [1, 1, 1]}}
        ],
        "props": [],
        "cameras": [
            {"id": "cam_01", "name": "cam", "lens_mm": 35.0,
             "keys": [{"t": 0, "position": [0, 1.5, 6], "look_at": [0, 1.2, 0]},
                      {"t": 3, "position": [0, 1.5, 3], "look_at": [0, 1.2, 0]}]}
        ],
        "timeline": [
            {"op": "camera.move", "time": 0, "camera": "cam_01", "preset": "push_in", "duration": 3.0}
        ],
    }

    class DummyScene:
        id = "dummy_01"
        protocol_json = dict(proto)

    scene = DummyScene()

    # Mock bake_scene and store.scene_doc
    monkeypatch.setattr(store, "scene_doc", lambda db, s: {"objects": []})
    monkeypatch.setattr(runner, "bake_scene", lambda doc, fps=24, camera=None: {"objects": []})

    # Mock probe to return a best candidate
    monkeypatch.setattr(
        blender_adapter, "probe",
        lambda **kw: {
            "planner": {"coverage": {"p1": 0.001}},  # coverage too low, triggering candidate adoption
            "best": {"name": "probe_candidate", "position": [0, 1.6, 5.0], "look_at": [0, 1.2, 0.0],
                     "lens_mm": 35.0, "coverage": {"p1": 0.20}},
        }
    )

    patched_ops = []
    def fake_patch(db, sc, ops, by=None):
        nonlocal patched_ops
        patched_ops = ops
        # apply to scene.protocol_json
        for op in ops:
            if op["op"] == "replace" and op["path"] == "/cameras/0/keys":
                sc.protocol_json["cameras"][0]["keys"] = op["value"]

    monkeypatch.setattr(store, "patch_scene", fake_patch)

    res = from_shot.auto_frame(None, scene, duration=3.0, shot_size="ms", focus_entity="brad_01")
    assert res["motion_preserved"] is True
    assert res["camera"] == "probe_candidate"

    # 验证新机位的关键帧首尾绝非静止，保留了向前的位移
    keys = scene.protocol_json["cameras"][0]["keys"]
    assert len(keys) == 2
    assert keys[0]["position"] != keys[1]["position"]
    # 终点比起点更靠近 look_at (Z 更小)
    assert keys[1]["position"][2] < keys[0]["position"][2]


def test_stage_api_compile_and_state_at():
    from app.api.v2.stage import compile_stage, get_state_at

    stage_data = _sample_stage().model_dump()
    req_compile = {
        "stage": stage_data,
        "shots": [
            {
                "shot_id": "s1",
                "order_no": 1,
                "window": [0.0, 3.0],
                "size": "ws",
                "camera": {"setup": "tracking", "move": "track", "on": "p1"},
                "focus": "p1",
            }
        ],
        "fps": 24,
    }

    res = compile_stage(req_compile)
    assert res["ok"] is True
    assert "protocol" in res
    assert res["protocol"]["meta"]["fps"] == 24
    assert len(res["protocol"]["cameras"]) == 1

    req_state = {"stage": stage_data, "t": 1.5}
    res_s = get_state_at(req_state)
    assert res_s["ok"] is True
    assert "actors" in res_s["state"]
    assert res_s["state"]["t"] == 1.5

