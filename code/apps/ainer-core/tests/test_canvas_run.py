"""一章多张画布、画布一键出片工作流、LTX 2.5 配音驱动。

不连库：切画布规则、工作流状态机是纯函数，直接测；advance 用假库和假的导演出片走一遍。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.api.v2 import canvas as api
from app.api.v2 import canvas_run as run_api
from app.director.renderers.base import RenderRequest, RendererError
from app.director.renderers.ltx25 import LTX25Adapter
from app.pipelines import canvas_run as cr


# ── 一章怎么分画布 ──────────────────────────────────────────────────────

def _shots(scene, n, start=1):
    return [(f"{scene}_{i}", scene, start + i) for i in range(n)]


def test_one_canvas_per_scene_in_scene_order():
    scenes = [("s2", 2, "归家掩饰"), ("s1", 1, "走廊抢劫"), ("s3", 3, None)]
    rows = api.split_scopes(scenes, _shots("s1", 3) + _shots("s2", 2, 10))
    assert [r.title for r in rows] == ["1. 走廊抢劫", "2. 归家掩饰"], "没镜头的场次不建画布"
    assert rows[0].shot_ids == ["s1_0", "s1_1", "s1_2"] and rows[0].scene_ids == ["s1"]
    assert [r.sort for r in rows] == [0, 1]


def test_long_scenes_split_evenly_without_a_tiny_tail():
    """112 镜按 24 一段 → 5 段，每段 22–23 镜；不是 4×24 + 一段 16。"""
    rows = api.split_scopes([("s4", 4, "放学围堵")], _shots("s4", 112), max_shots=24)
    assert len(rows) == 5
    assert {len(r.shot_ids) for r in rows} <= {22, 23}
    assert sum(len(r.shot_ids) for r in rows) == 112
    assert rows[0].title == "4. 放学围堵（1/5）" and rows[4].title == "4. 放学围堵（5/5）"
    # 键按段号，不带段数：场次长了一镜变成 6 段时，第 1 段还认得回原来那张画布
    assert rows[0].key == "scene:s4#1"


def test_shots_without_a_scene_go_to_the_last_canvas():
    rows = api.split_scopes([("s1", 1, "走廊")], _shots("s1", 2) + [("x", None, 99), ("y", "gone", 5)])
    assert rows[-1].title == "未分场" and rows[-1].shot_ids == ["y", "x"], "按镜头次序"


def test_board_scope_and_meta():
    plan = SimpleNamespace(kind="plan", scope_json={})
    scene = SimpleNamespace(kind="scene", scope_json={"shot_ids": ["a", "b", 3]})
    assert api.scope_shot_ids(plan) is None, "整章总览管全部镜头"
    assert api.scope_shot_ids(scene) == ["a", "b"]


def test_items_from_outside_land_below_everything():
    doc = {"nodes": [{"position": {"x": 40, "y": 0}, "height": 100}, {"position": {"x": -20, "y": 300}}]}
    assert api.place_below(doc) == {"x": -20.0, "y": 300 + 260 + 80}
    assert api.place_below({}) == {"x": 0.0, "y": 0.0}


def test_new_routes_are_registered():
    from app.main import app

    have = {(m, getattr(r, "path", "")) for r in app.routes for m in getattr(r, "methods", None) or ()}
    want = {
        ("GET", "/api/v2/studio/chapters/{chapter_id}/canvases"),
        ("POST", "/api/v2/studio/plans/{plan_id}/canvases:split"),
        ("POST", "/api/v2/studio/canvases"),
        ("GET", "/api/v2/studio/canvases/{board_id}"),
        ("PUT", "/api/v2/studio/canvases/{board_id}"),
        ("PATCH", "/api/v2/studio/canvases/{board_id}"),
        ("DELETE", "/api/v2/studio/canvases/{board_id}"),
        ("GET", "/api/v2/studio/shots/{shot_id}/canvas"),
        ("POST", "/api/v2/studio/canvases/{board_id}/items"),
        ("POST", "/api/v2/studio/canvases/{board_id}:run"),
        ("GET", "/api/v2/studio/runs/{run_id}"),
        ("POST", "/api/v2/studio/runs/{run_id}:cancel"),
        ("GET", "/api/v2/studio/canvases/{board_id}/runs"),
    }
    assert want <= have


# ── 工作流：纯函数 ──────────────────────────────────────────────────────

def test_pick_items_in_shot_order_and_skips_finished_shots():
    shots = [("c", 3, False), ("a", 1, True), ("b", 2, False)]
    assert [i["shot_id"] for i in cr.pick_items(shots)] == ["b", "c"]
    assert [i["shot_id"] for i in cr.pick_items(shots, only_missing=False)] == ["a", "b", "c"]
    assert [i["shot_id"] for i in cr.pick_items(shots, ["c", "a"], only_missing=False)] == ["a", "c"]
    assert cr.pick_items(shots)[0] == {"shot_id": "b", "order_no": 2, "step": "audio", "status": "pending"}


@pytest.mark.parametrize("st,elapsed,want", [
    (None, 10, "running"),
    (None, cr.LOST_S + 1, "failed"),
    ({"done": True, "status": "succeeded"}, 10, "succeeded"),
    ({"done": False, "status": "running", "step": "final"}, 10, "running"),
    ({"done": False, "status": "failed", "step": "identity", "error": None}, 10, "failed"),
    ({"done": False, "status": "running", "step": "final"}, cr.SHOT_TIMEOUT_S + 1, "failed"),
])
def test_director_verdict(st, elapsed, want):
    verdict, error = cr.director_verdict(st, 1000.0, 1000.0 + elapsed)
    assert verdict == want
    if want == "failed":
        assert error


def test_identity_failures_say_which_step():
    _, error = cr.director_verdict({"done": False, "status": "failed", "step": "identity"}, 0, 1)
    assert error == "身份首帧失败"


def test_summary_and_final_status():
    items = [{"status": "succeeded"}, {"status": "running", "shot_id": "b"}, {"status": "pending", "shot_id": "c"}]
    s = cr.summarize(items)
    assert (s["total"], s["succeeded"], s["running"], s["pending"]) == (3, 1, 1, 1)
    assert s["current"]["shot_id"] == "b"
    assert cr.finished_status([{"status": "succeeded"}, {"status": "failed"}]) == "failed"
    assert cr.finished_status([{"status": "succeeded"}, {"status": "skipped"}]) == "succeeded"


# ── 工作流：advance 假库走一遍 ──────────────────────────────────────────

class _DB:
    def __init__(self, **objs):
        self.objs = objs
        self.commits = 0

    def get(self, model, key):
        return self.objs.get(key)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def _run(items, **opts):
    return SimpleNamespace(id="run1", status="queued", started_at=None, finished_at=None, shot_plan_id="sp1",
                           profile="fast", options_json={"audio": "auto", "reuse_scene": True, **opts},
                           items_json=items)


def test_advance_walks_one_shot_through_audio_director_and_done(monkeypatch):
    from app.director import from_shot

    shot = SimpleNamespace(id="sh1", camera_json={"director_run": {"scene_id": "dsc_user"}})
    db = _DB(sh1=shot, sp1=SimpleNamespace(id="sp1"))
    monkeypatch.setattr(cr, "_dialogue", lambda db, sid: [])          # 这一镜没台词
    calls = []

    def fake_render(db, shot_id, **kw):
        calls.append((shot_id, kw))
        return {"blender_job_id": "djob1", "scene_id": kw.get("scene_id") or "dsc_new", "audio": "generate"}

    status = {"v": {"done": False, "status": "running", "step": "previs"}}
    monkeypatch.setattr(from_shot, "render_shot", fake_render)
    monkeypatch.setattr(from_shot, "run_status", lambda db, s: status["v"])

    run = _run([{"shot_id": "sh1", "order_no": 1, "step": "audio", "status": "pending"}], method="director")
    cr.advance(db, run, now=100)                  # 配音：没台词，直接过
    assert run.status == "running" and run.items_json[0]["step"] == "director"
    cr.advance(db, run, now=101)                  # 交导演任务：沿用 3D-BOX 里调过的场景
    assert calls == [("sh1", {"scene_id": "dsc_user", "profile": "fast", "audio": "auto", "frames_only": False})]
    assert run.items_json[0]["status"] == "running" and run.items_json[0]["reused"] is True
    cr.advance(db, run, now=200)                  # 还在跑
    assert run.items_json[0]["status"] == "running"
    status["v"] = {"done": True, "status": "succeeded", "step": "final"}
    cr.advance(db, run, now=600)
    assert run.items_json[0]["status"] == "succeeded"
    cr.advance(db, run, now=601)                  # 没有下一镜 → 收尾
    assert run.status == "succeeded" and run.finished_at is not None


def test_a_failing_shot_does_not_stop_the_rest(monkeypatch):
    from app.director import from_shot

    db = _DB(a=SimpleNamespace(id="a", camera_json={}), b=SimpleNamespace(id="b", camera_json={}),
             sp1=SimpleNamespace(id="sp1"))
    monkeypatch.setattr(cr, "_dialogue", lambda db, sid: [])

    def boom(db, shot_id, **kw):
        if shot_id == "a":
            raise ValueError("LLM 没搭出场景")
        return {"blender_job_id": "j", "scene_id": "s"}

    monkeypatch.setattr(from_shot, "render_shot", boom)
    run = _run([{"shot_id": "a", "order_no": 1, "step": "director", "status": "pending"},
                {"shot_id": "b", "order_no": 2, "step": "director", "status": "pending"}], reuse_scene=False)
    cr.advance(db, run, now=1)
    assert run.items_json[0]["status"] == "failed" and "LLM 没搭出场景" in run.items_json[0]["error"]
    cr.advance(db, run, now=2)
    assert run.items_json[1]["status"] == "running"


def test_shots_with_unvoiced_lines_get_voiced_first(monkeypatch):
    from app.pipelines import audio_compose as ac

    db = _DB(sh1=SimpleNamespace(id="sh1", camera_json={}), sp1=SimpleNamespace(id="sp1"))
    specs = [SimpleNamespace(asset_id=None)]
    monkeypatch.setattr(cr, "_dialogue", lambda db, sid: specs)
    submitted = []
    monkeypatch.setattr(ac, "generate_audio", lambda db, plan, **kw: submitted.append(kw) or SimpleNamespace(
        submitted=1, blocked=[], requires_confirm=False))
    monkeypatch.setattr(ac, "backfill_durations", lambda db, plan: {})
    run = _run([{"shot_id": "sh1", "order_no": 1, "step": "audio", "status": "pending"}])
    cr.advance(db, run, now=10)
    assert submitted == [{"kinds": ["dialogue"], "only_shot_ids": ["sh1"]}]
    assert run.items_json[0]["step"] == "audio" and run.items_json[0]["status"] == "running"
    cr.advance(db, run, now=20)                    # 还没落库：等
    assert run.items_json[0]["step"] == "audio"
    specs[0].asset_id = "as_tts"
    cr.advance(db, run, now=30)                    # 配好了 → 默认关键帧方案：画关键帧
    assert run.items_json[0]["step"] == "frame"


def test_audio_waits_have_a_limit(monkeypatch):
    db = _DB(sh1=SimpleNamespace(id="sh1", camera_json={}), sp1=SimpleNamespace(id="sp1"))
    monkeypatch.setattr(cr, "_dialogue", lambda db, sid: [SimpleNamespace(asset_id=None)])
    run = _run([{"shot_id": "sh1", "order_no": 1, "step": "audio", "status": "running", "audio_submitted": 0}])
    cr.advance(db, run, now=cr.AUDIO_WAIT_S + 1)
    assert run.items_json[0]["step"] == "frame" and "现场生成" in run.items_json[0]["note"]


def test_keyframe_method_draws_a_frame_then_a_video(monkeypatch):
    """默认方案：配音 → 关键帧（挂首帧）→ 钉住关键帧出视频 → 挂回镜头。任务在跑时主动问网关。"""
    from app.capability import service
    from app.models import TaskStatus
    from app.pipelines import keyframe

    shot = SimpleNamespace(id="sh1", camera_json={}, video_asset_id=None)
    tasks = {"kf1": SimpleNamespace(status=TaskStatus.running, error_json=None),
             "v1": SimpleNamespace(status=TaskStatus.running, error_json=None)}
    db = _DB(sh1=shot, sp1=SimpleNamespace(id="sp1"), **tasks)
    db.refresh = lambda obj: None
    monkeypatch.setattr(cr, "_dialogue", lambda db, sid: [])
    monkeypatch.setattr(cr, "_keyframe_ready", lambda db, s, engine: False)
    polled = []
    monkeypatch.setattr(service, "poll_task", lambda db, t: polled.append(t) or t)
    monkeypatch.setattr(keyframe, "submit_keyframe", lambda db, plan, s, engine: SimpleNamespace(id="kf1"))
    sizes = []
    monkeypatch.setattr(keyframe, "submit_video",
                        lambda db, plan, s, engine, size: sizes.append((engine, size)) or {"task": "v1", "audio": "drive"})

    run = _run([{"shot_id": "sh1", "order_no": 1, "step": "audio", "status": "pending"}], engine="local")
    cr.advance(db, run, now=0)                     # 配音（没台词）→ 关键帧
    cr.advance(db, run, now=1)                     # 交关键帧
    assert run.items_json[0]["frame_task"] == "kf1" and run.items_json[0]["step"] == "frame"
    cr.advance(db, run, now=1 + cr.POLL_EVERY_S + 1)
    assert polled, "回调没来也要主动问一次网关"
    tasks["kf1"].status = TaskStatus.succeeded
    cr.advance(db, run, now=100)                   # 关键帧好了 → 出视频
    assert run.items_json[0]["step"] == "video"
    cr.advance(db, run, now=101)
    assert sizes == [("local", (768, 448))] and run.items_json[0]["audio"] == "drive"
    tasks["v1"].status = TaskStatus.succeeded
    shot.video_asset_id = "as_video"
    cr.advance(db, run, now=400)
    assert run.items_json[0]["status"] == "succeeded"


def test_keyframe_failures_say_which_step(monkeypatch):
    from app.pipelines import keyframe

    db = _DB(sh1=SimpleNamespace(id="sh1", camera_json={}), sp1=SimpleNamespace(id="sp1"))
    monkeypatch.setattr(cr, "_keyframe_ready", lambda db, s, engine: False)

    def no_cast(db, plan, s, engine):
        raise keyframe.KeyframeError("林晓 在角色库里还没有本章的定妆照")

    monkeypatch.setattr(keyframe, "submit_keyframe", no_cast)
    run = _run([{"shot_id": "sh1", "order_no": 1, "step": "frame", "status": "pending"}])
    cr.advance(db, run, now=1)
    assert run.items_json[0]["status"] == "failed" and run.items_json[0]["error"].startswith("关键帧：林晓")


def test_existing_keyframes_are_reused(monkeypatch):
    db = _DB(sh1=SimpleNamespace(id="sh1", camera_json={}), sp1=SimpleNamespace(id="sp1"))
    monkeypatch.setattr(cr, "_keyframe_ready", lambda db, s, engine: True)
    run = _run([{"shot_id": "sh1", "order_no": 1, "step": "frame", "status": "pending"}])
    cr.advance(db, run, now=1)
    assert run.items_json[0]["step"] == "video" and run.items_json[0]["frame"] == "reused"


def test_local_video_reads_the_task_from_ltx25_items(monkeypatch):
    """ltx25_shots.generate 的 submitted 是条数、明细在 items（实跑踩过：按列表取会 'int' object is not subscriptable）。"""
    from app.pipelines import keyframe, ltx25_shots

    monkeypatch.setattr(ltx25_shots, "generate", lambda db, plan, **kw: {
        "submitted": 1, "items": [{"shot": 6, "task": "gt1", "audio": "drive"}], "skipped": []})
    assert keyframe.submit_video(None, None, SimpleNamespace(id="s"), "local") == {"task": "gt1", "audio": "drive"}
    monkeypatch.setattr(ltx25_shots, "generate", lambda db, plan, **kw: {
        "submitted": 0, "items": [], "skipped": [{"shot": 6, "why": "还没有关键帧"}]})
    assert keyframe.submit_video(None, None, SimpleNamespace(id="s"), "local") == {"skipped": "还没有关键帧"}


@pytest.mark.parametrize("status,want", [("running", "running"), ("succeeded", "succeeded"), ("failed", "failed")])
def test_task_verdict(status, want):
    assert cr.task_verdict(status, None, 0, 10, 60)[0] == want
    assert cr.task_verdict("running", None, 0, 61, 60)[0] == "failed", "超时"


def test_keyframe_prompt_is_an_english_instruction():
    from app.pipelines.keyframe import keyframe_prompt

    p = keyframe_prompt(people=["a slim teenage boy in a faded denim jacket"], size="ms",
                        framing="Medium shot in a school corridor.", action="He backs against the lockers.",
                        location="1990s school corridor with lockers", background="Photoreal film.", has_plate=True)
    assert p.startswith("Place 1 person in the scene"), "人放最前：模型最听前面的话"
    assert "reference image 1" in p and "(1) a slim teenage boy" in p
    assert "Use this location image as the set" in p
    assert "Medium shot." in p and "He backs against the lockers." in p
    assert "no collage" in p and len(p) <= 1900
    assert keyframe_prompt(people=[], size=None, framing="", action="", location="a ward", background="",
                           has_plate=False).startswith("Change the background to this location: a ward.")
    long = keyframe_prompt(people=["x " * 300] * 3, size="ms", framing="Framing here.", action="Action here.",
                           location="y " * 400, background="z " * 400, has_plate=True)
    assert "Framing here." in long and "Action here." in long, "外貌和场景再长也不能把构图和动作挤掉"
    assert "Exactly 3 people in the frame" in long, "多人镜头写死人数：klein 会把同一个人画两遍"
    assert "Exactly" not in p, "单人镜头不加（特写里还要留对手的虚焦肩膀）"


def test_still_framing_drops_camera_moves():
    from app.pipelines.keyframe import first_action, still_framing

    f = ("extreme close-up of skinny boy's face, head tilted to side, fresh red blood streak at corner of mouth, "
         "close-up, eye level to low angle looking up, telephoto 135mm lens, shallow depth of field, "
         "slow pan right, starting from left cheek, moving slightly to frontal-side angle, ending stable on the face")
    out = still_framing(f)
    assert "blood streak at corner of mouth" in out and "telephoto 135mm lens" in out
    assert "pan" not in out and "starting" not in out and "ending" not in out and "moving" not in out
    assert first_action("Uniform and very slow speed (simulating 0.4x pace). He wipes the blood off.") == "He wipes the blood off."
    assert first_action("No jitter. The leader steps forward.") == "The leader steps forward."


def test_the_keyframe_moment_skips_camera_sentences():
    from app.pipelines.keyframe import first_action

    assert first_action("Fixed camera position. The tall boy shoves him against the lockers. He winces.") == \
        "The tall boy shoves him against the lockers."
    assert first_action("Slow dolly in.") == ""


def test_stop_after_frame_finishes_the_shot_at_the_keyframe(monkeypatch):
    """先出分镜图：关键帧好了这一镜就算完成，不交视频（9-29 定的：先跑分镜图，审过再出视频）。"""
    from app.models import TaskStatus
    from app.pipelines import keyframe

    task = SimpleNamespace(status=TaskStatus.succeeded, error_json=None)
    db = _DB(sh1=SimpleNamespace(id="sh1", camera_json={}), sp1=SimpleNamespace(id="sp1"), kf=task)
    monkeypatch.setattr(cr, "_keyframe_ready", lambda db, s, engine: False)
    monkeypatch.setattr(keyframe, "submit_keyframe", lambda db, plan, s, engine: SimpleNamespace(id="kf"))
    monkeypatch.setattr(keyframe, "submit_video", lambda *a, **k: pytest.fail("先出分镜图时不该交视频"))
    run = _run([{"shot_id": "sh1", "order_no": 1, "step": "frame", "status": "pending"}], stop_after="frame")
    cr.advance(db, run, now=1)
    cr.advance(db, run, now=2)
    assert run.items_json[0]["status"] == "succeeded" and run.items_json[0]["stopped"] == "frame"


def test_a_crash_after_submitting_the_video_adopts_the_task(monkeypatch):
    """交视频时抛异常，但任务其实已经交上去了：认领它，不记成失败（镜 6、7 实跑踩过）。"""
    from app.pipelines import keyframe

    db = _DB(sh1=SimpleNamespace(id="sh1", camera_json={}), sp1=SimpleNamespace(id="sp1"))

    def crash(*a, **k):
        raise TypeError("'int' object is not subscriptable")

    monkeypatch.setattr(keyframe, "submit_video", crash)
    monkeypatch.setattr(cr, "_recent_video_task", lambda db, sid, since: SimpleNamespace(id="gt_video"))
    run = _run([{"shot_id": "sh1", "order_no": 1, "step": "video", "status": "pending"}])
    cr.advance(db, run, now=5)
    assert run.items_json[0]["status"] == "running" and run.items_json[0]["video_task"] == "gt_video"


def test_close_ups_only_draw_the_focus_person():
    from app.pipelines.keyframe import pick_cast

    assert pick_cast(["a", "b", "c"], "b", "ecu") == ["b"]
    assert pick_cast(["a", "b", "c", "d"], "c", "ms") == ["c", "a", "b"], "焦点人物排第一，最多 3 个"
    assert pick_cast(["a", "b"], None, "cu") == ["a", "b"], "没有焦点就照常"
    assert pick_cast([], "x", "cu") == []


def test_camera_is_tamed_for_keyframe_videos():
    from app.pipelines.keyframe import tame_camera

    out = tame_camera("He shouts at the boy. The camera orbits 180 degrees around them. Audio: shouting.", "ecu")
    assert "orbit" not in out and "He shouts at the boy." in out and "Audio: shouting." in out
    assert "face stays centered" in out
    assert "characters stay in frame" in tame_camera("They walk.", "ws")


def test_camera_sentences_are_not_the_keyframe_moment():
    from app.pipelines.keyframe import first_action

    assert first_action("Starts at frontal eye-level on both boys. The leader slaps him hard.") == \
        "The leader slaps him hard."


def test_chinese_descriptions_never_reach_the_image_model():
    from app.pipelines.keyframe import _english

    assert _english("林晓在雪坡上") == "" and _english("a girl on a slope") == "a girl on a slope"


def test_run_out_carries_the_summary():
    db = _DB()
    run = SimpleNamespace(id="r", board_id="b", shot_plan_id="p", status="running", profile="fast", options_json={},
                          items_json=[{"status": "pending", "shot_id": "x", "step": "audio"}], error=None,
                          created_at=None, started_at=None, finished_at=None)
    out = run_api.run_out(db, run)
    assert out["summary"]["current"]["shot_id"] == "x" and out["summary"]["total"] == 1


# ── LTX 2.5：台词轨驱动口型 ─────────────────────────────────────────────

def _req(**kw):
    return RenderRequest(renderer="ltx_25", prompt="p", control_type="union", control_video="/media/c.mp4",
                         control_videos={"depth": "/media/d.mp4"}, resolution=(768, 448), duration_sec=5, **kw)


def test_drive_mode_sends_the_dialogue_track_and_pins_the_identity_frame():
    a = LTX25Adapter()
    req = a.validate(_req(audio_mode="drive", audio_track="/media/drive.wav", first_frame="/media/id.png"))
    p = a.build_payload(req)
    assert p["audio"] == {"mode": "drive", "track": {"url": "/media/drive.wav"}}
    assert p["first_frame"] == {"url": "/media/id.png"} and p["quality"] == "final"
    assert "control" not in p, "网关的 a2v 不吃白模控制视频"
    assert (p["width"], p["height"]) == (768, 448)


def test_drive_mode_needs_a_track_and_a_first_frame():
    a = LTX25Adapter()
    with pytest.raises(RendererError):
        a.validate(_req(audio_mode="drive", first_frame="/media/id.png"))
    with pytest.raises(RendererError):
        a.validate(_req(audio_mode="drive", audio_track="/media/drive.wav"))


def test_union_control_keeps_generated_sound_unless_muted():
    a = LTX25Adapter()
    assert a.build_payload(a.validate(_req()))["audio"] == {"mode": "generate"}
    assert a.build_payload(a.validate(_req(audio_mode="none")))["audio"] == {"mode": "none"}


def test_render_profiles():
    from app.director import from_shot

    assert from_shot.PROFILES["fast"] == (768, 448)
    assert all(w % 64 == 0 and h % 64 == 0 for w, h in from_shot.PROFILES.values()), "两阶段管线要 64 的倍数"


def test_keyframe_candidates_are_picked_by_the_vision_model(monkeypatch):
    """出 2 张候选：都出完后视觉模型挑一张挂首帧；记下挑了哪张、为什么；stop_after=frame 就停在这里。"""
    from app.capability import service
    from app.models import TaskStatus
    from app.pipelines import frame_select, keyframe

    shot = SimpleNamespace(id="sh1", camera_json={"review": {"first_frame": "Medium shot. Two boys."}}, description="两人对峙")
    tasks = {"k0": SimpleNamespace(id="k0", status=TaskStatus.running, error_json=None),
             "k1": SimpleNamespace(id="k1", status=TaskStatus.running, error_json=None)}
    db = _DB(sh1=shot, sp1=SimpleNamespace(id="sp1"), **tasks)
    monkeypatch.setattr(cr, "_dialogue", lambda db, sid: [])
    monkeypatch.setattr(cr, "_keyframe_ready", lambda db, s, engine: False)
    monkeypatch.setattr(service, "poll_task", lambda db, t: t)
    monkeypatch.setattr(keyframe, "submit_candidates",
                        lambda db, plan, s, engine, n: [tasks[f"k{i}"] for i in range(n)])
    monkeypatch.setattr(keyframe, "candidate_url", lambda db, tid: (f"as_{tid}", f"http://x/media/{tid}.png"))
    monkeypatch.setattr(keyframe, "pick_refs", lambda db, plan, s: [("Brad", "http://x/media/brad.png")])
    seen = {}

    def fake_pick(db, refs, cands, target):
        seen.update(refs=refs, cands=cands, target=target)
        return {"best": 1, "reason": "候选 0 多了一个人", "problems": [], "model": "qwen3.6"}

    monkeypatch.setattr(frame_select, "pick", fake_pick)
    attached = []
    monkeypatch.setattr(keyframe, "attach_candidate", lambda db, s, tid, aid, pick: attached.append((tid, aid, pick["best"])))

    run = _run([{"shot_id": "sh1", "order_no": 1, "step": "audio", "status": "pending"}],
               engine="local", candidates=2, stop_after="frame")
    cr.advance(db, run, now=0)
    cr.advance(db, run, now=1)
    assert run.items_json[0]["frame_tasks"] == ["k0", "k1"]
    tasks["k0"].status = TaskStatus.succeeded
    cr.advance(db, run, now=50)
    assert not attached, "还有一张没出完：先不挑"
    tasks["k1"].status = TaskStatus.succeeded
    cr.advance(db, run, now=100)
    assert attached == [("k1", "as_k1", 1)]
    assert seen["cands"] == ["http://x/media/k0.png", "http://x/media/k1.png"] and seen["target"] == "Medium shot. Two boys."
    it = run.items_json[0]
    assert it["status"] == "succeeded" and it["stopped"] == "frame" and it["pick"] == {"best": 1, "of": 2, "reason": "候选 0 多了一个人"}


def test_one_failed_candidate_still_gives_a_frame(monkeypatch):
    from app.models import TaskStatus
    from app.pipelines import frame_select, keyframe

    shot = SimpleNamespace(id="sh1", camera_json={}, description="x")
    tasks = {"k0": SimpleNamespace(id="k0", status=TaskStatus.failed, error_json={"message": "OOM"}),
             "k1": SimpleNamespace(id="k1", status=TaskStatus.succeeded, error_json=None)}
    db = _DB(sh1=shot, sp1=SimpleNamespace(id="sp1"), **tasks)
    monkeypatch.setattr(keyframe, "candidate_url", lambda db, tid: (f"as_{tid}", f"u_{tid}"))
    monkeypatch.setattr(keyframe, "pick_refs", lambda db, plan, s: [])
    monkeypatch.setattr(frame_select, "pick", lambda db, refs, cands, target: {"best": 0, "reason": "只有一张候选", "problems": []})
    attached = []
    monkeypatch.setattr(keyframe, "attach_candidate", lambda db, s, tid, aid, pick: attached.append(tid))
    run = _run([{"shot_id": "sh1", "order_no": 1, "step": "frame", "status": "running", "frame_tasks": ["k0", "k1"],
                 "submitted": 0, "polled": 0}], engine="local", stop_after="video")
    cr.advance(db, run, now=5)
    assert attached == ["k1"] and run.items_json[0]["step"] == "video"


def test_model_lookup_refreshes_a_stale_gateway_catalog_once(monkeypatch):
    """网关新装了模型、core 缓存的目录还没有：先刷新一次本机网关目录再找（2026-10-08 ltx-2.5 报「没有找到模型」）。"""
    from app.capability import generic
    from app.pipelines import keyframe

    ep = SimpleNamespace(name="本机 AI 绘图工作台", base_url="http://127.0.0.1:7999/cap/v1")

    class _Rows:
        def scalars(self):
            return [ep]

    db = SimpleNamespace(execute=lambda *_a, **_k: _Rows())
    fresh = {"done": False}
    info = SimpleNamespace(model="ltx-2.5-22b-distilled")
    monkeypatch.setattr(generic, "catalog_models", lambda e, caps: [info] if fresh["done"] else [])
    monkeypatch.setattr(generic, "_enabled_routes", lambda db: [])
    monkeypatch.setattr(generic, "route_for", lambda i, e, routes: ("route", False))
    calls = []

    def refresh(db, eps):
        calls.append(len(eps))
        fresh["done"] = True
        return True

    monkeypatch.setattr(keyframe, "_refresh_local_catalogs", refresh)
    assert keyframe._route(db, "video.image_to_video", "ltx-2.5-22b-distilled") == ("route", True, None)
    assert calls == [1]
    calls.clear()
    fresh["done"] = False
    monkeypatch.setattr(keyframe, "_refresh_local_catalogs", lambda db, eps: calls.append(1) or False)
    route, _local, why = keyframe._route(db, "video.image_to_video", "nope")
    assert route is None and "没有找到模型" in why and calls == [1], "刷新也找不到：只刷一次，照旧报找不到"
