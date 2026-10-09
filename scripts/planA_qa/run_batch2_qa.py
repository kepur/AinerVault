#!/usr/bin/env python3
"""Plan A 第二批 QA 综合自动化验证执行器 (Batch 2 QA Test Runner)
=============================================================================
执行方式：
  .venv/bin/python scripts/planA_qa/run_batch2_qa.py

覆盖范围：
  1. 契约与接口测试：
     - R0-R2 基础契约与 CR-09 物理事实一致性校验 (test_planA_contracts_batch1.py)
     - 16 格定妆照与别名映射 (test_char_sheet.py)
     - 舞台物理参数、动作表与站位 (test_stage_p0.py, test_blocking_api.py)
     - 画布接口与生命周期 (test_canvas_api.py)
     - 导演编排与剧本时序 (test_cinematic_director.py, test_screenplay.py)
  2. 端到端真实交互验证：
     - 创作画布点击、编辑、保存与重开全生命周期 (test_studio_e2e_lifecycle.py)
  3. 影视与视频生成质量评估：
     - 评估多镜头覆盖、尾帧接力、运镜与声音生成现状。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORE_DIR = ROOT / "code" / "apps" / "ainer-core"
RUNS_DIR = ROOT / "docs" / "studio" / "test_runs"

PYTEST_TEST_FILES = [
    "tests/test_planA_contracts_batch1.py",
    "tests/test_canvas_api.py",
    "tests/test_stage_p0.py",
    "tests/test_char_sheet.py",
    "tests/test_blocking_api.py",
    "tests/test_cinematic_director.py",
    "tests/test_screenplay.py",
]


def run_batch2_qa() -> dict:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().isoformat()
    start_time = time.time()

    print(f"==================================================")
    print(f"=== Plan A Batch 2 Comprehensive QA Verification ===")
    print(f"==================================================")
    print(f"Timestamp: {timestamp}")
    print(f"Core Directory: {CORE_DIR}")
    print(f"Test Suites ({len(PYTEST_TEST_FILES)} files):")
    for f in PYTEST_TEST_FILES:
        print(f"  - {f}")
    print("")

    # 1. 运行 Pytest 契约与单元测试
    pytest_cmd = [
        str(ROOT / ".venv" / "bin" / "pytest"),
        "-v",
        "--tb=short",
        *PYTEST_TEST_FILES,
    ]

    res = subprocess.run(pytest_cmd, cwd=CORE_DIR, capture_output=True, text=True)
    pytest_duration = time.time() - start_time

    print(res.stdout)
    if res.stderr:
        print("STDERR:\n", res.stderr)

    pytest_success = (res.returncode == 0)

    passed = 0
    failed = 0
    for line in res.stdout.splitlines():
        if "passed" in line:
            m_pass = re.search(r"(\d+)\s+passed", line)
            if m_pass:
                passed = int(m_pass.group(1))
            m_fail = re.search(r"(\d+)\s+failed", line)
            if m_fail:
                failed = int(m_fail.group(1))

    # 2. 检查 E2E 交互最新记录
    e2e_report_path = RUNS_DIR / "e2e_interactive_latest.json"
    e2e_summary = {}
    if e2e_report_path.exists():
        try:
            with open(e2e_report_path, "r", encoding="utf-8") as f:
                e2e_summary = json.load(f)
        except Exception as e:
            e2e_summary = {"error": str(e)}

    # 3. 汇总成 Batch 2 结构化报告
    total_duration = time.time() - start_time
    summary = {
        "batch": "Batch 2",
        "timestamp": timestamp,
        "total_duration_seconds": round(total_duration, 2),
        "pytest_suite": {
            "success": pytest_success,
            "passed_count": passed,
            "failed_count": failed,
            "files": PYTEST_TEST_FILES,
            "duration_seconds": round(pytest_duration, 2),
        },
        "e2e_interactive_suite": {
            "status": e2e_summary.get("overall_status", "UNKNOWN"),
            "steps": e2e_summary.get("steps", {}),
            "defects_observed": e2e_summary.get("defects_observed", []),
        },
        "cinematic_quality_assessment": {
            "BLK-05_3d_blocking": {
                "status": "BLOCKED",
                "reason": "3D 白模姿态控制与站位推演未完成与 LTX 2.5 条件流打通",
            },
            "TIM-03_tail_frame_continuity": {
                "status": "FAILED",
                "reason": "缺少分镜尾帧作为次镜图生视频锚点接力机制，单次生成长镜头画面断层",
            },
            "CAM-04_cinematography_scale": {
                "status": "FAILED",
                "reason": "长镜头未按特写、全景、跟镜拆分，缺乏镜头节奏控制",
            },
            "BUG-04_mlx_audio_sync": {
                "status": "BLOCKED",
                "reason": "本地 MLX LTX 2.5 音频管道未完成，视频无匹配声音",
            },
        },
        "cr_status": {
            "CR-09": {
                "title": "canonical-pack 与 stage/cards 物理事实一致性校验",
                "status": "DEFECT_CONFIRMED",
                "description": "非角色实体被误赋人身物理属性，且 visual_prompt 参数不一致导致体型推断冲突",
            }
        }
    }

    out_json = RUNS_DIR / f"batch2_run_{int(start_time)}.json"
    latest_json = RUNS_DIR / "batch2_latest.json"

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    with open(latest_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n==================================================")
    print(f"=== Plan A Batch 2 QA Verification Finished ===")
    print(f"==================================================")
    print(f"Pytest Suite: {'PASSED' if pytest_success else 'FAILED'} (Passed: {passed}, Failed: {failed})")
    print(f"E2E Interactive Suite: {e2e_summary.get('overall_status', 'UNKNOWN')}")
    print(f"Quality Assessment: 4 items (2 Failed, 2 Blocked)")
    print(f"Report saved to: {out_json}")

    return summary


if __name__ == "__main__":
    res = run_batch2_qa()
    sys.exit(0 if res["pytest_suite"]["success"] else 1)
