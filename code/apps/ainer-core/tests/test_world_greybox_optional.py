"""world-greybox 是可选路径：默认关；关着时默认路径（原导演/动态漫剧）行为与改造前一致。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.director import config, from_shot
from app.worldmodel import qa, switches


class _Stop(Exception):
    pass


def _fake_db(shot, plan):
    objs = {shot.id: shot, plan.id: plan}
    return SimpleNamespace(get=lambda model, i: objs.get(i))


def _wire(monkeypatch, calls):
    shot = SimpleNamespace(id="sh_1", order_no=3, description="Tyler slaps Thomas", scene_id="sc_1", shot_plan_id="sp_1")
    plan = SimpleNamespace(id="sp_1", script_doc_id=None)
    monkeypatch.setattr(from_shot, "director_brief", lambda db, s, p: {"brief": "b", "duration": 3.0, "cast": [],
                                                                       "shot_size": "medium", "focus": None})
    monkeypatch.setattr(from_shot.planner, "generate_protocol",
                        lambda db, brief, duration: (calls.append(("plan", brief, duration)) or ({}, ["r"])))
    monkeypatch.setattr(from_shot, "bind_cast", lambda db, proto, cast: calls.append(("bind",)))

    def create(db, protocol, **kw):
        calls.append(("create", protocol.get("meta", {}).get("title"), kw["notes"]))
        return SimpleNamespace(id="ds_1", notes_json=kw["notes"], protocol_json=protocol)
    monkeypatch.setattr(from_shot.store, "create_from_protocol", create)

    def frame(*a, **kw):
        calls.append(("frame",))
        raise _Stop
    monkeypatch.setattr(from_shot, "auto_frame", frame)
    return _fake_db(shot, plan)


def test_flag_defaults_off():
    config.reload()
    assert config.load("feature_flags").get("world_greybox_enabled") is False
    assert "world_greybox_enabled" in config.FLAGS


def test_resolve_is_off_without_flag(monkeypatch):
    monkeypatch.delenv("DIRECTOR_WORLD_GREYBOX_ENABLED", raising=False)
    d = switches.resolve(SimpleNamespace(scalar=lambda q: pytest.fail("must not query switches when flag off")),
                         shot="sh_1", chapter="ch_1")
    assert not d.enabled and "feature flag" in d.reason


def test_resolve_needs_a_switch_even_with_flag(monkeypatch):
    monkeypatch.setenv("DIRECTOR_WORLD_GREYBOX_ENABLED", "true")
    d = switches.resolve(SimpleNamespace(scalar=lambda q: None), shot="sh_1", chapter="ch_1")
    assert not d.enabled and d.reason.startswith("no switch")


def test_render_shot_default_path_unchanged(monkeypatch):
    """开关关：每镜 LLM 搭一次景，标题“镜 N：…”，notes 与改造前完全一样，不碰共享舞台。"""
    monkeypatch.delenv("DIRECTOR_WORLD_GREYBOX_ENABLED", raising=False)
    calls: list = []
    db = _wire(monkeypatch, calls)
    monkeypatch.setattr(from_shot, "staged_scene", lambda *a, **k: pytest.fail("shared stage used on default path"))
    with pytest.raises(_Stop):
        from_shot.render_shot(db, "sh_1")
    assert calls[0] == ("plan", "b", 3.0)
    create = next(c for c in calls if c[0] == "create")
    assert create[1] == "镜 3：Tyler slaps Thomas"
    assert create[2] == {"shot_id": "sh_1", "plan_id": "sp_1", "repairs": ["r"]}


def test_render_shot_greybox_path_only_when_switched_on(monkeypatch):
    calls: list = []
    db = _wire(monkeypatch, calls)
    monkeypatch.setattr(switches, "resolve", lambda db, **k: switches.Decision(True, True, "chapter", "test"))
    used = []

    def staged(db, plan, shot, plan_once):
        used.append(1)
        sc, rep = plan_once()
        return sc, rep, False
    monkeypatch.setattr(from_shot, "staged_scene", staged)
    with pytest.raises(_Stop):
        from_shot.render_shot(db, "sh_1")
    assert used and next(c for c in calls if c[0] == "create")[2]["stage_scene_key"] == "sp_1:sc_1"


def test_ltx25_default_union_payload_unchanged():
    """默认 union 控制：不钉首帧时 payload 不带 first_frame（与改造前一致）。"""
    from app.director.renderers.base import RenderRequest
    from app.director.renderers.ltx25 import LTX25Adapter
    ad = LTX25Adapter()
    req = RenderRequest(renderer="ltx_25", prompt="p", control_type="union", control_video="/media/d.mp4",
                        control_videos={"depth": "/media/d.mp4"}, first_frame="/media/f.png", first_frame_styled=True,
                        fps=24, resolution=(768, 448), duration_sec=3.0)
    pay = ad.build_payload(ad.validate(req))
    assert "first_frame" not in pay and pay["control"]["type"] == "union"


def test_camera_gate_precedence_bug_fixed():
    """镜 3 旧判定：缩放撞边界（1.45）但平移够大就过 —— 现在不过。"""
    g = qa.camera_gate({"scale": 1.45, "shift_x": -0.075, "shift_y": 0.0}, "pan_left")
    assert not g["ok"] and "bound" in g["why"]
    ok = qa.camera_gate({"scale": 1.0, "shift_x": -0.05, "shift_y": 0.0}, "pan_left",
                        reference={"scale": 1.0, "shift_x": -0.04, "shift_y": 0.0})
    assert ok["ok"]
    bad = qa.camera_gate({"scale": 1.0, "shift_x": 0.05, "shift_y": 0.0}, "pan_left",
                         reference={"scale": 1.0, "shift_x": -0.04, "shift_y": 0.0})
    assert not bad["ok"]


def test_select_falls_back_to_original(tmp_path):
    from app.worldmodel import pipeline
    orig = tmp_path / "orig.mp4"
    orig.write_bytes(b"x")
    run = SimpleNamespace(id="wpr_t", config={"shots": [{"n": 1}], "fallback_to_original": True},
                          state={"shots": {"1": {"attempts": [{"video": "a.mp4", "qa": {"pass": False, "failed": ["positions"]}}]}}},
                          out_dir=str(tmp_path / "o"), title=None)
    ctx = pipeline.Ctx(SimpleNamespace(commit=lambda: None), run)
    ctx.original_clip = lambda n: str(orig)
    pipeline.select(ctx, {"n": 1})
    assert ctx.rec(1)["final"]["source"] == "original"
    ctx.rec(1)["attempts"][0]["qa"] = {"pass": True, "failed": []}
    pipeline.select(ctx, {"n": 1})
    assert ctx.rec(1)["final"]["source"] == "greybox"
    ctx.rec(1)["override"] = {"source": "original"}
    pipeline.select(ctx, {"n": 1})
    assert ctx.rec(1)["final"]["source"] == "original" and ctx.rec(1)["final"]["why"] == "user override"


def test_llm_delta_proposes_only(monkeypatch):
    from app.worldmodel import llm_build
    seen = {}
    monkeypatch.setattr(llm_build.ws, "snapshot", lambda db, wid: {"regions": []})
    monkeypatch.setattr(llm_build.ws, "propose_delta", lambda db, wid, ops, **kw: seen.setdefault("ops", ops) and SimpleNamespace(id="wd"))
    fake = lambda messages, schema, **kw: {"ops": [{"op": "add_region", "key": "a"},  # noqa: E731
                                                   {"op": "add_fact", "subject_key": "a"},
                                                   {"op": "add_fact", "subject_key": "a", "evidence_span": "x"}]}
    llm_build.propose_chapter_delta(None, "ws", chapter_id="ch", text="t", chat=fake)
    assert [o["op"] for o in seen["ops"]] == ["add_region", "add_fact"]  # 无出处的事实被丢弃
