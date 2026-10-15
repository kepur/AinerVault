"""审片问题记录 v0 合同测试（hub.P1.C2）。

纯 CPU，不导入 MLX/ORT/模型，不读媒体/数据库，不写生产库/RunStore。
外部记录一律经显式 fixtures 映射提供；文件写入只用 pytest tmp_path。
"""
from __future__ import annotations

import copy
import inspect
import json
from pathlib import Path

import pytest

from app.production import review_contract as rc

SCHEMA_SRC = Path(__file__).resolve().parents[4] / "docs" / "v2" / "production_brain" / "review_record_v0.schema.json"

FIXTURES = {
    "fixture:shot5/clip": {"current_revision": "r3"},
    "fixture:suspense/take": {"current_revision": "r3"},
    "fixture:comedy/take": {"current_revision": "r3"},
    "fixture:audio/line": {"current_revision": "r1"},
}


def _binding(**kw):
    base = {
        "plan_id": "fixture-bag-elephant",
        "plan_revision": 0,
        "world_id": "fixture-world",
        "world_version": 1,
        "scene_id": "fixture-scene",
        "scene_revision": 0,
        "take_id": "fixture-suspense",
    }
    base.update(kw)
    return base


def _hard_all(state="pass"):
    return [{"name": n, "state": state} for n in rc.HARD_CONSTRAINTS]


def _dims_all(status="pass", evidence=True):
    return [{"dimension": d, "status": status, "evidence_present": evidence} for d in rc.DIMENSIONS]


def make_issue(**kw):
    base = {
        "protocol": "hub.review/v0",
        "record_kind": "issue",
        "issue_id": "fixture-issue-gaze",
        "standard_version": "v0",
        "binding": _binding(shot_id="fixture-shot-5"),
        "subject": {"kind": "role", "id": "fixture-heroine"},
        "clock": {"clock": "sim_tick", "sim_hz": 120, "start": 180, "end": 240},
        "dimension": "story_character",
        "severity": "major",
        "verdict": "fail",
        "hard_constraint": "none",
        "evidence": [
            {"ref": "fixture:shot5/clip", "digest": "d1",
             "locator": "sim_tick[180,240)", "summary": "揭示后无反应，完整片段已看"}
        ],
        "observed": "揭示后 60 tick 内无注视与反应",
        "expected": "揭示后应注视变形物并给出反应",
        "fix": {"scope": "performance", "path": "/performance/fixture-heroine/reaction",
                "minimal_range": "sim_tick[180,240)"},
        "lock_impact": {"touches_lock": False, "lock_paths": []},
        "reviewer": {"kind": "human", "id": "fixture-reviewer", "is_author": False},
        "inputs": [{"asset_ref": "fixture:shot5/clip", "revision": "r3"}],
    }
    base.update(kw)
    return copy.deepcopy(base)


def make_verdict(**kw):
    base = {
        "protocol": "hub.review/v0",
        "record_kind": "verdict",
        "verdict_id": "fixture-verdict-1",
        "standard_version": "v0",
        "binding": _binding(),
        "hard_constraints": _hard_all("pass"),
        "dimensions": _dims_all("pass", True),
        "overall": "pass",
        "reviewer": {"kind": "human", "id": "fixture-reviewer", "is_author": False},
        "inputs": [{"asset_ref": "fixture:suspense/take", "revision": "r3"}],
        "evaluated_at": "2026-10-15",
    }
    base.update(kw)
    return copy.deepcopy(base)


def make_comparison(**kw):
    base = {
        "protocol": "hub.review/v0",
        "record_kind": "comparison",
        "comparison_id": "fixture-cmp-1",
        "standard_version": "v0",
        "baseline": {"event_id": "fixture-transform", "world_id": "fixture-world",
                     "world_version": 1, "role_ids": ["fixture-heroine"]},
        "candidate_a": {"take_id": "fixture-suspense", "asset_ref": "fixture:suspense/take", "revision": "r3"},
        "candidate_b": {"take_id": "fixture-comedy", "asset_ref": "fixture:comedy/take", "revision": "r3"},
        "preference": "tie",
        "reason": "两者各成立一次，按当前题材目标无法分高下",
        "hard_constraints_checked": True,
        "blind": {"author_hidden": True, "technique_hidden": True, "model_hidden": True,
                  "self_score_hidden": True, "randomized_order": True},
        "reviewer": {"kind": "human", "id": "fixture-judge", "is_author": False},
        "evaluated_at": "2026-10-15",
    }
    base.update(kw)
    return copy.deepcopy(base)


def make_choice(**kw):
    base = {
        "protocol": "hub.review/v0",
        "record_kind": "choice",
        "choice_id": "fixture-choice-1",
        "standard_version": "v0",
        "requirement_ref": "fixture-req-reveal",
        "candidates": [
            {"take_id": "fixture-suspense", "asset_ref": "fixture:suspense/take",
             "revision": "r3", "diff": "慢转头"},
            {"take_id": "fixture-comedy", "asset_ref": "fixture:comedy/take",
             "revision": "r3", "diff": "double-take"},
        ],
        "selected_take_id": "fixture-comedy",
        "user_verbatim": "要第二个，反应更干脆",
        "shown_order": ["fixture-suspense", "fixture-comedy"],
        "chosen_at": "2026-10-15",
        "hard_constraints_preserved": True,
        "grants_license_or_budget": False,
        "reviewer": {"kind": "user", "id": "fixture-user", "is_author": False},
    }
    base.update(kw)
    return copy.deepcopy(base)


def _codes(errors):
    return [e["code"] for e in errors]


# ---- schema 本体（经 tmp_path 中转，不直接断言生产路径写入） ----

def test_schema_loads_and_covers_required_enums(tmp_path):
    text = SCHEMA_SRC.read_text(encoding="utf-8")
    tmp_copy = tmp_path / "review_record_v0.schema.json"
    tmp_copy.write_text(text, encoding="utf-8")
    schema = json.loads(tmp_copy.read_text(encoding="utf-8"))
    assert schema["$defs"]["issue"]["properties"]["dimension"]["enum"] == list(rc.DIMENSIONS)
    assert len(schema["$defs"]["issue"]["properties"]["dimension"]["enum"]) == 7
    hard = schema["$defs"]["verdict"]["properties"]["hard_constraints"]["items"]["properties"]["name"]["enum"]
    assert sorted(hard) == sorted(rc.HARD_CONSTRAINTS)
    assert schema["$defs"]["fix_proposal"]["properties"]["scope"]["enum"] == ["world", "performance", "presentation", "style"]
    pref = schema["$defs"]["comparison"]["properties"]["preference"]["enum"]
    assert set(pref) == {"prefer_a", "prefer_b", "tie", "undecidable"}
    clocks = schema["$defs"]["clock_interval"]["properties"]["clock"]["enum"]
    assert set(clocks) == {"sim_tick", "video_frame", "audio_sample"}
    assert len(schema["examples"]) >= 4


def test_schema_examples_pass_semantics(tmp_path):
    schema = json.loads(SCHEMA_SRC.read_text(encoding="utf-8"))
    log = []
    for ex in schema["examples"]:
        errs = rc.validate_record(copy.deepcopy(ex), FIXTURES)
        log.append({"kind": ex["record_kind"], "errors": errs})
        assert errs == [], f"自带例子应通过语义校验: {errs}"
    (tmp_path / "examples-check.json").write_text(json.dumps(log, ensure_ascii=False), encoding="utf-8")


# ---- 正例 ----

def test_valid_issue_passes():
    assert rc.validate_issue(make_issue(), FIXTURES) == []


def test_valid_verdict_unverified_when_evidence_missing():
    dims = _dims_all("pass", True)
    dims[0] = {"dimension": "intent_genre", "status": "unverified", "evidence_present": False,
               "note": "单帧不足以证明悬疑成立"}
    dims[5] = {"dimension": "sound_performance", "status": "unverified", "evidence_present": False,
               "note": "静音不得给声音通过"}
    v = make_verdict(dimensions=dims, overall="unverified")
    assert rc.validate_verdict(v, FIXTURES) == []


def test_valid_comparison_tie_and_undecidable_pass():
    assert rc.validate_comparison(make_comparison(preference="tie"), FIXTURES) == []
    assert rc.validate_comparison(make_comparison(preference="undecidable", reason="片段缺失，无法判断"), FIXTURES) == []


def test_valid_choice_passes():
    assert rc.validate_choice(make_choice(), FIXTURES) == []


def test_video_frame_and_audio_sample_clocks_pass():
    issue = make_issue(clock={"clock": "video_frame", "fps": 24, "origin_tick": 1200, "start": 10, "end": 20})
    assert rc.validate_clock(issue["clock"]) == []
    issue2 = make_issue(clock={"clock": "audio_sample", "sample_rate": 48000, "anchor_tick": 0, "start": 0, "end": 480})
    assert rc.validate_clock(issue2["clock"]) == []


# ---- 反例 1：时间轴混淆 ----

def test_counterexample_timeline_confusion_frame_as_tick():
    # 把“第 300 帧”直接写成 300 tick，且把 fps 塞进 sim_tick。
    bad = {"clock": "sim_tick", "sim_hz": 120, "start": 300, "end": 310, "fps": 24}
    errs = rc.validate_clock(bad)
    assert "timeline_confusion" in _codes(errs)


def test_counterexample_timeline_confusion_missing_unit_fields():
    no_fps = {"clock": "video_frame", "start": 300, "end": 310}  # 缺 fps/origin：裸帧号不可用
    errs = rc.validate_clock(no_fps)
    assert errs != []
    issue = make_issue(clock={"clock": "video_frame", "start": 300, "end": 310})
    assert rc.validate_issue(issue, FIXTURES) != []


def test_counterexample_inverted_interval_rejected():
    bad = {"clock": "sim_tick", "sim_hz": 120, "start": 240, "end": 240}  # 空区间违反左闭右开
    assert "invalid_interval" in _codes(rc.validate_clock(bad))


# ---- 反例 2：旧媒体身份 ----

def test_counterexample_stale_media_input():
    issue = make_issue(inputs=[{"asset_ref": "fixture:shot5/clip", "revision": "r2"}])
    errs = rc.validate_issue(issue, FIXTURES)
    assert "stale_media" in _codes(errs)


def test_counterexample_stale_media_candidate():
    cmp = make_comparison()
    cmp["candidate_b"] = {"take_id": "fixture-comedy", "asset_ref": "fixture:comedy/take", "revision": "r1"}
    assert "stale_media" in _codes(rc.validate_comparison(cmp, FIXTURES))


# ---- 反例 3：作者自评作为晋升 ----

def test_counterexample_self_review_promotion_verdict():
    v = make_verdict(supports_promotion=True,
                     reviewer={"kind": "human", "id": "fixture-author", "is_author": True})
    assert "self_promotion" in _codes(rc.validate_verdict(v, FIXTURES))


def test_counterexample_self_review_promotion_comparison():
    cmp = make_comparison(supports_promotion=True,
                          reviewer={"kind": "human", "id": "fixture-author", "is_author": True})
    assert "self_promotion" in _codes(rc.validate_comparison(cmp, FIXTURES))


def test_counterexample_nonblind_promotion_rejected():
    blind = {"author_hidden": False, "technique_hidden": True, "model_hidden": True,
             "self_score_hidden": True, "randomized_order": True}
    cmp = make_comparison(supports_promotion=True, blind=blind)
    assert "self_promotion" in _codes(rc.validate_comparison(cmp, FIXTURES))


# ---- 反例 4：缺证据假绿 ----

def test_counterexample_missing_evidence_false_green():
    dims = _dims_all("pass", True)
    dims[5] = {"dimension": "sound_performance", "status": "pass", "evidence_present": False}
    v = make_verdict(dimensions=dims, overall="pass")
    assert "missing_evidence" in _codes(rc.validate_verdict(v, FIXTURES))


def test_counterexample_empty_evidence_issue():
    issue = make_issue(evidence=[])
    assert "missing_evidence" in _codes(rc.validate_issue(issue, FIXTURES))


def test_counterexample_blocker_overridden_by_scores():
    hard = _hard_all("pass")
    hard[1] = {"name": "identity", "state": "fail", "note": "跨镜身份不一致"}
    v = make_verdict(hard_constraints=hard, overall="pass")
    assert "blocker_overridden" in _codes(rc.validate_verdict(v, FIXTURES))
    v2 = make_verdict(hard_constraints=hard, overall="unverified")
    assert "blocker_overridden" in _codes(rc.validate_verdict(v2, FIXTURES))


# ---- 反例 5：修改锁定字段 ----

def test_counterexample_silent_lock_edit():
    issue = make_issue(
        fix={"scope": "performance", "path": "/world/actor/position", "minimal_range": "sim_tick[180,240)"},
        lock_impact={"touches_lock": False, "lock_paths": []},
    )
    errs = rc.validate_issue(issue, FIXTURES, known_locks=["/world/actor/position"])
    assert "lock_violation" in _codes(errs)


def test_counterexample_lock_claim_without_paths():
    issue = make_issue(lock_impact={"touches_lock": True, "lock_paths": []})
    assert "lock_violation" in _codes(rc.validate_issue(issue, FIXTURES))


def test_declared_lock_edit_passes():
    issue = make_issue(
        fix={"scope": "performance", "path": "/world/actor/position", "minimal_range": "sim_tick[180,240)"},
        lock_impact={"touches_lock": True, "lock_paths": ["/world/actor/position"]},
    )
    assert rc.validate_issue(issue, FIXTURES, known_locks=["/world/actor/position"]) == []


# ---- 其他封口规则 ----

def test_world_fix_requires_new_version():
    issue = make_issue(fix={"scope": "world", "path": "/world/props/bag", "minimal_range": "eventioane"})
    assert "invalid_scope" in _codes(rc.validate_issue(issue, FIXTURES))
    ok = make_issue(fix={"scope": "world", "path": "/world/props/bag", "minimal_range": "event",
                         "world_new_version_required": True})
    assert rc.validate_issue(ok, FIXTURES) == []


def test_blocker_issue_must_name_constraint():
    issue = make_issue(severity="blocker", verdict="fail", hard_constraint="none")
    assert "blocker_without_constraint" in _codes(rc.validate_issue(issue, FIXTURES))
    ok = make_issue(severity="blocker", verdict="fail", hard_constraint="identity")
    assert rc.validate_issue(ok, FIXTURES) == []


def test_unmapped_external_ref_rejected():
    issue = make_issue(inputs=[{"asset_ref": "fixture:ghost/clip", "revision": "r9"}])
    assert "unmapped_ref" in _codes(rc.validate_issue(issue, FIXTURES))


def test_fabricated_score_rejected():
    issue = make_issue()
    issue["evidence"] = [{"ref": "fixture:shot5/clip", "summary": "ok", "score": 80}]
    assert "fabricated_score" in _codes(rc.validate_issue(issue, FIXTURES))


def test_choice_does_not_revoke_hard_constraints():
    bad = make_choice(hard_constraints_preserved=False)
    assert "blocker_overridden" in _codes(rc.validate_choice(bad, FIXTURES))
    bad2 = make_choice(grants_license_or_budget=True)
    assert "blocker_overridden" in _codes(rc.validate_choice(bad2, FIXTURES))


def test_no_scoring_or_promotion_helpers():
    src = inspect.getsource(rc)
    assert "def score" not in src and "auto_promote" not in src
    summary = rc.summarize_verdict(make_verdict())
    assert set(summary) == {"overall", "hard_fail", "hard_unverified", "dim_fail", "dim_unverified"}


def test_module_has_no_io_or_model_imports():
    src = inspect.getsource(rc)
    for token in ("import sqlalchemy", "import mlx", "import ort", "from mlx", "open(", "sqlite", "psycopg"):
        assert token not in src, token


def test_dispatcher_rejects_unknown_kind():
    errs = rc.validate_record({"record_kind": "final_cut", "protocol": "hub.review/v0"}, FIXTURES)
    assert errs != [] and errs[0]["code"] == "schema_violation"
