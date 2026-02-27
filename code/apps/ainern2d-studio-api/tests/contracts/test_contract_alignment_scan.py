from __future__ import annotations

import re
from pathlib import Path


_EVENT_ASSIGN_RE = re.compile(r'event_type\s*=\s*"([a-z0-9_.]+)"')
_EVENT_DOC_RE = re.compile(r"`([a-z0-9_.]+)`")
_ERROR_CODE_RE = re.compile(r"\b([A-Z]+)-[A-Z_]+-\d{3}\b")

_ERROR_DOMAINS = {
    "AUTH",
    "REQ",
    "ORCH",
    "PLAN",
    "ROUTE",
    "WORKER",
    "COMPOSE",
    "ASSET",
    "RAG",
    "OBS",
    "SYS",
}


def _repo_root() -> Path:
    # tests/contracts -> tests -> ainern2d-studio-api -> apps -> code -> repo_root
    return Path(__file__).resolve().parents[5]


def _iter_python_sources(root: Path):
    for py in root.rglob("*.py"):
        if "tests" in py.parts:
            continue
        yield py


def _registered_events(root: Path) -> set[str]:
    doc = (root / "ainer_event_types.md").read_text(encoding="utf-8")
    return {m.group(1) for m in _EVENT_DOC_RE.finditer(doc)}


def test_all_event_types_are_registered() -> None:
    root = _repo_root()
    registered = _registered_events(root)
    unknown: list[str] = []

    scan_roots = [
        root / "code" / "apps",
        root / "code" / "shared",
    ]
    for scan_root in scan_roots:
        for py in _iter_python_sources(scan_root):
            text = py.read_text(encoding="utf-8")
            for m in _EVENT_ASSIGN_RE.finditer(text):
                evt = m.group(1)
                if evt not in registered:
                    unknown.append(f"{py}:{evt}")

    assert not unknown, "Unregistered event_type found:\n" + "\n".join(sorted(unknown))


def test_error_code_domains_follow_contract() -> None:
    root = _repo_root()
    invalid: list[str] = []

    scan_roots = [
        root / "code" / "apps",
        root / "code" / "shared",
    ]
    for scan_root in scan_roots:
        for py in _iter_python_sources(scan_root):
            text = py.read_text(encoding="utf-8")
            for m in _ERROR_CODE_RE.finditer(text):
                code = m.group(1)
                if code not in _ERROR_DOMAINS:
                    invalid.append(f"{py}:{m.group(0)}")

    assert not invalid, "Invalid error-code domain found:\n" + "\n".join(sorted(invalid))
