#!/usr/bin/env python3
"""Plan A 第一批 QA 自动化验证执行器 (Batch 1 QA Test Runner)
=============================================================================
执行方式：
  .venv/bin/python scripts/planA_qa/run_batch1_qa.py

功能：
  1. 自动化运行 Plan A 第一批相关的契约与单元测试套件（严格内存隔离）。
  2. 输出结构化测试记录与 JSON 报告至 docs/studio/test_runs/。
  3. 生成分项通过/失败统计矩阵供交接报告使用。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORE_DIR = ROOT / "code" / "apps" / "ainer-core"
RUNS_DIR = ROOT / "docs" / "studio" / "test_runs"

TEST_FILES = [
    "tests/test_planA_contracts_batch1.py",
    "tests/test_canvas_api.py",
    "tests/test_stage_p0.py",
    "tests/test_char_sheet.py",
]


def run_tests() -> dict:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().isoformat()
    start_time = time.time()

    pytest_cmd = [
        str(ROOT / ".venv" / "bin" / "pytest"),
        "-v",
        "--tb=short",
        *TEST_FILES,
    ]

    print(f"=== Plan A Batch 1 QA Verification Started ===")
    print(f"Timestamp: {timestamp}")
    print(f"Directory: {CORE_DIR}")
    print(f"Test Files: {', '.join(TEST_FILES)}\n")

    res = subprocess.run(pytest_cmd, cwd=CORE_DIR, capture_output=True, text=True)
    duration = time.time() - start_time

    print(res.stdout)
    if res.stderr:
        print("STDERR:\n", res.stderr)

    success = (res.returncode == 0)

    # 提取通过数
    passed = 0
    failed = 0
    for line in res.stdout.splitlines():
        if "passed" in line:
            import re
            m_pass = re.search(r"(\d+)\s+passed", line)
            if m_pass:
                passed = int(m_pass.group(1))
            m_fail = re.search(r"(\d+)\s+failed", line)
            if m_fail:
                failed = int(m_fail.group(1))

    summary = {
        "timestamp": timestamp,
        "duration_seconds": round(duration, 2),
        "return_code": res.returncode,
        "success": success,
        "passed_count": passed,
        "failed_count": failed,
        "test_files": TEST_FILES,
        "stdout": res.stdout,
    }

    out_json = RUNS_DIR / f"batch1_run_{int(start_time)}.json"
    latest_json = RUNS_DIR / "batch1_latest.json"

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    with open(latest_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n=== QA Verification Finished ===")
    print(f"Status: {'PASSED (通过)' if success else 'FAILED (失败)'}")
    print(f"Passed: {passed}, Failed: {failed}, Duration: {round(duration, 2)}s")
    print(f"Report saved to: {out_json}")
    return summary


if __name__ == "__main__":
    summary = run_tests()
    sys.exit(0 if summary["success"] else 1)
