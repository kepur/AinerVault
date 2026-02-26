#!/usr/bin/env python3
"""Validate SKILL 01~22 implementation scaffolding and anti-drift anchors.

Usage:
  python3 code/scripts/validate_skill_framework.py
  python3 code/scripts/validate_skill_framework.py --strict
  python3 code/scripts/validate_skill_framework.py --report progress/MODEL_CONFIRMATION_REPORT.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List


@dataclass
class CheckResult:
    check_id: str
    status: str  # PASS | FAIL | WARN
    detail: str


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _exists_any(base: Path, pattern: str) -> bool:
    return any(base.glob(pattern))


def run_checks(repo_root: Path) -> list[CheckResult]:
    checks: list[CheckResult] = []

    expected_ids = {f"{i:02d}" for i in range(1, 23)}

    # C001: root spec files 01~22
    spec_files = list(repo_root.glob("SKILL_[0-9][0-9]_*.md"))
    found_ids = {
        m.group(1)
        for f in spec_files
        for m in [re.match(r"^SKILL_(\d{2})_.*\.md$", f.name)]
        if m
    }
    missing_specs = sorted(expected_ids - found_ids)
    if missing_specs:
        checks.append(
            CheckResult(
                "C001",
                "FAIL",
                f"Missing root SKILL specs: {', '.join(missing_specs)}",
            )
        )
    else:
        checks.append(CheckResult("C001", "PASS", "Root SKILL_01~22 specs are present."))

    # C002: DTO files 01~22
    dto_dir = repo_root / "code/shared/ainern2d_shared/schemas/skills"
    missing_dto = [sid for sid in sorted(expected_ids) if not (dto_dir / f"skill_{sid}.py").exists()]
    if missing_dto:
        checks.append(CheckResult("C002", "FAIL", f"Missing DTO files: {', '.join(missing_dto)}"))
    else:
        checks.append(CheckResult("C002", "PASS", "DTO files skill_01.py ~ skill_22.py are present."))

    # C003: Service skeleton files by ownership boundary
    studio_dir = repo_root / "code/apps/ainern2d-studio-api/app/services/skills"
    composer_dir = repo_root / "code/apps/ainern2d-composer/app/services/skills"
    service_missing: list[str] = []
    for i in range(1, 23):
        sid = f"{i:02d}"
        if sid in {"06", "20"}:
            if not _exists_any(composer_dir, f"skill_{sid}_*.py"):
                service_missing.append(f"SKILL_{sid}(composer)")
        else:
            if not _exists_any(studio_dir, f"skill_{sid}_*.py"):
                service_missing.append(f"SKILL_{sid}(studio)")
    if service_missing:
        checks.append(CheckResult("C003", "FAIL", f"Missing service files: {', '.join(service_missing)}"))
    else:
        checks.append(CheckResult("C003", "PASS", "Service file ownership boundaries are satisfied."))

    # C004: Studio registry includes 01~05,07~19,21,22
    reg_file = repo_root / "code/apps/ainern2d-studio-api/app/services/skill_registry.py"
    reg_txt = _read(reg_file)
    studio_skill_ids = [*(f"{i:02d}" for i in range(1, 6)), *(f"{i:02d}" for i in range(7, 20)), "21", "22"]
    missing_registry = [sid for sid in studio_skill_ids if f'"skill_{sid}":' not in reg_txt]
    if missing_registry:
        checks.append(CheckResult("C004", "FAIL", f"Missing registry keys: {', '.join(missing_registry)}"))
    else:
        checks.append(CheckResult("C004", "PASS", "Studio SkillRegistry mapping is complete."))

    # C005: Dispatcher anchors for 21/22
    dispatcher_file = repo_root / "code/apps/ainern2d-studio-api/app/services/skill_dispatcher.py"
    d_txt = _read(dispatcher_file)
    d_ok = (
        'JobType.resolve_entity_continuity.value: "skill_21"' in d_txt
        and 'JobType.manage_persona_dataset_index.value: "skill_22"' in d_txt
    )
    if not d_ok:
        checks.append(CheckResult("C005", "FAIL", "SkillDispatcher missing job_type -> skill_21/22 mapping."))
    else:
        checks.append(CheckResult("C005", "PASS", "SkillDispatcher includes 21/22 mapping."))

    # C006: Composer dispatcher anchors for 06/20
    composer_dispatcher = repo_root / "code/apps/ainern2d-composer/app/services/skill_dispatcher.py"
    c_txt = _read(composer_dispatcher)
    c_ok = (
        "JobType.assemble_audio_timeline.value" in c_txt
        and "AudioTimelineService" in c_txt
        and "JobType.compile_dsl.value" in c_txt
        and "DslCompilerService" in c_txt
    )
    if not c_ok:
        checks.append(CheckResult("C006", "FAIL", "Composer dispatcher missing 06/20 ownership mapping."))
    else:
        checks.append(CheckResult("C006", "PASS", "Composer dispatcher includes 06/20 mapping."))

    # C007: DAG order anchors
    dag_file = repo_root / "code/apps/ainern2d-studio-api/app/modules/orchestrator/dag_engine.py"
    dag_txt = _read(dag_file)
    ix_extract = dag_txt.find("JobType.extract_entities")
    ix_21 = dag_txt.find("JobType.resolve_entity_continuity")
    ix_07 = dag_txt.find("JobType.canonicalize_entities")
    ix_22 = dag_txt.find("JobType.manage_persona_dataset_index")
    ix_prompt = dag_txt.find("JobType.plan_prompt")
    order_ok = ix_extract != -1 and ix_21 != -1 and ix_07 != -1 and ix_22 != -1 and ix_prompt != -1 and ix_extract < ix_21 < ix_07 and ix_22 < ix_prompt
    if not order_ok:
        checks.append(CheckResult("C007", "FAIL", "DAG order anchors broken: expected 04->21->07 and 22 before 10."))
    else:
        checks.append(CheckResult("C007", "PASS", "DAG order anchors are present (04->21->07, 22->10)."))

    # C008: DB preview model anchors for 21/22
    preview_models = repo_root / "code/shared/ainern2d_shared/ainer_db_models/preview_models.py"
    pm_txt = _read(preview_models)
    model_tokens = [
        "class EntityInstanceLink",
        "class EntityContinuityProfile",
        "class EntityPreviewVariant",
        "class CharacterVoiceBinding",
        "class PersonaDatasetBinding",
        "class PersonaIndexBinding",
        "class PersonaLineageEdge",
        "class PersonaRuntimeManifest",
    ]
    missing_models = [t for t in model_tokens if t not in pm_txt]
    if missing_models:
        checks.append(CheckResult("C008", "FAIL", f"Missing DB model classes: {', '.join(missing_models)}"))
    else:
        checks.append(CheckResult("C008", "PASS", "DB model anchors for SKILL 21/22 are present."))

    # C009: Alembic alignment migration exists and contains enum anchors
    mig = repo_root / "code/apps/alembic/versions/0f2b6c9b0c7f_align_skill_21_22_schema.py"
    if not mig.exists():
        checks.append(CheckResult("C009", "FAIL", "Missing Alembic migration 0f2b6c9b0c7f_align_skill_21_22_schema.py."))
    else:
        m_txt = _read(mig)
        enum_ok = "resolve_entity_continuity" in m_txt and "manage_persona_dataset_index" in m_txt
        if enum_ok:
            checks.append(CheckResult("C009", "PASS", "Alembic migration for 21/22 enum/table alignment is present."))
        else:
            checks.append(CheckResult("C009", "FAIL", "Alembic migration exists but enum anchors are incomplete."))

    # C010: Progress matrix has SKILL_21/22 and db_alignment pending notes
    status_file = repo_root / "progress/skill_delivery_status.yaml"
    s_txt = _read(status_file)
    progress_ok = (
        "skill_id: \"SKILL_21\"" in s_txt
        and "skill_id: \"SKILL_22\"" in s_txt
        and "status: \"INTEGRATION_READY\"" in s_txt
        and "db_alignment:" in s_txt
    )
    if not progress_ok:
        checks.append(CheckResult("C010", "FAIL", "progress/skill_delivery_status.yaml missing 21/22 or db alignment anchors."))
    else:
        checks.append(CheckResult("C010", "PASS", "Progress matrix contains 21/22 + db_alignment anchors."))

    # C011: Warn if hard blockers still pending (expected at this stage)
    if "SKILL_21/22 service 持久化写库" in s_txt or "执行 alembic upgrade head" in s_txt:
        checks.append(CheckResult("C011", "WARN", "Pending blockers remain: DB upgrade execution / SKILL_21-22 persistence wiring."))
    else:
        checks.append(CheckResult("C011", "PASS", "No high-level pending blockers found in progress matrix."))

    return checks


def build_markdown_report(checks: List[CheckResult], strict: bool) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    total = len(checks)
    p = sum(1 for c in checks if c.status == "PASS")
    f = sum(1 for c in checks if c.status == "FAIL")
    w = sum(1 for c in checks if c.status == "WARN")

    lines = [
        "# MODEL_CONFIRMATION_REPORT",
        "",
        f"- generated_at_utc: `{now}`",
        f"- strict_mode: `{str(strict).lower()}`",
        f"- summary: `PASS={p} FAIL={f} WARN={w} TOTAL={total}`",
        "",
        "| check_id | status | detail |",
        "|---|---|---|",
    ]
    for c in checks:
        lines.append(f"| {c.check_id} | {c.status} | {c.detail} |")

    lines.extend([
        "",
        "## Next",
        "1. 若存在 FAIL：先修复 FAIL 再开始功能开发。",
        "2. 若仅 WARN：可继续开发，但必须在本轮交付中关闭 WARN 对应项。",
        "3. 每次改动后再次运行本脚本，确保无新增漂移。",
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate SKILL scaffolding and anti-drift anchors.")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when any FAIL exists.")
    parser.add_argument("--report", type=str, default="", help="Optional markdown report output path.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON to stdout.")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    checks = run_checks(repo_root)

    fail_count = sum(1 for c in checks if c.status == "FAIL")

    if args.json:
        payload = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "pass": sum(1 for c in checks if c.status == "PASS"),
                "fail": fail_count,
                "warn": sum(1 for c in checks if c.status == "WARN"),
                "total": len(checks),
            },
            "checks": [c.__dict__ for c in checks],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for c in checks:
            print(f"[{c.status}] {c.check_id} {c.detail}")

    if args.report:
        report_path = (repo_root / args.report).resolve() if not Path(args.report).is_absolute() else Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(build_markdown_report(checks, strict=args.strict), encoding="utf-8")
        print(f"report_written={report_path}")

    if args.strict and fail_count > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
