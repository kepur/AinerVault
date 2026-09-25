"""场景项目的读写：虚拟文件系统、版本历史、编译、手动改动。

API 与智能体共用这一层 —— 智能体的 x_write / x_edit 与人在界面上改脚本走同一条路，
版本历史里一视同仁，都能撤回。
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.ids import new_id
from app.models import SceneProject
from app.scene3d.runner import compile_scene
from app.scene3d.templates import TEMPLATES

ENTRY = "scene.js"
FILE_RE = re.compile(r"^[A-Za-z0-9_\-一-鿿]{1,48}\.(js|md|json)$")
MAX_FILE = 200_000
MAX_FILES = 20
MAX_VERSIONS = 40


class SceneFileError(ValueError):
    """文件操作不合法（路径、大小、找不到要替换的原文……）。消息直接给人或智能体看。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_project(db: Session, *, title: str, template: str | None = None, novel_id: str | None = None,
                shot_plan_id: str | None = None, scene_id: str | None = None) -> SceneProject:
    tpl = TEMPLATES.get(template or "blank") or TEMPLATES["blank"]
    p = SceneProject(
        id=new_id("sc"), title=(title or tpl["name"]).strip()[:200], template=tpl["key"],
        novel_id=novel_id, shot_plan_id=shot_plan_id, scene_id=scene_id,
        files_json={ENTRY: tpl["script"], "notes.md": f"# {title or tpl['name']}\n\n（导演笔记：智能体在这里记它的规划）\n"},
        overrides_json={}, versions_json=[], settings_json={}, seed=1,
    )
    db.add(p)
    compile_project(p)
    db.flush()
    return p


def compile_project(p: SceneProject) -> dict[str, Any]:
    r = compile_scene((p.files_json or {}).get(ENTRY, ""), seed=p.seed or 1, overrides=p.overrides_json or None)
    p.compiled_json = r.get("doc")
    p.diagnostics_json = {k: r.get(k) for k in ("ok", "errors", "warnings", "summary", "ms")}
    return r


def _check_path(path: str) -> str:
    path = (path or "").strip().lstrip("/")
    if not FILE_RE.match(path):
        raise SceneFileError(f"文件名「{path}」不合法：只能是一层目录下的 .js / .md / .json，比如 scene.js、notes.md")
    return path


def list_files(p: SceneProject) -> list[dict[str, Any]]:
    return [{"path": k, "bytes": len(v.encode("utf-8")), "lines": v.count("\n") + 1}
            for k, v in sorted((p.files_json or {}).items())]


def read_file(p: SceneProject, path: str) -> str:
    path = _check_path(path)
    files = p.files_json or {}
    if path not in files:
        raise SceneFileError(f"没有文件「{path}」。现有：{', '.join(sorted(files)) or '（空）'}")
    return files[path]


def _snapshot(p: SceneProject, by: str, note: str) -> None:
    versions = list(p.versions_json or [])
    versions.append({"at": _now(), "by": by, "note": note[:120], "files": dict(p.files_json or {})})
    p.versions_json = versions[-MAX_VERSIONS:]


def write_file(p: SceneProject, path: str, content: str, *, by: str, note: str = "") -> None:
    path = _check_path(path)
    if len(content.encode("utf-8")) > MAX_FILE:
        raise SceneFileError(f"文件太大（上限 {MAX_FILE // 1000}KB）：把重复的摆放改成循环或 S.row / S.along")
    files = dict(p.files_json or {})
    if path not in files and len(files) >= MAX_FILES:
        raise SceneFileError(f"文件数到上限 {MAX_FILES} 了")
    if files.get(path) == content:
        return
    _snapshot(p, by, note or f"写 {path}")
    files[path] = content
    p.files_json = files


def edit_file(p: SceneProject, path: str, old: str, new: str, *, by: str, note: str = "") -> int:
    """精确替换：old 必须在文件里恰好出现一次（和写代码的 agent 一样的规矩）。返回改动的行号。"""
    text = read_file(p, path)
    if not old:
        raise SceneFileError("old 不能为空：要追加内容就用 x_write 整个重写，或者找一段现有的结尾来替换")
    n = text.count(old)
    if n == 0:
        # 常见原因：空白不一致、记错了原文。给出最像的一行帮它对上
        first = old.strip().splitlines()[0] if old.strip() else old
        hint = next((f"第 {i + 1} 行：{ln.strip()[:80]}" for i, ln in enumerate(text.splitlines()) if first.strip()[:20] and first.strip()[:20] in ln), "")
        raise SceneFileError(f"在 {path} 里找不到要替换的原文（要逐字一致，包括空格和换行）。{('最像的是 ' + hint) if hint else '先用 x_read 看一下现在的内容'}")
    if n > 1:
        raise SceneFileError(f"要替换的原文在 {path} 里出现了 {n} 次，不知道改哪一处 —— 多带几行上下文让它唯一")
    line = text[: text.index(old)].count("\n") + 1
    write_file(p, path, text.replace(old, new, 1), by=by, note=note or f"改 {path} 第 {line} 行")
    return line


def set_overrides(p: SceneProject, overrides: dict[str, Any]) -> None:
    ov = {k: overrides.get(k) for k in ("objects", "cameras", "cuts") if overrides.get(k)}
    p.overrides_json = ov


def restore_version(p: SceneProject, index: int, *, by: str) -> None:
    versions = list(p.versions_json or [])
    if not 0 <= index < len(versions):
        raise SceneFileError(f"没有第 {index} 版（共 {len(versions)} 版）")
    target = versions[index]["files"]
    _snapshot(p, by, f"回到 {versions[index]['at']} 的版本")
    p.files_json = dict(target)


def project_out(p: SceneProject, *, full: bool = True) -> dict[str, Any]:
    d = p.diagnostics_json or {}
    summary = d.get("summary") or {}
    out: dict[str, Any] = {
        "id": p.id, "title": p.title, "template": p.template, "novel_id": p.novel_id,
        "shot_plan_id": p.shot_plan_id, "scene_id": p.scene_id, "thumb_url": p.thumb_url,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        "ok": d.get("ok"), "objects": summary.get("objects"), "cameras": len(summary.get("cameras") or []),
        "duration": summary.get("duration"),
    }
    if full:
        out.update({
            "files": p.files_json or {}, "overrides": p.overrides_json or {}, "doc": p.compiled_json,
            "diagnostics": d, "seed": p.seed, "settings": p.settings_json or {},
            "versions": [{"index": i, "at": v.get("at"), "by": v.get("by"), "note": v.get("note")}
                         for i, v in enumerate(p.versions_json or [])],
        })
    return out
