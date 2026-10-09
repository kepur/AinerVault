"""快速成片：想法拆镜、几镜叠一次 LTX 生成的帧位和分段。"""
from __future__ import annotations

import pytest

from app.pipelines import director_review as dr
from app.pipelines import quick_film as qf


def test_take_layout_squeezes_into_the_ltx_limit():
    assert qf.take_layout([3, 4, 2]) == [(0, 3000), (3000, 7000), (7000, 9000)]
    long = qf.take_layout([5, 5, 5, 5], max_ms=10000)
    assert long[-1][1] == 10000 and [b - a for a, b in long] == [2500] * 4


def test_one_take_pins_every_shot_at_its_start_frame():
    p = qf.one_take_payload(["f0", "f1", "f2"], ["Run.", "Fall.", "Laugh."], [3, 4, 2], "wind and snow")
    assert p["first_frame"] == {"url": "f0"}
    assert [(k["image"]["url"], k["frame_idx"]) for k in p["keyframes"]] == [("f1", 72), ("f2", 168)]
    assert p["segments"] == [{"prompt": "Run.", "start_ms": 0, "end_ms": 3000},
                             {"prompt": "Fall.", "start_ms": 3000, "end_ms": 7000},
                             {"prompt": "Laugh.", "start_ms": 7000, "end_ms": 9000}]
    assert p["duration_ms"] == 9000 and p["audio"] == {"mode": "generate"} and p["prompt"].startswith("Run. Fall. Laugh.")
    assert "wind and snow" in p["prompt"]


def test_plan_idea_cleans_the_llm_output(monkeypatch):
    out = ('<think>…</think>{"title": "第一次滑雪", "scene": "A snowy ski slope", "look": "red ski suit", "audio": "wind",'
           ' "shots": [{"size": "WS", "first_frame": "Wide shot. The girl at the top.", "motion": "She pushes off.", "seconds": 9},'
           ' {"size": "cu", "first_frame": "Close-up of her face.", "motion": "She laughs.", "seconds": 1},'
           ' {"size": "ms", "first_frame": ""}, "junk"]}')
    monkeypatch.setattr(dr, "_chat", lambda *a, **k: (out, "qwen3.6"))
    plan = qf.plan_idea(None, "她第一次滑雪", 3, has_outfit=False, has_scene=False)
    assert plan["title"] == "第一次滑雪" and plan["model"] == "qwen3.6"
    assert [s["size"] for s in plan["shots"]] == ["ws", "cu"], "空首帧、非对象的丢掉"
    assert [s["seconds"] for s in plan["shots"]] == [5.0, 2.0], "每镜 2–5 秒"


def test_plan_without_shots_fails_loudly(monkeypatch):
    monkeypatch.setattr(dr, "_chat", lambda *a, **k: ('{"shots": []}', "m"))
    with pytest.raises(RuntimeError):
        qf.plan_idea(None, "x", 2, has_outfit=False, has_scene=False)


def test_get_video_and_last_frame_resolves_correctly(monkeypatch):
    from unittest.mock import MagicMock
    from app.models import GenTask, TaskStatus, Asset, AssetKind

    mock_db = MagicMock()
    mock_task = GenTask(
        id="gt_test",
        status=TaskStatus.succeeded,
        result_json={"last_frame": {"url": "http://localhost:8100/media/test_lf.png"}},
    )

    vid_asset = Asset(id="as_vid", kind=AssetKind.video, url="http://localhost:8100/media/test.mp4")
    lf_asset = Asset(id="as_lf", kind=AssetKind.image, url="http://localhost:8100/media/test_lf.png")

    mock_db.execute.return_value.scalars.return_value.first.side_effect = [vid_asset, lf_asset]

    vid, lf = qf._get_video_and_last_frame(mock_db, mock_task)
    assert vid == ("as_vid", "http://localhost:8100/media/test.mp4")
    assert lf == ("as_lf", "http://localhost:8100/media/test_lf.png")
