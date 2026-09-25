"""渲染器（LTX 0.9.7 启用 / LTX 2.5 预埋）、UE 预埋、功能开关、任务进度。"""
from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from app.director import config, jobs
from app.director.renderers.base import RenderRequest, RendererError
from app.director.renderers.ltx097 import LTX097Adapter
from app.director.renderers.ltx25 import LTX25Adapter
from app.director.ue_worker import adapter as ue
from app.director.ue_worker import coords
from app.director.ue_worker.remote.http_client import UERemoteHTTP
from app.director.ue_worker.remote.websocket_client import UERemoteWS, envelope
from app.director.ue_worker.translator import camera_to_sequencer


# ── 功能开关 ─────────────────────────────────────────────

def test_v1_flags_are_blender_and_ltx097_on_ue_and_ltx25_off(monkeypatch):
    for k in config.FLAGS:
        monkeypatch.delenv(f"DIRECTOR_{k.upper()}", raising=False)
    assert config.features() == {"blender_enabled": True, "ue_enabled": False, "ltx097_enabled": True, "ltx25_enabled": False}


def test_env_overrides_a_flag(monkeypatch):
    monkeypatch.setenv("DIRECTOR_UE_ENABLED", "true")
    assert config.enabled("ue_enabled")


# ── LTX 0.9.7 ────────────────────────────────────────────

def _req(**kw):
    base = {"prompt": "a fight", "control_video": "http://x/preview.mp4", "resolution": (770, 450), "duration_sec": 6}
    return RenderRequest(**{**base, **kw})


def test_ltx097_v2v_payload():
    a = LTX097Adapter()
    p = a.build_payload(a.validate(_req(first_frame="http://x/f.png")))
    assert (p["width"], p["height"]) == (768, 448)                 # 32 的倍数
    assert p["duration_ms"] == 6000 and p["first_frame"] == {"url": "http://x/f.png"}
    assert p["control"] == {"type": "v2v", "video": {"url": "http://x/preview.mp4"}, "pin_first": False, "denoise": 0.92}


def test_ltx097_iclora_payload_uses_strength_not_denoise():
    a = LTX097Adapter()
    p = a.build_payload(a.validate(_req(control_type="pose", strength=0.8)))
    assert p["control"]["type"] == "pose" and p["control"]["strength"] == 0.8 and "denoise" not in p["control"]


def test_ltx097_rejects_union_control():
    with pytest.raises(RendererError, match="union"):
        LTX097Adapter().validate(_req(control_type="union"))


def test_ltx097_refuses_a_control_type_the_workbench_cannot_run(monkeypatch):
    """没有 13B 底模时要明说，不能悄悄换成 v2v。"""
    monkeypatch.setenv("DIRECTOR_LTX097_ENABLED", "true")
    a = LTX097Adapter()
    monkeypatch.setattr(a, "control_types", lambda db=None: ["v2v"])
    with pytest.raises(RendererError, match="13B"):
        a.generate(None, _req(control_type="depth"))


def test_ltx097_flag_off(monkeypatch):
    monkeypatch.setenv("DIRECTOR_LTX097_ENABLED", "false")
    with pytest.raises(config.FeatureDisabled):
        LTX097Adapter().generate(None, _req())


# ── LTX 2.5（预埋）───────────────────────────────────────────

def test_ltx25_union_payload_and_mock():
    a = LTX25Adapter()
    req = _req(renderer="ltx_25", control_type="union", control_videos={"depth": "http://x/d.mp4", "pose": "http://x/p.mp4"})
    r = a.mock_generate(req)
    assert r.mock and r.video_url is None
    ctl = r.meta["payload"]["control"]
    assert ctl["type"] == "union" and set(ctl["videos"]) == {"depth", "pose"}
    assert ctl["strengths"] == {"depth": 0.8, "pose": 1.0}
    assert r.meta["payload"]["model_family"] == "ltx-2.5"


def test_ltx25_union_needs_a_control_video():
    with pytest.raises(RendererError, match="union control"):
        LTX25Adapter().validate(_req(control_type="union", control_videos={}))


def test_ltx25_is_off_in_v1(monkeypatch):
    monkeypatch.delenv("DIRECTOR_LTX25_ENABLED", raising=False)
    with pytest.raises(config.FeatureDisabled):
        LTX25Adapter().generate(None, _req(renderer="ltx_25"))


# ── UE（预埋）──────────────────────────────────────────────

def test_ue_axes():
    """我们 Y 上、+Z 前、+X 是人的左手；UE Z 上、+X 前、+Y 右手、厘米。"""
    assert coords.location([0, 0, 1]) == [100.0, 0.0, 0.0]
    assert coords.location([1, 0, 0]) == [0.0, -100.0, 0.0]
    assert coords.location([0, 1, 0]) == [0.0, 0.0, 100.0]
    assert coords.yaw(90) == -90
    r = coords.look_rotator([0, 1, 0], [0, 1, 10])
    assert r["Yaw"] == 0 and r["Pitch"] == 0


def _baked():
    # 两台机位：前 3 帧 c1、后 2 帧 c2；一个会动的人
    cam = lambda x: [x, 1.6, 5, 0, 1, 0, 35, 0]  # noqa: E731
    return {
        "fps": 24, "frames": 5, "duration": 0.1667,
        "objects": [
            {"id": "A", "name": "A", "kind": "character", "parent": None, "pos": [0, 0, 0], "rot": [0, 0, 0], "scale": [1, 1, 1],
             "animated": True, "character": {"body": "male", "height": 1.75}},
            {"id": "house", "name": "house", "kind": "prefab", "prefab": "house", "parent": None, "pos": [5, 0, 5],
             "rot": [0, 90, 0], "scale": [1, 1, 1], "animated": False,
             "parts": [{"prim": "box", "size": [4, 3, 6], "pos": [0, 1.5, 0]}]},
        ],
        "anim": {"A": sum(([0, 0, i * 0.5, 0, 0, 0, 1, 1, 1] for i in range(5)), [])},
        "lights": [{"id": "s", "kind": "sun", "dir": [-0.6, -1.4, -0.5]}],
        "camera": {"ids": ["c1", "c1", "c1", "c2", "c2"], "frames": sum((cam(0) for _ in range(5)), [])},
        "cameras": {"c1": {"name": "一号", "frames": sum((cam(0) for _ in range(5)), [])},
                    "c2": {"name": "二号", "frames": sum((cam(2) for _ in range(5)), [])}},
    }


PROTO = {"scene_id": "s1", "environment": {"preset": "street_day"},
         "timeline": [{"op": "actor.play_action", "time": 0.04, "actor": "A", "action": "right_punch", "duration": 0.6}]}


def test_ue_plan_translates_actors_sequence_and_cuts():
    p = ue.plan(PROTO, _baked(), {"level": "/Game/L", "asset_map": {}})
    house = next(a for a in p["level"]["actors"] if a["id"] == "house")
    assert house["placeholder"] and house["asset"].endswith("Cube.Cube")
    assert house["scale"] == [6, 4, 3]                     # 包围盒 (x4, y3, z6) → UE (X=z, Y=x, Z=y)
    assert house["rotation"]["Yaw"] == -90
    assert p["cameras"]["cuts"] == [{"camera": "c1", "start_frame": 0, "end_frame": 3}, {"camera": "c2", "start_frame": 3, "end_frame": 5}]
    anim = p["sequence"]["animations"][0]
    assert anim["anim_asset"].endswith("Punch_R") and (anim["start_frame"], anim["end_frame"]) == (1, 15)
    for name, src in p["scripts"].items():
        compile(src, name, "exec")                          # 生成的 Unreal Python 至少语法对
    assert "json.loads(" in p["scripts"]["build_level.py"]


def test_camera_cut_track_merges_runs():
    assert camera_to_sequencer.camera_cuts({"camera": {"ids": ["a", "a", "", "a"]}}) == [
        {"camera": "a", "start_frame": 0, "end_frame": 2}, {"camera": "a", "start_frame": 3, "end_frame": 4}]


def test_ue_execute_is_off_in_v1(monkeypatch):
    monkeypatch.delenv("DIRECTOR_UE_ENABLED", raising=False)
    with pytest.raises(config.FeatureDisabled):
        ue.execute(PROTO, _baked())


def test_ue_execute_sends_the_scripts_when_enabled(monkeypatch):
    monkeypatch.setenv("DIRECTOR_UE_ENABLED", "true")
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append((req.method, req.url.path, json.loads(req.content or b"{}")))
        return httpx.Response(200, json={"ok": True} if req.url.path != "/remote/info" else {"HttpServerPort": 30010})
    client = UERemoteHTTP("http://ue", transport=httpx.MockTransport(handler))
    out = ue.execute(PROTO, _baked(), client=client)
    assert out["ue"] == {"HttpServerPort": 30010}
    puts = [c for c in calls if c[0] == "PUT"]
    assert len(puts) == 3 and all(c[1] == "/remote/object/call" for c in puts)
    assert puts[0][2]["functionName"] == "ExecutePythonCommand" and "PythonCommand" in puts[0][2]["parameters"]


def test_ue_websocket_envelope_and_reply():
    sent = []

    class Fake:
        def send(self, s):
            sent.append(json.loads(s))

        def recv(self):
            return json.dumps({"RequestId": sent[-1]["Id"], "ResponseCode": 200, "ResponseBody": {"ReturnValue": 1}})

        def close(self):
            pass
    with UERemoteWS(connect=lambda url, timeout: Fake()) as ws:
        assert ws.call("/Game/X", "Foo", {"a": 1}) == {"ReturnValue": 1}
    assert sent[0] == envelope(1, "/remote/object/call", {"objectPath": "/Game/X", "functionName": "Foo",
                                                          "parameters": {"a": 1}, "generateTransaction": True})


# ── 任务 ────────────────────────────────────────────────

def test_blender_progress_percent_weights_the_slow_passes():
    p = jobs._Progress("j", ["preview", "clay", "depth", "pose", "canny"])
    p.done = {"build", "walk"}
    p.state = {"stage": "preview", "frame": 72, "total": 145}
    mid = p.percent()
    p.done |= {"preview"}
    p.state = {"stage": "clay", "frame": 0, "total": 145}
    assert 20 < mid < p.percent() < 60


def test_final_render_needs_a_finished_control_job():
    with pytest.raises(jobs.JobError, match="控制素材"):
        jobs.submit_final(None, SimpleNamespace(job_type="blender_render", status="running"), {})
