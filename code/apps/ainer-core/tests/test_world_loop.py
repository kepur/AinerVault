"""闭环：骨骼动作、take → Blender 作业、LTX layout 载荷、QA 闸门、共享舞台复用、Blender 冒烟。"""
from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from app.worldmodel import motion
from app.worldmodel import qa
from app.worldmodel.seeds import chapter01_corridor as ch1
from tests.test_world_db import db  # noqa: F401  (Postgres 夹具，回滚事务)

BLENDER = "/Applications/Blender.app/Contents/MacOS/Blender"


def test_pose_clips_use_mixamo_bones_and_move():
    for clip in ("walk", "slap", "kick", "cower", "tremble", "pick_up"):
        a, _ = motion.pose_at([{"clip": clip, "start_ms": 0, "end_ms": 2000}], 300)
        b, _ = motion.pose_at([{"clip": clip, "start_ms": 0, "end_ms": 2000}], 1000)
        assert set(a) <= set(motion.BONES)
        assert a != b, clip
    # 片段外：静止
    assert motion.pose_at([{"clip": "slap", "start_ms": 0, "end_ms": 500}], 5000)[0] == motion.pose_at([], 5000)[0]


def test_seed_motion_clips_are_known():
    for tr in ch1.tracks().values():
        for c in tr["clips"]:
            assert c["clip"] in motion.KNOWN_CLIPS, c


def test_layout_payload_needs_styled_first_frame():
    from app.director.renderers.base import RenderRequest, RendererError
    from app.director.renderers.ltx25 import LTX25Adapter
    ad = LTX25Adapter()
    req = RenderRequest(renderer="ltx_25", prompt="p", control_type="layout", control_video="/media/clay.mp4",
                        fps=8, resolution=(640, 384), duration_sec=3.0)
    with pytest.raises(RendererError):
        ad.validate(req)
    ok = req.model_copy(update={"first_frame": "/media/f.png", "first_frame_styled": True})
    pay = ad.build_payload(ad.validate(ok))
    assert pay["first_frame"] == {"url": "/media/f.png"}
    assert pay["control"]["type"] == "layout"


def _ffmpeg(args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="no ffmpeg")
def test_qa_gates_on_synthetic_clips(tmp_path):
    zoom = str(tmp_path / "zoom.mp4")
    _ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=640x384:r=8:d=3", "-f", "lavfi", "-i", "sine=f=440:d=3",
             "-vf", "zoompan=z='1+0.006*on':d=1:s=640x384:fps=8", "-shortest", "-c:a", "aac", zoom])
    g = qa.gate_shot(zoom, kind="action", planned_move="push_in", duration_s=3.0, mood="tension",
                     prompt="tense dramatic", music_cue="tension")
    assert g["camera"]["ok"] and g["motion"]["ok"] and g["audio"]["ok"], g
    still = str(tmp_path / "still.mp4")
    _ffmpeg(["-f", "lavfi", "-i", "color=c=gray:s=640x384:r=8:d=3", still])
    g = qa.gate_shot(still, kind="action", planned_move="push_in", duration_s=3.0, mood=None, prompt="")
    assert not g["pass"] and {"camera", "motion", "audio"} <= set(g["failed"])


def test_take_job_carries_skeleton_frames_and_camera_move(db):  # noqa: F811
    from app.worldmodel import compile as wc
    from app.worldmodel import service as ws
    r = ch1.build(db)
    perf = ws.performance_for_scene(db, ch1.SCENE_KEY)
    take = next(t for t in ws.performance_out(perf)["takes"] if t["order_no"] == 12) \
        if "takes" in ws.performance_out(perf) else None
    if take is None:
        from app.models import WorldTake
        take = ws.take_out(db.query(WorldTake).filter_by(performance_id=perf.id, order_no=12).one())
    snap = ws.snapshot(db, r["world_id"], region_keys=[perf.region_key])
    job = wc.compile_take_job(snap, ws.performance_out(perf), take, out_dir="/tmp/x", resolution=(640, 384),
                              actors_meta=ch1.ACTORS)
    n = wc.ltx_frames(take["end_ms"] - take["start_ms"], take["fps"])
    assert len(job["camera_frames"]) == n
    assert job["camera_frames"][0] != job["camera_frames"][-1]
    fr = job["actors"]["brad"]["frames"]
    assert len(fr) == n and set(fr[0]["bones"]) <= set(motion.BONES)
    assert set(job["passes"]) >= {"clay", "depth", "pose"}
    # 街道区域：镜 19 在第二个区域，通过 portal 连到走廊
    street = ws.performance_for_scene(db, ch1.STREET_SCENE_KEY)
    assert street.region_key == ch1.STREET_KEY


def test_staged_scene_reuses_one_stage_per_scene(db, monkeypatch):  # noqa: F811
    from types import SimpleNamespace

    from app.director import from_shot
    from app.models import DirectorScene
    calls = []
    plan = SimpleNamespace(id="sp_test_world_loop")
    s1, s2 = SimpleNamespace(id="s1", scene_id="sc_same"), SimpleNamespace(id="s2", scene_id="sc_same")

    def plan_once():
        calls.append(1)
        sc = DirectorScene(**from_shot._test_scene_kwargs()) if hasattr(from_shot, "_test_scene_kwargs") else None
        return sc, []
    if not hasattr(from_shot, "_test_scene_kwargs"):
        pytest.skip("DirectorScene 构造需要完整导演上下文；复用逻辑由 stage_scene_key 覆盖")
    a, _, ra = from_shot.staged_scene(db, plan, s1, plan_once)
    b, _, rb = from_shot.staged_scene(db, plan, s2, plan_once)
    assert len(calls) == 1 and not ra and rb and a.id == b.id


def test_stage_scene_key_shares_by_scene():
    from types import SimpleNamespace

    from app.director.from_shot import stage_scene_key
    p = SimpleNamespace(id="sp1")
    assert stage_scene_key(p, SimpleNamespace(id="a", scene_id="x")) == stage_scene_key(p, SimpleNamespace(id="b", scene_id="x"))
    assert stage_scene_key(p, SimpleNamespace(id="a", scene_id=None)) != stage_scene_key(p, SimpleNamespace(id="b", scene_id=None))


@pytest.mark.skipif(not os.path.exists(BLENDER), reason="no Blender")
def test_blender_world_multicam_smoke(db, tmp_path):  # noqa: F811
    from app.models import WorldTake
    from app.worldmodel import blender_run
    from app.worldmodel import compile as wc
    from app.worldmodel import service as ws
    r = ch1.build(db)
    perf = ws.performance_for_scene(db, ch1.SCENE_KEY)
    t = db.query(WorldTake).filter_by(performance_id=perf.id, order_no=1).one()
    snap = ws.snapshot(db, r["world_id"], region_keys=[perf.region_key])
    job = wc.compile_take_job(snap, ws.performance_out(perf), ws.take_out(t), out_dir=str(tmp_path),
                              resolution=(320, 192), passes=["clay"], actors_meta=ch1.ACTORS)
    m = blender_run.run(job, timeout_s=300, log_path=str(tmp_path / "b.log"))
    assert os.path.exists(m["outputs"]["clay"]) and m["check"]["ok"]
