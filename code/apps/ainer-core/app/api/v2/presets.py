"""预设库接口：风格广场、运镜广场、特效广场、爆款题材……收藏、最近使用、封面生成、把风格套到分镜计划。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.capability.schemas import Capability
from app.db import get_db
from app.models import Asset, Preset, ShotPlan
from app.presets import jobs
from app.presets import service as ps

router = APIRouter(prefix="/api/v2/presets", tags=["presets"])

KINDS = {"style", "genre", "camera_move", "effect", "hairstyle", "outfit", "expression", "character"}


@router.get("")
def list_presets(kind: str, category: str | None = None, q: str | None = None, mark: str | None = None,
                 commercial: bool = False, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    if kind not in KINDS:
        raise HTTPException(422, f"kind 只能是 {sorted(KINDS)}")
    rows = ps.list_presets(db, kind, category=category, q=q, mark=mark, commercial=commercial)
    db.commit()
    return rows


@router.get("/categories")
def get_categories(kind: str, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    out = ps.categories(db, kind)
    db.commit()
    return out


def _preset(db: Session, pid: str) -> Preset:
    p = db.get(Preset, pid)
    if p is None:
        raise HTTPException(404, "预设不存在")
    return p


@router.post("/{pid}:favorite")
def favorite(pid: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    _preset(db, pid)
    on = ps.toggle_mark(db, pid, "favorite")
    db.commit()
    return {"favorite": on}


@router.post("/{pid}:use")
def use(pid: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    p = _preset(db, pid)
    ps.mark_used(db, p)
    db.commit()
    return ps.preset_out(p)


def _set_cover(pid: str):
    def done(db: Session, asset: Asset) -> None:
        p = db.get(Preset, pid)
        if p is not None:
            p.cover_url = asset.url
    return done


class CoversIn(BaseModel):
    kind: str = "style"
    limit: int = 60


@router.post(":covers")
def make_covers(body: CoversIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    """给还没有封面的风格出封面：本机一张一张出（排在队列里，不抢造型室试穿）。"""
    if body.kind != "style":
        raise HTTPException(422, "目前只有风格需要生成封面；角色走 /characters")
    ps.ensure_seeded(db, "style")
    queued = {j["title"] for j in jobs.snapshot("covers") if j["status"] in ("queued", "running")}
    n = 0
    for p in db.execute(select(Preset).where(Preset.kind == "style", Preset.cover_url.is_(None)).order_by(Preset.sort)).scalars():
        title = f"风格封面·{p.name}"
        if title in queued or n >= body.limit:
            continue
        pl = p.payload_json or {}
        jobs.enqueue(jobs.Job(
            title=title, capability=Capability.image_t2i, group="covers", purpose="preset_cover",
            payload={"prompt": f"{pl.get('cover', '')}, {pl.get('prompt', '')}".strip(", "),
                     "negative_prompt": pl.get("negative", ""), "width": 576, "height": 768,
                     # 画风放顶层：工作台只读 input.style，params 里的它不看
                     "style": pl.get("render", "auto"), "params": {"seed": 7}},
            on_done=_set_cover(p.id)))
        n += 1
    db.commit()
    return {"queued": n, "pending": jobs.pending("covers")}


@router.get("/jobs")
def job_status(group: str | None = None) -> list[dict[str, Any]]:
    return jobs.snapshot(group)


class ApplyStyleIn(BaseModel):
    plan_id: str
    preset_id: str | None = None


@router.post(":apply-style")
def apply_style(body: ApplyStyleIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    """把风格套到一份分镜：之后出的首帧、尾帧都带上这个风格（已出的图不动，重出才生效）。"""
    plan = db.get(ShotPlan, body.plan_id)
    if plan is None:
        raise HTTPException(404, "分镜计划不存在")
    cfg = dict(plan.config_json or {})
    if body.preset_id is None:
        cfg.pop("style_preset", None)
        plan.config_json = cfg
        db.commit()
        return {"plan_id": plan.id, "style_preset": None}
    p = _preset(db, body.preset_id)
    if p.kind != "style":
        raise HTTPException(422, "只能套用风格预设")
    pl = p.payload_json or {}
    cfg["style_preset"] = {"id": p.id, "key": p.key, "name": p.name, "render": pl.get("render", "auto"),
                           "prompt": pl.get("prompt", ""), "negative": pl.get("negative", "")}
    plan.config_json = cfg
    ps.mark_used(db, p)
    db.commit()
    return {"plan_id": plan.id, "style_preset": cfg["style_preset"]}
