"""预设库的读写：补种子、列表（分类/搜索/收藏/最近/可商用）、收藏、使用计数。"""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ids import new_id
from app.models import Preset, PresetMark
from app.presets.seeds import SEEDS

_SEEDED: set[str] = set()


def ensure_seeded(db: Session, kind: str) -> None:
    """补齐这一类的官方预设；已有的按种子刷新名字与 payload（封面、次数、收藏不动）。"""
    if kind in _SEEDED or kind not in SEEDS:
        return
    have = {p.key: p for p in db.execute(select(Preset).where(Preset.kind == kind)).scalars()}
    for s in SEEDS[kind]():
        p = have.get(s["key"])
        payload = dict(s["payload"])
        if p is None:
            db.add(Preset(id=new_id("ps"), kind=kind, key=s["key"], name=s["name"], category=s.get("category"),
                          payload_json=payload, tags_json=s.get("tags"), author="官方", official=True,
                          commercial=True, uses=0, sort=s.get("sort", 0)))
        elif p.official:
            # 官方预设以代码为准；已经出好的图（views、cover）保留
            keep = {k: v for k, v in (p.payload_json or {}).items() if k in ("views", "voice", "cover_task")}
            p.name, p.category, p.sort = s["name"], s.get("category"), s.get("sort", 0)
            p.payload_json = {**payload, **keep}
            p.tags_json = s.get("tags")
    db.flush()
    _SEEDED.add(kind)


def preset_out(p: Preset, marks: set[str] | None = None) -> dict[str, Any]:
    return {
        "id": p.id, "kind": p.kind, "key": p.key, "name": p.name, "category": p.category,
        "cover_url": p.cover_url, "payload": p.payload_json or {}, "tags": p.tags_json or [],
        "author": p.author, "official": p.official, "commercial": p.commercial, "uses": p.uses,
        "favorite": bool(marks and "favorite" in marks),
    }


def list_presets(db: Session, kind: str, *, category: str | None = None, q: str | None = None,
                 mark: str | None = None, commercial: bool = False, official: bool | None = None) -> list[dict[str, Any]]:
    ensure_seeded(db, kind)
    stmt = select(Preset).where(Preset.kind == kind)
    if category and category != "推荐":
        stmt = stmt.where(Preset.category == category)
    if q:
        stmt = stmt.where(Preset.name.ilike(f"%{q}%") | Preset.author.ilike(f"%{q}%"))
    if commercial:
        stmt = stmt.where(Preset.commercial.is_(True))
    if official is not None:
        stmt = stmt.where(Preset.official.is_(official))
    marks: dict[str, set[str]] = {}
    for m in db.execute(select(PresetMark).join(Preset, Preset.id == PresetMark.preset_id).where(Preset.kind == kind)).scalars():
        marks.setdefault(m.preset_id, set()).add(m.mark)
    if mark:
        ids = [pid for pid, ms in marks.items() if mark in ms]
        stmt = stmt.where(Preset.id.in_(ids or [""]))
    if mark == "recent":
        recent = {m.preset_id: m.updated_at for m in db.execute(select(PresetMark).where(PresetMark.mark == "recent")).scalars()}
        rows = sorted(db.execute(stmt).scalars(), key=lambda p: recent.get(p.id), reverse=True)
    elif category == "推荐":
        rows = list(db.execute(stmt.order_by(Preset.uses.desc(), Preset.sort)).scalars())
    else:
        rows = list(db.execute(stmt.order_by(Preset.sort, Preset.name)).scalars())
    return [preset_out(p, marks.get(p.id)) for p in rows]


def categories(db: Session, kind: str) -> list[dict[str, Any]]:
    ensure_seeded(db, kind)
    rows = db.execute(select(Preset.category, func.count()).where(Preset.kind == kind).group_by(Preset.category)).all()
    return [{"category": c, "count": n} for c, n in rows if c]


def toggle_mark(db: Session, preset_id: str, mark: str) -> bool:
    m = db.execute(select(PresetMark).where(PresetMark.preset_id == preset_id, PresetMark.mark == mark)).scalars().first()
    if m:
        db.delete(m)
        return False
    db.add(PresetMark(id=new_id("pm"), preset_id=preset_id, mark=mark))
    return True


def mark_used(db: Session, preset: Preset) -> None:
    preset.uses = (preset.uses or 0) + 1
    m = db.execute(select(PresetMark).where(PresetMark.preset_id == preset.id, PresetMark.mark == "recent")).scalars().first()
    if m:
        from app.models.base import utcnow
        m.updated_at = utcnow()
    else:
        db.add(PresetMark(id=new_id("pm"), preset_id=preset.id, mark="recent"))
