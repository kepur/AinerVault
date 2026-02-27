#!/usr/bin/env python3
"""Validate pre-implementation readiness gates.

Usage:
  python3 code/scripts/validate_preimplementation_readiness.py
  python3 code/scripts/validate_preimplementation_readiness.py --strict
  python3 code/scripts/validate_preimplementation_readiness.py \
    --report progress/PREIMPLEMENTATION_READINESS_REPORT.md
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


@dataclass
class CheckResult:
    code: str
    title: str
    status: str  # PASS | FAIL | WARN
    detail: str


def _run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout.strip()


def _validate_files_exist() -> CheckResult:
    required = [
        ROOT / "START_HERE_FOR_AGENTS.md",
        ROOT / "ainer_contracts.md",
        ROOT / "ainer_event_types.md",
        ROOT / "ainer_error_code.md",
        ROOT / "progress" / "skill_delivery_status.yaml",
        ROOT / "code" / "docs" / "runbooks" / "e2e-handoff-test-matrix.md",
    ]
    missing = [str(p.relative_to(ROOT)) for p in required if not p.exists()]
    if missing:
        return CheckResult(
            code="P001",
            title="Mandatory Specs & Runbooks",
            status="FAIL",
            detail=f"missing={missing}",
        )
    return CheckResult(
        code="P001",
        title="Mandatory Specs & Runbooks",
        status="PASS",
        detail="all required docs present",
    )


def _validate_skill_specs_01_22() -> CheckResult:
    missing: list[str] = []
    for i in range(1, 23):
        pattern = f"SKILL_{i:02d}_"
        found = any(p.name.startswith(pattern) for p in ROOT.glob("SKILL_*.md"))
        if not found:
            missing.append(pattern + "*.md")
    if missing:
        return CheckResult(
            code="P002",
            title="Root SKILL_01~22 Specs",
            status="FAIL",
            detail=f"missing={missing}",
        )
    return CheckResult(
        code="P002",
        title="Root SKILL_01~22 Specs",
        status="PASS",
        detail="01~22 specs present",
    )


def _validate_framework_strict() -> CheckResult:
    cmd = [
        sys.executable,
        "code/scripts/validate_skill_framework.py",
        "--strict",
        "--report",
        "progress/MODEL_CONFIRMATION_REPORT.md",
    ]
    rc, out = _run(cmd, ROOT)
    if rc != 0:
        tail = "\n".join(out.splitlines()[-10:])
        return CheckResult(
            code="P003",
            title="Framework Strict Validation",
            status="FAIL",
            detail=tail or "validate_skill_framework failed",
        )
    return CheckResult(
        code="P003",
        title="Framework Strict Validation",
        status="PASS",
        detail="validate_skill_framework --strict passed",
    )


def _validate_skills_pytest() -> CheckResult:
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "code/apps/ainern2d-studio-api/tests/skills",
        "-q",
    ]
    rc, out = _run(cmd, ROOT)
    if rc != 0:
        tail = "\n".join(out.splitlines()[-20:])
        return CheckResult(
            code="P004",
            title="Skills Test Suite",
            status="FAIL",
            detail=tail or "skills pytest failed",
        )
    summary = out.splitlines()[-1] if out.splitlines() else "skills pytest passed"
    return CheckResult(
        code="P004",
        title="Skills Test Suite",
        status="PASS",
        detail=summary,
    )


def _validate_e2e_21_22() -> CheckResult:
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "code/apps/ainern2d-studio-api/tests/skills/test_e2e_handoff_21_22.py",
        "-q",
    ]
    rc, out = _run(cmd, ROOT)
    if rc != 0:
        tail = "\n".join(out.splitlines()[-20:])
        return CheckResult(
            code="P005",
            title="E2E-021/022 Service Chains",
            status="FAIL",
            detail=tail or "E2E-021/022 pytest failed",
        )
    summary = out.splitlines()[-1] if out.splitlines() else "e2e 21/22 passed"
    return CheckResult(
        code="P005",
        title="E2E-021/022 Service Chains",
        status="PASS",
        detail=summary,
    )


def _validate_realdb_optional() -> CheckResult:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        return CheckResult(
            code="P006",
            title="Real-DB Persistence Validation",
            status="WARN",
            detail="DATABASE_URL not set; skip real-db validator",
        )
    cmd = [
        sys.executable,
        "code/scripts/validate_skill_21_22_persistence_realdb.py",
    ]
    rc, out = _run(cmd, ROOT)
    result_line = _extract_validation_result_line(out)
    if rc != 0:
        tail = "\n".join(out.splitlines()[-20:])
        return CheckResult(
            code="P006",
            title="Real-DB Persistence Validation",
            status="FAIL",
            detail=result_line or tail or "real-db validator failed",
        )
    summary = result_line or "real-db validator passed"
    return CheckResult(
        code="P006",
        title="Real-DB Persistence Validation",
        status="PASS",
        detail=summary,
    )


def _extract_validation_result_line(output: str) -> str:
    for line in reversed(output.splitlines()):
        if line.startswith("VALIDATION_RESULT:"):
            return line
    return ""


def _render_report(results: list[CheckResult], strict: bool) -> str:
    now = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M:%SZ")
    pass_count = sum(1 for r in results if r.status == "PASS")
    fail_count = sum(1 for r in results if r.status == "FAIL")
    warn_count = sum(1 for r in results if r.status == "WARN")

    readiness = "GO" if fail_count == 0 and (not strict or warn_count == 0) else "NO_GO"
    lines = [
        "# PREIMPLEMENTATION_READINESS_REPORT",
        "",
        f"- generated_at_utc: `{now}`",
        f"- strict_mode: `{str(strict).lower()}`",
        f"- summary: `PASS={pass_count} FAIL={fail_count} WARN={warn_count} TOTAL={len(results)}`",
        f"- readiness: `{readiness}`",
        "",
        "## Gate Results",
    ]
    for r in results:
        lines.append(f"- [{r.status}] {r.code} {r.title}: {r.detail}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate pre-implementation readiness gates.")
    parser.add_argument(
        "--report",
        default="progress/PREIMPLEMENTATION_READINESS_REPORT.md",
        help="markdown report output path",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="treat WARN as failure",
    )
    args = parser.parse_args()

    checks = [
        _validate_files_exist,
        _validate_skill_specs_01_22,
        _validate_framework_strict,
        _validate_skills_pytest,
        _validate_e2e_21_22,
        _validate_realdb_optional,
    ]
    results = [fn() for fn in checks]
    report = _render_report(results, strict=args.strict)

    report_path = ROOT / args.report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    print(f"report_written={report_path}")

    has_fail = any(r.status == "FAIL" for r in results)
    has_warn = any(r.status == "WARN" for r in results)
    if has_fail:
        return 1
    if args.strict and has_warn:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
