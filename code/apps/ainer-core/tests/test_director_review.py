"""导演审片 + 关键帧挑图：解析、编号映射、出片提示词顺序、挑图失败兜底、编排器开关。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.pipelines import canvas_run as cr
from app.pipelines import director_review as dr
from app.pipelines import frame_select as fsel


def test_parse_json_skips_thinking_and_fences():
    text = '<think>who is the leader? {"no": 1}</think>\n```json\n{"shots": [{"shot": "s1"}], "continuity": []}\n```'
    assert dr.parse_json(text)["shots"][0]["shot"] == "s1"
    with pytest.raises(dr.ReviewError):
        dr.parse_json("sorry, no json")


def test_apply_review_maps_aliases_and_keeps_original_text():
    shots = [SimpleNamespace(id="sh_a", order_no=5, camera_json={"move": "static"}),
             SimpleNamespace(id="sh_b", order_no=6, camera_json=None)]
    data = {"shots": [
        {"shot": "s1", "cast": ["c2", "c1", "c9", "c3", "c4"], "focus": "c2", "first_frame": "Medium shot. A tall boy...",
         "last_frame": "...", "motion": "The tall boy slaps...", "issues": ["领头少年是高个少年，不是李爽"]},
        {"shot": "s2", "cast": ["c1"], "focus": "c7", "first_frame": "Close-up of...", "motion": "He shouts."},
        {"shot": "s9", "first_frame": "nope"},
        {"shot": "s2", "first_frame": ""},
    ]}
    out = dr.apply_review(shots, data, {"s1": "sh_a", "s2": "sh_b"},
                          {"c1": "e_victim", "c2": "e_tyler", "c3": "e_brad", "c4": "e_x"}, "qwen3.6")
    a, b = shots[0].camera_json, shots[1].camera_json
    assert a["move"] == "static", "审片挂在 review 下，不动分镜原有字段"
    assert a["review"]["cast"] == ["e_tyler", "e_victim", "e_brad"], "不认识的编号丢掉，最多 3 人"
    assert a["review"]["focus"] == "e_tyler" and a["review"]["model"] == "qwen3.6"
    assert b["review"]["focus"] == "e_victim", "焦点不在画面里就退回第一个人"
    assert [r["order_no"] for r in out] == [5, 6] and out[0]["issues"]
    assert dr.review_of(shots[0])["first_frame"].startswith("Medium shot")
    assert dr.review_of(SimpleNamespace(camera_json={"review": {"first_frame": ""}})) is None


def test_reviewed_motion_leads_the_ltx_prompt():
    from app.pipelines.ltx25_shots import shot_prompt

    p = shot_prompt(SimpleNamespace(prompt="Medium shot, eye level, slow pan right"), SimpleNamespace(motion_prompt_en="Old motion."),
                    [], ["character (1)"], characters=["a tall boy in a denim jacket"], style="Live-action film.",
                    lead="The tall boy slaps the thin boy across the face. Slow push-in.")
    assert p.startswith("The tall boy slaps"), "LTX 官方：第一句写主要动作"
    assert "slow pan right" not in p and "Old motion." not in p, "审过就不再拼分镜原文（两套说法会打架）"
    assert "character (1) speaks" in p and "a tall boy in a denim jacket" in p
    old = shot_prompt(SimpleNamespace(prompt="Medium shot"), SimpleNamespace(motion_prompt_en="He walks."), [], [])
    assert "He walks." in old, "没审过的照旧"


def test_review_runs_once_and_only_for_keyframe():
    assert cr._needs_review({"method": "keyframe", "review": True})
    assert not cr._needs_review({"method": "keyframe"}), "老的 run 没有 review 键：不补审"
    assert not cr._needs_review({"method": "keyframe", "review": True, "reviewed": 1.0})
    assert not cr._needs_review({"method": "keyframe", "review": False})
    assert not cr._needs_review({"method": "director", "review": True})


def test_pick_falls_back_to_first_candidate(monkeypatch):
    def boom(*_a, **_k):
        raise dr.ReviewError("LM Studio 没开")

    monkeypatch.setattr(fsel, "_chat", boom)
    got = fsel.pick(None, [("Brad — reference portrait", "http://x/media/a.png")], ["u0", "u1"], "Medium shot")
    assert got["best"] == 0 and "没做成" in got["reason"]
    assert fsel.pick(None, [], ["only"], "x")["best"] == 0


def test_pick_reads_the_models_choice(monkeypatch):
    monkeypatch.setattr(fsel, "_chat", lambda *_a, **_k: ('{"best": 1, "reason": "候选 0 多了一个人", "problems": ["0：人重复"]}', "qwen3.6"))
    got = fsel.pick(None, [], ["http://x/a.png", "http://x/b.png"], "Two boys")
    assert got == {"best": 1, "reason": "候选 0 多了一个人", "problems": ["0：人重复"], "model": "qwen3.6"}
    monkeypatch.setattr(fsel, "_chat", lambda *_a, **_k: ('{"best": 5}', "m"))
    assert fsel.pick(None, [], ["a", "b"], "x")["best"] == 0, "挑了不存在的编号：兜底第一张"


def test_vision_message_lists_refs_then_candidates():
    parts = fsel.build_message([("Brad", "http://remote/a.png")], ["http://remote/c0.png", "http://remote/c1.png"], "Two boys")
    texts = [p["text"] for p in parts if p["type"] == "text"]
    assert texts[0].startswith("Reference image 0: Brad") and texts[1] == "Candidate 0:" and texts[2] == "Candidate 1:"
    assert "exactly 2 candidates" in texts[-1]
    assert sum(p["type"] == "image_url" for p in parts) == 3
