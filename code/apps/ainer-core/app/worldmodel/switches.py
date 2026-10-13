"""world-greybox 是**可选**路径：总开关（feature_flags.yaml: world_greybox_enabled）× 作用域开关（默认关）。

默认路径（原动态漫剧 / 导演管线）不看这里以外的任何东西；只有 resolve(...).enabled 为真时才走 greybox。
作用域优先级：shot > plan > chapter > production > novel。fallback_to_original：greybox 闸门不过时回退原管线成片。
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.director import config
from app.ids import new_id
from app.models import WorldGreyboxSwitch

SCOPES = ("shot", "plan", "chapter", "production", "novel")


@dataclass
class Decision:
    enabled: bool
    fallback_to_original: bool
    scope: str | None
    reason: str


def global_enabled() -> bool:
    return config.enabled("world_greybox_enabled")


def set_switch(db: Session, scope_kind: str, scope_id: str, *, enabled: bool,
               fallback_to_original: bool = True, note: str | None = None) -> WorldGreyboxSwitch:
    if scope_kind not in SCOPES:
        raise ValueError(f"scope_kind 只能是 {SCOPES}")
    sw = db.scalar(select(WorldGreyboxSwitch).where(WorldGreyboxSwitch.scope_kind == scope_kind,
                                                    WorldGreyboxSwitch.scope_id == scope_id))
    if sw is None:
        sw = WorldGreyboxSwitch(id=new_id("wgs"), scope_kind=scope_kind, scope_id=scope_id)
        db.add(sw)
    sw.enabled, sw.fallback_to_original, sw.note = enabled, fallback_to_original, note
    db.flush()
    return sw


def resolve(db: Session, **scopes: str | None) -> Decision:
    """resolve(db, shot=..., plan=..., chapter=..., production=..., novel=...)：最具体的已设开关说了算。"""
    if not global_enabled():
        return Decision(False, True, None, "feature flag world_greybox_enabled=false")
    for kind in SCOPES:
        sid = scopes.get(kind)
        if not sid:
            continue
        sw = db.scalar(select(WorldGreyboxSwitch).where(WorldGreyboxSwitch.scope_kind == kind,
                                                        WorldGreyboxSwitch.scope_id == sid))
        if sw is not None:
            return Decision(sw.enabled, sw.fallback_to_original, kind, f"{kind} switch")
    return Decision(False, True, None, "no switch set (default off)")


def out(sw: WorldGreyboxSwitch) -> dict:
    return {"scope_kind": sw.scope_kind, "scope_id": sw.scope_id, "enabled": sw.enabled,
            "fallback_to_original": sw.fallback_to_original, "note": sw.note}
