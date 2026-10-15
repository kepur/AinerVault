"""hub.P1.C3 独立探针：重建输入 + 7 个作者未覆盖的新反例 + 变异敏感性。

只读核对 hub.P1.C2，不改源码。fixtures 与记录全部独立重建（c3 命名空间），
不复用作者测试的辅助函数。每个反例断言真实错误码；变异段证明检查是负载性的：
换上恒过桩后，坏 verdict 应不再被拒（探针据此判定桩可检出），恢复后重现拒收。

用法：PYTHONPATH=code/apps/ainer-core .venv/bin/python \
  reports/V-production-review-contract/probe_counterexamples.py
输出 JSON 行；全部符合预期则 exit 0，否则非零。
"""
import copy
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "code" / "apps" / "ainer-core"))

from app.production import review_contract as rc  # noqa: E402

assert "review_contract" in rc.__name__, rc
SRC = Path(rc.__file__).resolve()
assert str(SRC).startswith(str(REPO)), SRC

# 独立 fixtures（c3 命名空间，与作者 fixture-* 无交集）。
FIX = {
    "c3:shot/clip": {"current_revision": "r5", "sha256": "a" * 64},
    "c3:suspense/take": {"current_revision": "r5"},
    "c3:comedy/take": {"current_revision": "r5"},
}

ROWS = []


def check(cid, desc, errors, expect_code):
    codes = [e.get("code") for e in errors]
    ok = expect_code in codes
    ROWS.append({"id": cid, "desc": desc, "expect": expect_code,
                 "codes": codes, "pass": ok,
                 "errors": errors[:4]})
    return ok


def check_empty(cid, desc, errors):
    ok = errors == []
    ROWS.append({"id": cid, "desc": desc, "expect": "empty",
                 "codes": [e.get("code") for e in errors], "pass": ok,
                 "errors": errors[:4]})
    return ok


def binding(**kw):
    b = {"plan_id": "c3-bag-elephant", "plan_revision": 2, "world_id": "c3-world",
         "world_version": 3, "scene_id": "c3-scene", "scene_revision": 1,
         "take_id": "c3-suspense"}
    b.update(kw)
    return b


def issue(**kw):
    d = {"protocol": "hub.review/v0", "record_kind": "issue",
         "issue_id": "c3-issue-1", "standard_version": "v0",
         "binding": binding(shot_id="c3-shot-7"),
         "subject": {"kind": "role", "id": "c3-heroine"},
         "clock": {"clock": "sim_tick", "sim_hz": 120, "start": 600, "end": 720},
         "dimension": "story_character", "severity": "major", "verdict": "fail",
         "hard_constraint": "none",
         "evidence": [{"ref": "c3:shot/clip", "digest": "c3-d7",
                       "locator": "sim_tick[600,720)", "summary": "揭示后无反应，完整片段已看"}],
         "observed": "揭示后 120 tick 内无注视与反应",
         "expected": "揭示后应注视变形物并给出反应",
         "fix": {"scope": "performance", "path": "/performance/c3-heroine/reaction",
                 "minimal_range": "sim_tick[600,720)"},
         "lock_impact": {"touches_lock": False, "lock_paths": []},
         "reviewer": {"kind": "human", "id": "c3-reviewer", "is_author": False},
         "inputs": [{"asset_ref": "c3:shot/clip", "revision": "r5", "sha256": "a" * 64}]}
    d.update(kw)
    return copy.deepcopy(d)


def verdict(**kw):
    d = {"protocol": "hub.review/v0", "record_kind": "verdict",
         "verdict_id": "c3-verdict-1", "standard_version": "v0",
         "binding": binding(),
         "hard_constraints": [{"name": n, "state": "pass"} for n in rc.HARD_CONSTRAINTS],
         "dimensions": [{"dimension": x, "status": "pass", "evidence_present": True}
                        for x in rc.DIMENSIONS],
         "overall": "pass",
         "reviewer": {"kind": "human", "id": "c3-reviewer", "is_author": False},
         "inputs": [{"asset_ref": "c3:suspense/take", "revision": "r5"}],
         "evaluated_at": "2026-10-15"}
    d.update(kw)
    return copy.deepcopy(d)


def comparison(**kw):
    d = {"protocol": "hub.review/v0", "record_kind": "comparison",
         "comparison_id": "c3-cmp-1", "standard_version": "v0",
         "baseline": {"event_id": "c3-transform", "world_id": "c3-world",
                      "world_version": 3, "role_ids": ["c3-heroine"]},
         "candidate_a": {"take_id": "c3-suspense", "asset_ref": "c3:suspense/take",
                         "revision": "r5"},
         "candidate_b": {"take_id": "c3-comedy", "asset_ref": "c3:comedy/take",
                         "revision": "r5"},
         "preference": "tie", "reason": "两者各成立一次，当前题材目标无法分高下",
         "hard_constraints_checked": True,
         "blind": {"author_hidden": True, "technique_hidden": True,
                   "model_hidden": True, "self_score_hidden": True,
                   "randomized_order": True},
         "reviewer": {"kind": "human", "id": "c3-judge", "is_author": False},
         "evaluated_at": "2026-10-15"}
    d.update(kw)
    return copy.deepcopy(d)


def choice(**kw):
    d = {"protocol": "hub.review/v0", "record_kind": "choice",
         "choice_id": "c3-choice-1", "standard_version": "v0",
         "requirement_ref": "c3-req-reveal",
         "candidates": [
             {"take_id": "c3-suspense", "asset_ref": "c3:suspense/take",
              "revision": "r5", "diff": "慢转头"},
             {"take_id": "c3-comedy", "asset_ref": "c3:comedy/take",
              "revision": "r5", "diff": "double-take"}],
         "selected_take_id": "c3-comedy", "user_verbatim": "要第二个，反应更干脆",
         "shown_order": ["c3-suspense", "c3-comedy"], "chosen_at": "2026-10-15",
         "hard_constraints_preserved": True, "grants_license_or_budget": False,
         "reviewer": {"kind": "user", "id": "c3-user", "is_author": False}}
    d.update(kw)
    return copy.deepcopy(d)


ok_all = True
# ── 正例对照（4 个，证明探针输入本身合法，非空转） ──
ok_all &= check_empty("P1", "有效 issue 通过", rc.validate_issue(issue(), FIX))
ok_all &= check_empty("P2", "有效 verdict 通过", rc.validate_verdict(verdict(), FIX))
ok_all &= check_empty("P3", "有效 comparison 通过", rc.validate_comparison(comparison(), FIX))
ok_all &= check_empty("P4", "有效 choice 通过", rc.validate_choice(choice(), FIX))

# ── 7 个新反例（作者 29 测试未覆盖；见报告对照表） ──
c = comparison()
c["candidate_b"] = dict(c["candidate_a"])  # 同一 take 冒充双候选
ok_all &= check("N1", "comparison 双候选同一 take", rc.validate_comparison(c, FIX), "same_take")

c = comparison(hard_constraints_checked=False)  # 未先查硬约束
ok_all &= check("N2", "comparison 未查硬约束", rc.validate_comparison(c, FIX),
                "hard_constraints_skipped")

c = choice(reviewer={"kind": "model", "id": "c3-model", "is_author": False})
ok_all &= check("N3", "choice 非 user 记录用户选择", rc.validate_choice(c, FIX),
                "wrong_reviewer")

c = choice(selected_take_id="c3-ghost")
ok_all &= check("N4", "choice 所选不在候选内", rc.validate_choice(c, FIX),
                "unknown_selection")

v = verdict()  # 硬约束一条 unverified 却 overall=pass
v["hard_constraints"][4] = {"name": "license", "state": "unverified",
                            "note": "许可来源待查"}
ok_all &= check("N5", "verdict 硬 unverified 却总体 pass",
                rc.validate_verdict(v, FIX), "missing_evidence")

bad_inp = issue(inputs=[{"asset_ref": "c3:shot/clip", "revision": "r5",
                         "sha256": "b" * 64}])  # 版本对但字节身份错
ok_all &= check("N6", "input sha 与 fixture 登记不一致",
                rc.validate_issue(bad_inp, FIX), "stale_media")

bad_lock = issue(lock_impact={"touches_lock": False, "lock_paths": ["/world/actor/x"]})
ok_all &= check("N7", "touches_lock=false 却列 lock_paths",
                rc.validate_issue(bad_lock, FIX), "lock_violation")

# ── 变异敏感性：换上恒过桩，坏 verdict 应漏网（证明探针非空转） ──
mut_detected = False
mut_detail = ""
try:
    hard = [{"name": n, "state": "pass"} for n in rc.HARD_CONSTRAINTS]
    hard[1] = {"name": "identity", "state": "fail", "note": "跨镜身份不一致"}
    bad_v = verdict(hard_constraints=hard, overall="pass")
    real_codes = [e.get("code") for e in rc.validate_verdict(bad_v, FIX)]
    orig = rc.validate_verdict
    try:
        rc.validate_verdict = lambda data, fixtures: []  # noqa: E731 故意坏实现：恒过
        stub_codes = [e.get("code") for e in rc.validate_verdict(bad_v, FIX)]
    finally:
        rc.validate_verdict = orig
    recheck = [e.get("code") for e in rc.validate_verdict(bad_v, FIX)]
    mut_detected = ("blocker_overridden" in real_codes
                    and "blocker_overridden" not in stub_codes
                    and "blocker_overridden" in recheck)
    mut_detail = f"real={real_codes} stub={stub_codes} restored={recheck}"
except Exception as exc:  # noqa: BLE001
    mut_detail = f"mutation harness error: {type(exc).__name__}: {exc}"

ROWS.append({"id": "MUT", "desc": "恒过桩下坏 verdict 漏网且恢复后重现（敏感性）",
             "expect": "stub misses blocker_overridden, restore catches",
             "detail": mut_detail, "pass": bool(mut_detected)})
ok_all = ok_all and mut_detected

for r in ROWS:
    print(json.dumps(r, ensure_ascii=False))

print(json.dumps({"new_counterexamples": 7, "positives": 4,
                  "all_hold": bool(ok_all)}, ensure_ascii=False))
sys.exit(0 if ok_all else 1)
