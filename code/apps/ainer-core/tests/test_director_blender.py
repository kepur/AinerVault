"""Blender 控制素材：骨架图画法、PNG、适配器的进度解析／卡死换进程／报错，以及一次真 Blender 冒烟。"""
from __future__ import annotations

import json
import os
import shutil
import struct
import sys
import textwrap
import zlib

import numpy as np
import pytest

from app.director import blender_adapter, config
from app.director.blender_worker.png import COLORS, LIMBS, draw_pose, write_png


# ── 骨架图（OpenPose COCO-18）──────────────────────────────

def test_limbs_and_colors_match_openpose():
    """视频模型的姿态控制是拿 controlnet_aux 的画法训练的：连线表、配色一处都不能自创。"""
    assert len(LIMBS) == 17 and LIMBS[0] == (1, 2) and LIMBS[12] == (1, 0)
    assert COLORS[0] == (255, 0, 0) and len(COLORS) == 18


def test_pose_image_draws_joints_and_limbs_and_skips_unseen_points():
    kps = [(0.0, 0.0, 0.0)] * 18
    kps[1] = (50.0, 50.0, 1.0)      # 颈
    kps[2] = (30.0, 50.0, 1.0)      # 右肩
    kps[3] = (30.0, 90.0, 0.0)      # 右肘：看不见 → 不画，连它的肢体也不画
    img = draw_pose(128, 128, [kps])
    assert tuple(img[50, 50]) == COLORS[1]                         # 关节是全色
    assert tuple(img[50, 40]) == tuple(int(c * 0.6) for c in COLORS[0])   # 颈–右肩肢体 60% 亮度
    assert not img[90, 30].any()


def test_png_writer_produces_a_valid_png(tmp_path):
    img = np.zeros((6, 10, 3), dtype=np.uint8)
    img[2, 3] = (255, 0, 0)
    p = tmp_path / "a.png"
    write_png(str(p), img)
    raw = p.read_bytes()
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = struct.unpack(">II", raw[16:24])
    assert (w, h) == (10, 6)
    idat = raw[raw.index(b"IDAT") + 4:raw.index(b"IEND") - 8]
    rows = zlib.decompress(idat)
    assert rows[2 * 31 + 1 + 3 * 3] == 255          # 第 2 行、第 3 列的 R


# ── 适配器：拿一个假的「Blender」脚本测进度、卡死、报错 ─────────────

def _fake(tmp_path, body: str):
    script = tmp_path / "fake_blender.py"
    script.write_text(textwrap.dedent(body))
    exe = tmp_path / "blender"
    exe.write_text(f"#!/bin/sh\nexec {sys.executable} {script} \"$@\"\n")
    exe.chmod(0o755)
    return str(exe)


@pytest.fixture
def cfg(monkeypatch):
    def use(binary: str, **over):
        conf = {"binary": binary, "stall_sec": 3, "timeout_sec": 60, "retries": 1, "passes": ["pose"], **over}
        real = config.load

        def fake(name):
            return conf if name == "blender" else real(name)
        monkeypatch.setattr(config, "load", fake)
        monkeypatch.setenv("DIRECTOR_BLENDER_ENABLED", "true")
    return use


def test_progress_is_parsed_and_the_manifest_returned(tmp_path, cfg):
    exe = _fake(tmp_path, """
        import json, os, sys
        job = json.load(open(sys.argv[sys.argv.index("--") + 1]))
        print("Blender 5.x 启动噪音", flush=True)
        print("AINER_STAGE " + json.dumps({"stage": "pose"}), flush=True)
        print("AINER_PROGRESS " + json.dumps({"pass": "pose", "frame": 1, "total": 2}), flush=True)
        m = os.path.join(job["out_dir"], "manifest.json")
        json.dump({"outputs": {"pose": "pose.mp4"}, "passes": job["passes"]}, open(m, "w"))
        print("AINER_DONE " + json.dumps({"manifest": m}), flush=True)
    """)
    cfg(exe)
    seen = []
    m = blender_adapter.render(job_id="j", scene_id=None, baked_path="x.json", out_dir=str(tmp_path), resolution=(256, 144),
                               on_progress=seen.append)
    assert m["outputs"] == {"pose": "pose.mp4"} and m["passes"] == ["pose"]
    assert [e["kind"] for e in seen] == ["stage", "progress"]
    job = json.loads((tmp_path / "job.json").read_text())
    assert job["resolution"] == [256, 144] and job["ffmpeg"]


def test_a_stuck_blender_is_killed_and_retried_in_a_new_process(tmp_path, cfg):
    """「卡住的直接杀掉，换一个进程」：第一次一声不吭挂住，第二次正常。"""
    exe = _fake(tmp_path, """
        import json, os, sys, time
        job = json.load(open(sys.argv[sys.argv.index("--") + 1]))
        flag = os.path.join(job["out_dir"], "first.done")
        if not os.path.exists(flag):
            open(flag, "w").close()
            time.sleep(60)
        m = os.path.join(job["out_dir"], "manifest.json")
        json.dump({"outputs": {}}, open(m, "w"))
        print("AINER_DONE " + json.dumps({"manifest": m}), flush=True)
    """)
    cfg(exe, stall_sec=2)
    seen = []
    m = blender_adapter.render(job_id="j", scene_id=None, baked_path="x", out_dir=str(tmp_path), resolution=(256, 144),
                               on_progress=seen.append)
    assert m == {"outputs": {}}
    retry = [e for e in seen if e["kind"] == "retry"]
    assert len(retry) == 1 and "卡死" in retry[0]["error"]


def test_worker_errors_surface_after_retries(tmp_path, cfg):
    exe = _fake(tmp_path, """
        import json
        print("AINER_ERROR " + json.dumps({"message": "KeyError: 'objects'"}), flush=True)
        raise SystemExit(2)
    """)
    cfg(exe, retries=1)
    with pytest.raises(blender_adapter.BlenderError, match="KeyError"):
        blender_adapter.render(job_id="j", scene_id=None, baked_path="x", out_dir=str(tmp_path), resolution=(256, 144))


def test_the_blender_child_gets_no_secrets(monkeypatch):
    monkeypatch.setenv("CORE_DATABASE_URL", "postgresql://u:p@h/db")
    monkeypatch.setenv("SOME_API_KEY", "x")
    env = blender_adapter._env()
    assert "CORE_DATABASE_URL" not in env and "SOME_API_KEY" not in env and "PATH" in env


def test_disabled_flag_blocks_rendering(monkeypatch, tmp_path):
    monkeypatch.setenv("DIRECTOR_BLENDER_ENABLED", "false")
    with pytest.raises(config.FeatureDisabled):
        blender_adapter.render(job_id="j", scene_id=None, baked_path="x", out_dir=str(tmp_path), resolution=(256, 144))


# ── 真 Blender 冒烟（装了 Blender 和 node 才跑）─────────────────

@pytest.mark.skipif(not (blender_adapter.binary() and (shutil.which("node") or os.path.exists("/opt/homebrew/bin/node"))),
                    reason="没有 Blender 或 node")
def test_real_blender_renders_pose_and_clay(tmp_path, monkeypatch):
    from app.scene3d.runner import bake_scene, compile_scene

    monkeypatch.setenv("DIRECTOR_BLENDER_ENABLED", "true")
    r = compile_scene('S.setup({duration: 1});\nconst a = S.character("a", {at: [0, 0]});\n'
                      'S.action(a, "right_punch", {t: 0});\nconst c = S.camera("c");\n'
                      'S.cameraKeys(c, [{t: 0, at: [0, 1.5, 4], look: [0, 1, 0]}]);')
    b = bake_scene(r["doc"], frames=9)
    (tmp_path / "baked.json").write_text(json.dumps(b))
    m = blender_adapter.render(job_id="t", scene_id=None, baked_path=str(tmp_path / "baked.json"), out_dir=str(tmp_path),
                               resolution=(256, 160), passes=["clay", "pose"])
    assert {"clay", "pose", "camera_json", "motion_json", "blend"} <= set(m["outputs"])
    motion = json.loads((tmp_path / "motion.json").read_text())
    kps = motion["actors"]["a"]["frames"][0]["keypoints_2d"]
    assert len(kps) == 18
    nose, neck = kps[0], kps[1]
    assert nose[2] == 1 and neck[2] == 1 and nose[1] < neck[1]       # 看得见，鼻子在脖子上面
    assert 60 < neck[0] < 200                                        # 人在画面中间一带
