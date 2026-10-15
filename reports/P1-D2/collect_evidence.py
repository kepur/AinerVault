#!/usr/bin/env python3
"""hub.P1.D2 证据采集：身份 SHA、命令/退出码、反例矩阵、能力表 fixture。

纯 CPU、只读输入；只写 reports/P1-D2/evidence.json。复用测试模块里的 fixture 构造函数，
保证证据与 tests/test_production_performance_contract.py 用的是同一套输入。

用法：
    cd code/apps/ainer-core
    PYTHONDONTWRITEBYTECODE=1 ../../../.venv/bin/python ../../../reports/P1-D2/collect_evidence.py
"""
from __future__ import annotations

import copy
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
APP = REPO / "code/apps/ainer-core"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(APP.parents[0]))  # code/apps：让 tests 包可导入

from app.production import performance_contract as pc  # noqa: E402
from tests import test_production_performance_contract as tf  # noqa: E402

OUT = REPO / "reports" / "P1-D2" / "evidence.json"
D1_INDEPENDENT_R2 = REPO / "reports" / "production-brain" / "D1-independent-r2" / "results.json"


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(path: Path) -> dict:
    return {"path": str(path), "sha256": sha256_of(path), "bytes": path.stat().st_size}


def counterexamples() -> list[dict]:
    """反例矩阵：每一项独立执行，记录期望码与实际码。"""
    caps = tf.fixture_capabilities()
    rows: list[dict] = []

    def add(name: str, result: pc.ValidationResult, expect: str, note: str = "") -> None:
        codes = result.error_codes()
        if expect == "ok":
            passed = result.ok
        else:
            passed = expect in codes
        rows.append(
            {
                "case": name,
                "expect": expect,
                "actual_codes": codes,
                "paths": [item["path"] for item in result.errors][:6],
                "executable": result.executable,
                "pass": passed,
                "note": note,
            }
        )

    # 1 相同部位双写
    request, response = tf._two_curves(
        tf.fixture_curve(),
        tf.fixture_curve(owner={"kind": "runtime", "id": "fixture-runtime", "authorization_ref": "fixture-ref"}),
    )
    add("same-body-part-double-write", pc.validate_response(response, request, capabilities=caps, executed_tick_ranges=[]), "control_conflict")

    # 2 以换名字绕锁（别名展开后仍命中）
    lock_request = tf.fixture_request(locks=[{"path": "/world/actor/head", "by": "fixture-user", "reason": "user-lock"}])
    add(
        "rename-alias-around-lock",
        pc.validate_response(
            tf.fixture_response(lock_request, [tf.fixture_curve(body_part="cranium")]),
            lock_request,
            capabilities=caps,
        ),
        "lock_conflict",
    )
    # 2b 用控制器路径换名字绕锁
    add(
        "controller-token-around-lock",
        pc.validate_response(
            tf.fixture_response(lock_request, [tf.fixture_curve(body_part="cranium", controller_ref="fixture:ctl/head/turn")]),
            lock_request,
            capabilities=caps,
        ),
        "lock_conflict",
    )

    # 3/4 NaN / Inf
    for label, bad in (("nan-value", float("nan")), ("inf-value", float("inf")), ("neg-inf-value", float("-inf"))):
        curve = tf.fixture_curve()
        curve["keyframes"][1]["value"] = bad
        add(label, pc.validate_response(tf.fixture_response(tf.fixture_request(), [curve]), tf.fixture_request(), capabilities=caps), "out_of_range")

    # 5 负 / 逆时长
    request = tf.fixture_request()
    request["duration_ticks"] = -600
    add("negative-duration", pc.validate_request(request), "invalid_time_curve")
    request = tf.fixture_request()
    request["duration_ticks"] = 0
    add("zero-duration", pc.validate_request(request), "invalid_time_curve")

    # 6 逆序阶段
    curve = tf.fixture_curve()
    curve["phases"]["arrival_end_tick"] = 30
    add("inverted-phases", pc.validate_response(tf.fixture_response(tf.fixture_request(), [curve]), tf.fixture_request(), capabilities=caps), "invalid_time_curve")

    # 7 24Hz 冒充 120Hz
    request = tf.fixture_request()
    request["binding"]["sim_hz"] = 24
    add("sim-hz-24-as-120", pc.validate_request(request), "invalid_time_curve")
    request = tf.fixture_request()
    response = tf.fixture_response(request, [tf.fixture_curve()])
    response["binding"]["render_fps"] = 120
    add("render-fps-swap-120", pc.validate_response(response, request, capabilities=caps), "invalid_time_curve")

    # 8 一拍二硬写成每 2 tick
    curve = tf.fixture_curve(
        phases={"start_tick": 0, "anticipation_end_tick": 2, "arrival_end_tick": 4, "hold_end_tick": 598, "end_tick": 600},
        keyframes=[{"tick": 0, "value": 0}, {"tick": 2, "value": 30}, {"tick": 600, "value": 0}],
    )
    add("twos-as-2-ticks", pc.validate_response(tf.fixture_response(tf.fixture_request(), [curve]), tf.fixture_request(), capabilities=caps), "invalid_time_curve")

    # 9 未实现口型写成功
    mouth = tf.fixture_curve(channel="mouth", body_part="face", unit="normalized", controller_ref="fixture:ctl/mouth/shape")
    mouth["keyframes"] = [{"tick": 0, "value": 0}, {"tick": 5, "value": 0.5}, {"tick": 600, "value": 0}]
    mouth["phases"] = {"start_tick": 0, "anticipation_end_tick": 5, "arrival_end_tick": 10, "hold_end_tick": 590, "end_tick": 600}
    add("mouth-without-audio", pc.validate_response(tf.fixture_response(tf.fixture_request(), [mouth]), tf.fixture_request(), capabilities=caps, executed_tick_ranges=[]), "missing_audio_alignment")

    # 10/11 pending:D5 被执行 / 能力表把占位登记为可执行
    pending = tf.fixture_curve(
        controller_ref="pending:D5/face/hesitant",
        mapping_status="pending_D5",
        execution_status="candidate",
        unsupported_reason=None,
    )
    add("pending-d5-claimed-executable", pc.validate_response(tf.fixture_response(tf.fixture_request(), [pending]), tf.fixture_request(), capabilities=caps), "unsupported_action")
    table = tf.fixture_capabilities()
    table["controllers"]["pending:D5/face/hesitant"] = {"unit": "normalized", "executable": True}
    pending_ok = tf.fixture_curve(
        controller_ref="pending:D5/face/hesitant",
        mapping_status="pending_D5",
        execution_status="unsupported",
        unsupported_reason="D5 controller registry not available",
        body_part="face",
        unit="normalized",
        keyframes=[
            {"tick": 0, "value": 0},
            {"tick": 60, "value": 0.5},
            {"tick": 180, "value": 0.5},
            {"tick": 420, "value": 0},
            {"tick": 600, "value": 0},
        ],
    )
    add("placeholder-registered-executable", pc.validate_response(tf.fixture_response(tf.fixture_request(), [pending_ok]), tf.fixture_request(), capabilities=table), "unsupported_action")

    # 12 重复 / 未覆盖 keyframe
    curve = tf.fixture_curve()
    curve["keyframes"] = [{"tick": 0, "value": 0}, {"tick": 180, "value": 30}, {"tick": 180, "value": 20}, {"tick": 600, "value": 0}]
    add("duplicate-keyframe-tick", pc.validate_response(tf.fixture_response(tf.fixture_request(), [curve]), tf.fixture_request(), capabilities=caps), "invalid_time_curve")
    curve = tf.fixture_curve()
    curve["keyframes"] = [{"tick": 10, "value": 0}, {"tick": 600, "value": 0}]
    add("keyframes-not-covering-range", pc.validate_response(tf.fixture_response(tf.fixture_request(), [curve]), tf.fixture_request(), capabilities=caps), "invalid_time_curve")

    # 13 unknown_controller / 缺能力表
    add(
        "unknown-controller",
        pc.validate_response(
            tf.fixture_response(tf.fixture_request(), [tf.fixture_curve(controller_ref="fixture:ctl/unknown")]),
            tf.fixture_request(),
            capabilities=caps,
        ),
        "unknown_controller",
    )
    add(
        "registered-without-capability-table",
        pc.validate_response(tf.fixture_response(tf.fixture_request(), [tf.fixture_curve()]), tf.fixture_request()),
        "unknown_controller",
    )

    # 14 值域 / 单位 / 维度
    curve = tf.fixture_curve()
    curve["keyframes"][1]["value"] = 400.0
    add("value-out-of-registered-range", pc.validate_response(tf.fixture_response(tf.fixture_request(), [curve]), tf.fixture_request(), capabilities=caps), "out_of_range")
    curve = tf.fixture_curve(unit="normalized")
    add("unit-mismatch", pc.validate_response(tf.fixture_response(tf.fixture_request(), [curve]), tf.fixture_request(), capabilities=caps), "out_of_range")
    curve = tf.fixture_curve()
    curve["keyframes"] = [{"tick": 0, "value": [0, 0]}, {"tick": 600, "value": 1}]
    add("vector-dim-mismatch", pc.validate_response(tf.fixture_response(tf.fixture_request(), [curve]), tf.fixture_request(), capabilities=caps), "out_of_range")

    # 15 旧版本 / 身份 / 已执行区间
    request = tf.fixture_request()
    response = tf.fixture_response(request, [tf.fixture_curve()])
    request["binding"]["plan_revision"] = 3
    add("stale-plan-revision", pc.validate_response(response, request, capabilities=caps), "stale_revision")
    request = tf.fixture_request()
    response = tf.fixture_response(request, [tf.fixture_curve()])
    response["binding"]["actor_id"] = "fixture-other"
    add("actor-mismatch", pc.validate_response(response, request, capabilities=caps), "unknown_actor")
    request = tf.fixture_request()
    response = tf.fixture_response(request, [tf.fixture_curve()])
    add("changed-past-overlap", pc.validate_response(response, request, capabilities=caps, executed_tick_ranges=[(300, 700)]), "changed_past")

    # 16 非法锁 Pointer
    request = tf.fixture_request(locks=[{"path": "world/actor", "by": "fixture-user", "reason": "user-lock"}])
    add("lock-pointer-no-slash", pc.validate_request(request), "lock_conflict")
    request = tf.fixture_request(locks=[{"path": "/bad~2escape", "by": "fixture-user", "reason": "user-lock"}])
    add("lock-pointer-bad-escape", pc.validate_request(request), "lock_conflict")
    return rows


def positive_controls() -> list[dict]:
    caps = tf.fixture_capabilities()
    request = tf.fixture_request()
    ok_exec = pc.validate_response(
        tf.fixture_response(request, [tf.fixture_curve()]), request, capabilities=caps, executed_tick_ranges=[]
    )
    blocked = pc.validate_response(
        tf.fixture_response(request, [tf.fixture_curve()]), request, capabilities=caps, executed_tick_ranges=None
    )
    unbound = pc.validate_response(
        tf.fixture_response(request, [tf.fixture_curve()]), None, capabilities=caps, executed_tick_ranges=[]
    )
    examples = []
    for take in tf.TAKES:
        result = pc.validate_response(
            tf.example_response(take), tf.example_request(take), executed_tick_ranges=[]
        )
        examples.append(
            {
                "take": take,
                "ok": result.ok,
                "executable": result.executable,
                "proposed_curves": result.proposed_curves,
                "executable_curves": result.executable_curves,
                "mapping_status": [curve["mapping_status"] for curve in tf.example_response(take)["curves"]],
                "execution_status": [curve["execution_status"] for curve in tf.example_response(take)["curves"]],
            }
        )
    return [
        {
            "case": "registered-fixture-with-explicit-executed-ranges",
            "ok": ok_exec.ok,
            "executable": ok_exec.executable,
            "expected": "ok and executable",
        },
        {
            "case": "registered-fixture-without-executed-ranges",
            "ok": blocked.ok,
            "executable": blocked.executable,
            "expected": "ok but NOT executable (changed_past 未验证)",
        },
        {
            "case": "unbound-response",
            "ok": unbound.ok,
            "executable": unbound.executable,
            "expected": "ok but NOT executable (绑定未验证)",
        },
        {"case": "three-d1-canonical-responses", "takes": examples, "expected": "all ok and not executable"},
    ]


def git_clean_scope() -> dict:
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain", "--", "code/apps/ainer-core/app/production/performance_contract.py",
             "code/apps/ainer-core/tests/test_production_performance_contract.py", "reports/P1-D2"],
            cwd=REPO, capture_output=True, text=True, check=False,
        )
        return {"status": out.stdout.strip().splitlines(), "returncode": out.returncode}
    except Exception as exc:  # pragma: no cover
        return {"error": str(exc)}


def main() -> int:
    pytest_log = REPO / "reports" / "P1-D2" / "pytest-p1d2.log"
    schema_alignment = REPO / "reports" / "P1-D2" / "schema-alignment.json"
    payload = {
        "task": "hub.P1.D2",
        "agent": "deepseek-q5t8",
        "date": "2026-10-15",
        "platform": f"{platform.system()} {platform.release()}",
        "python": sys.version.split()[0],
        "pydantic": __import__("pydantic").VERSION,
        "cpu_only": True,
        "inputs": [
            identity(REPO / "docs" / "v2" / "production_brain" / "performance_interface_v0.schema.json"),
            identity(REPO / "docs" / "v2" / "production_brain" / "performance_interface_v0.md"),
            identity(REPO / "reports" / "production-brain" / "D1-r3" / "identities.json"),
            identity(REPO / "reports" / "production-brain" / "D1-r3" / "r2-performance_interface_v0.schema.json"),
            identity(REPO / "reports" / "production-brain" / "D1-r3" / "r2-performance_interface_v0.md"),
        ],
        "outputs": [
            identity(APP / "app" / "production" / "performance_contract.py"),
            identity(APP / "tests" / "test_production_performance_contract.py"),
            identity(REPO / "reports" / "P1-D2" / "check_schema_alignment.py"),
            identity(REPO / "reports" / "P1-D2" / "collect_evidence.py"),
            identity(schema_alignment),
            identity(pytest_log),
        ],
        "commands": [
            {
                "cmd": "TMPDIR=/tmp/hub-p1-d2-vR7yCD PYTHONDONTWRITEBYTECODE=1 ../../../.venv/bin/python -m pytest tests/test_production_performance_contract.py -q",
                "cwd": str(APP),
                "exit": 0,
                "result": "106 passed, 1 warning",
                "log": str(pytest_log),
            },
            {
                "cmd": "PYTHONDONTWRITEBYTECODE=1 /Users/mac/AinerWorkFlow/AnimeWorldZero/.venv/bin/python reports/P1-D2/check_schema_alignment.py",
                "cwd": str(REPO),
                "exit": 0,
                "result": "26 cases, 0 false green, 0 canonical rejected, RESULT: PASS",
                "log": str(REPO / "reports" / "P1-D2" / "schema-alignment.log"),
            },
            {
                "cmd": "PYTHONDONTWRITEBYTECODE=1 /Users/mac/AinerWorkFlow/AnimeWorldZero/.venv/bin/python reports/P1-D2/check_schema_alignment.py --failure-control",
                "cwd": str(REPO),
                "exit": 0,
                "result": "failure-control RESULT: PASS（注入假绿后确实抓到 12/12）",
                "log": str(REPO / "reports" / "P1-D2" / "schema-alignment-failure-control.log"),
            },
            {
                "cmd": "PYTHONDONTWRITEBYTECODE=1 ../../../.venv/bin/python -m pytest tests/test_production_review_contract.py tests/test_production_chain.py tests/test_performance.py -q",
                "cwd": str(APP),
                "exit": 0,
                "result": "135 passed（邻近模块回归，未动它们）",
            },
        ],
        "capability_fixture": tf.fixture_capabilities(),
        "counterexamples": counterexamples(),
        "positive_controls": positive_controls(),
        "schema_alignment": json.loads(schema_alignment.read_text(encoding="utf-8")),
        "d1_independent_r2_reference_sha": sha256_of(D1_INDEPENDENT_R2) if D1_INDEPENDENT_R2.exists() else None,
        "git_status_scope": git_clean_scope(),
        "unverified": [
            "全量 ainer-core 测试套件（超出文件范围；部分用例需要服务/数据库）",
            "真实音频、真实角色包 D5 控制面、渲染、E2E",
            "序列化消费方（谁把本校验器接到 API/执行器）尚未存在",
            "性能：单条 600 tick 曲线的校验耗时未做基准",
        ],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    failed = [row for row in payload["counterexamples"] if not row["pass"]]
    print(f"counterexamples={len(payload['counterexamples'])} failed={len(failed)}")
    for row in failed:
        print("  FAILED:", row)
    print(f"positive_controls={len(payload['positive_controls'])}")
    print(f"evidence -> {OUT} sha256={sha256_of(OUT)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
