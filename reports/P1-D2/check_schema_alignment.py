#!/usr/bin/env python3
"""hub.P1.D2 交叉核对：D2 结构/语义层 vs D1 r3 JSON Schema（jsonschema 4.x）。

只读：加载 D1 r3 schema 与 D2 模块，构造内存中的正例/反例，比较判定。
不写产品代码、不改 schema、不导入 MLX/ORT/模型、不碰数据库/网络。

用法（jsonschema 只在 AWZ 既有 venv 中可用，未安装任何包）：
    PYTHONDONTWRITEBYTECODE=1 /Users/mac/AinerWorkFlow/AnimeWorldZero/.venv/bin/python \
        reports/P1-D2/check_schema_alignment.py [--out reports/P1-D2/schema-alignment.json]

判定口径：
- 一致性：schema 判不合法的记录，D2 语义层必须也拒绝（fail-closed 超集，不允许假绿）。
- 三份标准 response：schema 与 D2 语义层都必须接受，且 executable 必须为 False。
- 已知且有意的差异：D2 语义层比 schema 更严（如 NaN、未对齐音频、pending 被执行），
  逐条记录在 divergences 中，不放宽。
退出码 0 表示全部通过；1 表示出现未预期的假绿或标准例子被误拒。
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
APP = REPO / "code/apps/ainer-core"
SCHEMA_PATH = REPO / "docs" / "v2" / "production_brain" / "performance_interface_v0.schema.json"
DOC_PATH = REPO / "docs" / "v2" / "production_brain" / "performance_interface_v0.md"
sys.path.insert(0, str(APP))

import jsonschema  # noqa: E402  (只在具备该依赖的解释器中运行本脚本)
from jsonschema import Draft202012Validator  # noqa: E402

from app.production import performance_contract as pc  # noqa: E402

D1_R3_SCHEMA_SHA = "34aba041558ecbc279ca84d2e846c76ee2334dd621433c086e9b150640b7d23c"
D1_R3_DOC_SHA = "73c3e88952e50f9e720ac2f80debe2915884a014f8498177e94de6c9ff039946"
MODEL_BY_KIND = {"request": pc.RequestModel, "response": pc.ResponseModel, "error": pc.ErrorRecordModel}


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _jsonschema_version() -> str:
    try:
        from importlib.metadata import version

        return version("jsonschema")
    except Exception:  # pragma: no cover - 仅用于证据记录
        return "unknown"


def structural_ok(record: dict) -> bool:
    """D2 结构层单独判定（私有入口；语义另行判定）。"""
    errors: list[dict[str, str]] = []
    model = MODEL_BY_KIND.get(record.get("record_kind"))
    if model is None:
        return False
    return pc._structure(errors, model, record, "/") is not None


def build_cases(schema: dict) -> list[dict]:
    examples = schema["examples"]
    requests = {item["request_id"]: item for item in examples if item.get("record_kind") == "request"}
    responses = {item["request_id"]: item for item in examples if item.get("record_kind") == "response"}
    error_record = next(item for item in examples if item.get("record_kind") == "error")

    cases: list[dict] = []

    def add(name: str, record: dict, request: dict | None = None, note: str = "") -> None:
        cases.append({"name": name, "record": copy.deepcopy(record), "request": copy.deepcopy(request), "note": note})

    for take in ("suspense", "comedy", "dry"):
        add(f"example-request-{take}", requests[f"fixture-request-{take}"], note="D1 schema 标准例子")
        add(
            f"example-response-{take}",
            responses[f"fixture-request-{take}"],
            requests[f"fixture-request-{take}"],
            note="D1 schema 标准例子（必须仍为候选/未支持）",
        )
    add("example-request-audio-clock", requests["fixture-audio-clock"], note="pending 对齐：D2 语义层应拒绝")
    add("example-error-audio-clock", error_record, requests["fixture-audio-clock"], note="D1 schema 标准错误记录")

    base_request = requests["fixture-request-suspense"]
    base_response = responses["fixture-request-suspense"]

    record = copy.deepcopy(base_request)
    record["binding"]["sim_hz"] = 24
    add("request-sim-hz-24", record, note="24Hz 冒充 120Hz")
    record = copy.deepcopy(base_request)
    record["intensity"] = 2.0
    add("request-intensity-2", record, note="越界强度")
    record = copy.deepcopy(base_request)
    record["duration_ticks"] = -600
    add("request-negative-duration", record, note="负时长")
    record = copy.deepcopy(base_request)
    record["locks"][0]["path"] = "world/actor/position"
    add("request-lock-pointer-no-slash", record, note="D1 r3 Pointer 语法")
    record = copy.deepcopy(base_request)
    record["extra_field"] = 1
    add("request-extra-property", record, note="additionalProperties=false")

    record = copy.deepcopy(base_response)
    record["binding"]["render_fps"] = 0
    add("response-render-fps-0", record, base_request, note="render_fps 最小 1")
    record = copy.deepcopy(base_response)
    record["curves"][0]["keyframes"] = [record["curves"][0]["keyframes"][0]]
    add("response-single-keyframe", record, base_request, note="keyframes minItems=2")
    record = copy.deepcopy(base_response)
    record["curves"][0]["mapping_status"] = "pending_D5"
    record["curves"][0]["execution_status"] = "candidate"
    add("response-pending-claimed-candidate", record, base_request, note="pending_D5 then 分支要求 unsupported")
    record = copy.deepcopy(base_response)
    record["curves"][0]["keyframes"][1]["value"] = float("nan")
    add("response-nan-value", record, base_request, note="NaN：D2 语义层必须拒绝（JSON 无 NaN）")
    record = copy.deepcopy(base_response)
    record["curves"][0]["keyframes"][1]["value"] = 999.0
    add("response-out-of-range", record, base_request, note="单位范围")
    record = copy.deepcopy(base_response)
    record["curves"][0]["phases"]["arrival_end_tick"] = 1
    add("response-phase-inverted", record, base_request, note="预备/到位顺序")
    record = copy.deepcopy(base_response)
    record["curves"].append(copy.deepcopy(record["curves"][0]))
    add("response-duplicate-writer", record, base_request, note="相同部位双写")
    record = copy.deepcopy(base_response)
    record["curves"][0]["channel"] = "mouth"
    add("response-mouth-without-audio", record, base_request, note="未对齐音频写口型")
    record = copy.deepcopy(base_response)
    record["binding"]["plan_revision"] = 2
    add("response-stale-plan-revision", record, base_request, note="旧版本绑定")

    record = copy.deepcopy(error_record)
    record["errors"][0]["code"] = "made_up"
    audio_request = requests["fixture-audio-clock"]
    record = copy.deepcopy(error_record)
    record["errors"][0]["code"] = "made_up"
    add("error-unknown-code", record, audio_request, note="十码之外")
    record = copy.deepcopy(error_record)
    record["errors"] = []
    add("error-empty-errors", record, audio_request, note="errors minItems=1")
    record = copy.deepcopy(error_record)
    record["errors"][0]["path"] = "/bad~2escape"
    add("error-bad-pointer", record, audio_request, note="D1 r3 Pointer 转义")
    record = copy.deepcopy(error_record)
    record["curves"] = []
    add("error-with-curves", record, audio_request, note="错误记录不得夹带成功曲线")
    return cases


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(REPO / "reports" / "P1-D2" / "schema-alignment.json"))
    parser.add_argument(
        "--failure-control",
        action="store_true",
        help="故意把 D2 判定替换成「一律通过」，用于证明本脚本真的能抓到假绿（预期 exit 1）",
    )
    args = parser.parse_args()

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    validator.check_schema(schema)
    cases = build_cases(schema)

    false_green: list[str] = []
    canonical_rejected: list[str] = []
    divergences: list[dict] = []
    structural_deferred: list[str] = []
    rows: list[dict] = []

    for case in cases:
        schema_valid = validator.is_valid(case["record"])
        struct_ok = structural_ok(case["record"]) if case["record"].get("record_kind") else False
        result = pc.validate_record(
            case["record"],
            case["request"],
            capabilities=None,
            executed_tick_ranges=[],
        )
        d2_ok = True if args.failure_control else result.ok
        row = {
            "name": case["name"],
            "note": case["note"],
            "schema_valid": schema_valid,
            "d2_structural_ok": struct_ok,
            "d2_ok": d2_ok,
            "d2_codes": result.error_codes(),
            "d2_executable": result.executable,
        }
        rows.append(row)
        if not schema_valid and d2_ok:
            false_green.append(case["name"])
        if not schema_valid and struct_ok and not d2_ok:
            # 结构层有意把这几项让给语义层，好给出精确的 D1 码；语义层仍然拒绝。
            structural_deferred.append(case["name"])
            divergences.append(
                {"name": case["name"], "kind": "structural-deferred-to-semantic", "codes": result.error_codes()}
            )
        if schema_valid and not d2_ok:
            divergences.append({"name": case["name"], "kind": "d2-semantic-stricter", "codes": result.error_codes()})
        if case["name"].startswith("example-response-") and not (schema_valid and d2_ok):
            canonical_rejected.append(case["name"])
        if case["name"].startswith("example-response-") and result.executable:
            canonical_rejected.append(case["name"] + ":executable")

    payload = {
        "task": "hub.P1.D2",
        "failure_control": bool(args.failure_control),
        "python": sys.version.split()[0],
        "jsonschema": _jsonschema_version(),
        "schema_sha256": sha256_of(SCHEMA_PATH),
        "schema_sha256_expected": D1_R3_SCHEMA_SHA,
        "doc_sha256": sha256_of(DOC_PATH),
        "doc_sha256_expected": D1_R3_DOC_SHA,
        "schema_meta_valid": True,
        "cases": len(cases),
        "false_green": false_green,
        "canonical_rejected": canonical_rejected,
        "structural_deferred_to_semantic": structural_deferred,
        "divergences": divergences,
        "rows": rows,
    }
    out = Path(args.out)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"cases={len(cases)} false_green={len(false_green)} canonical_rejected={len(canonical_rejected)}")
    print(f"divergences={len(divergences)} structural_deferred={len(structural_deferred)}")
    print(f"schema_sha={payload['schema_sha256']}")
    for item in divergences:
        print("  divergence:", item)
    ok = (
        not false_green
        and not canonical_rejected
        and payload["schema_sha256"] == D1_R3_SCHEMA_SHA
        and payload["doc_sha256"] == D1_R3_DOC_SHA
    )
    if args.failure_control:
        ok = not ok  # 控制组：断言「必须能抓到假绿」；抓到即 0，抓不到即 1
        print("RESULT(failure-control):", "PASS" if ok else "FAIL")
        return 0 if ok else 1
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
