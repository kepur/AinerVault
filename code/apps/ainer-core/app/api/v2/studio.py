"""画布（ainer-studio）用的聚合接口。

画布一屏要看全一整份分镜：每一镜一张卡片，缩略图、景别、时长、首尾帧与视频
是否就绪、是不是分区身份出的图。现有的 /chapters/{id}/storyboard 是给「逐镜
审稿」用的，一行里带着全部提示词与参考图 —— 两百多镜时太重；而且它只认
「激活剧本的最新版本计划」，画布需要能指定看哪一份。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import (
    Asset, AudioSpec, Chapter, FrameSpec, Scene, ScriptDoc, Shot, ShotPerformance,
    ShotPlan, WorldEntity, WorldTransform,
)

router = APIRouter(prefix="/api/v2/studio", tags=["studio"])


@router.get("/chapters/{chapter_id}/plans")
def chapter_plans(chapter_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """这一章的全部分镜计划（含归档与试片），新的在前。"""
    chapter = db.get(Chapter, chapter_id)
    if chapter is None:
        raise HTTPException(status_code=404, detail="chapter not found")
    doc_ids = [d.id for d in db.execute(
        select(ScriptDoc).where(ScriptDoc.chapter_id == chapter_id)).scalars()]
    rows = db.execute(
        select(ShotPlan, func.count(Shot.id))
        .outerjoin(Shot, Shot.shot_plan_id == ShotPlan.id)
        .where(ShotPlan.script_doc_id.in_(doc_ids or [""]))
        .group_by(ShotPlan.id)
        .order_by(ShotPlan.created_at.desc())
    ).all()
    return {
        "chapter": {"id": chapter.id, "title": chapter.title, "novel_id": chapter.novel_id},
        "plans": [{
            "id": p.id, "version": p.version,
            "status": getattr(p.status, "value", p.status),
            "shots": n,
            "sample": bool((p.config_json or {}).get("sample")),
            "created_at": p.created_at.isoformat() if p.created_at else None,
        } for p, n in rows],
    }


@router.get("/plans/{plan_id}/board")
def plan_board(plan_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """画布的一整份分镜：场景分组，每镜一张卡片需要的最少字段。"""
    plan = db.get(ShotPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="shot plan not found")
    doc = db.get(ScriptDoc, plan.script_doc_id)
    chapter = db.get(Chapter, doc.chapter_id) if doc else None

    shots = list(db.execute(
        select(Shot).where(Shot.shot_plan_id == plan.id).order_by(Shot.order_no)
    ).scalars())
    sids = [s.id for s in shots] or [""]
    frames: dict[str, dict[str, FrameSpec]] = {}
    for f in db.execute(select(FrameSpec).where(FrameSpec.shot_id.in_(sids))).scalars():
        frames.setdefault(f.shot_id, {})[f.role.value] = f
    asset_ids = {f.asset_id for fs in frames.values() for f in fs.values() if f.asset_id}
    asset_ids |= {s.video_asset_id for s in shots if s.video_asset_id}
    urls = {a.id: a.url for a in db.execute(
        select(Asset).where(Asset.id.in_(list(asset_ids) or [""]))).scalars()}
    lines: dict[str, int] = {}
    for sid, n in db.execute(
        select(AudioSpec.shot_id, func.count(AudioSpec.id))
        .where(AudioSpec.shot_id.in_(sids), AudioSpec.kind == "dialogue")
        .group_by(AudioSpec.shot_id)
    ).all():
        lines[sid] = n
    scene_ids = {s.scene_id for s in shots if s.scene_id}
    scenes = {sc.id: sc for sc in db.execute(
        select(Scene).where(Scene.id.in_(list(scene_ids) or [""]))).scalars()}

    # 创作画布：每镜所在的场次画布，和正在跑的一键出片（分镜画布据此显示「出片中」并轮询）
    from app.models.studio_board import StudioBoard, StudioRun

    board_of: dict[str, str] = {}
    for b in db.execute(select(StudioBoard).where(StudioBoard.shot_plan_id == plan.id,
                                                  StudioBoard.kind == "scene")).scalars():
        for sid in ((b.scope_json or {}).get("shot_ids") or []):
            board_of.setdefault(sid, b.id)
    running: dict[str, dict[str, Any]] = {}
    for r in db.execute(select(StudioRun).where(StudioRun.shot_plan_id == plan.id,
                                                StudioRun.status.in_(("queued", "running")))).scalars():
        for it in (r.items_json or []):
            if isinstance(it, dict) and it.get("status") in ("pending", "running") and it.get("shot_id"):
                running[it["shot_id"]] = {"run_id": r.id, "step": it.get("step"), "status": it.get("status")}

    def frame_out(f: FrameSpec | None) -> dict[str, Any] | None:
        if f is None:
            return None
        return {"id": f.id, "status": getattr(f.status, "value", f.status),
                "url": urls.get(f.asset_id) if f.asset_id else None,
                "stale": bool((f.params_json or {}).get("needs_regeneration"))}

    cards = []
    for s in shots:
        fs = frames.get(s.id, {})
        first = fs.get("first")
        regional = ((first.params_json or {}).get("regional") or {}) if first else {}
        cards.append({
            "id": s.id, "order_no": s.order_no, "scene_id": s.scene_id,
            "shot_size": s.shot_size, "duration_ms": s.duration_ms,
            "description": s.description,
            "camera": {k: (s.camera_json or {}).get(k)
                       for k in ("move", "motion_kind", "motion_decision", "rig")},
            "first": frame_out(first),
            "last": frame_out(fs.get("last")),
            "video_url": urls.get(s.video_asset_id) if s.video_asset_id else None,
            "dialogue_lines": lines.get(s.id, 0),
            "canvas_id": board_of.get(s.id),
            "canvas_run": running.get(s.id),
            # 导演出片：最近一次在跑的（run）和已挂回的（done）；画布据此轮询 /director/shots/{id}/run
            "director": {"run": (s.camera_json or {}).get("director_run"),
                         "done": (s.camera_json or {}).get("director")}
            if (s.camera_json or {}).get("director_run") or (s.camera_json or {}).get("director") else None,
            "regional": {
                "source": regional.get("source"),
                "people": len(regional.get("figures") or []),
                "preview_url": (first.params_json or {}).get("regional_preview_url")
                if first else None,
            } if regional else None,
        })
    transform = db.get(WorldTransform, plan.transform_id) if plan.transform_id else None
    return {
        "plan": {"id": plan.id, "version": plan.version,
                 "status": getattr(plan.status, "value", plan.status),
                 "aspect_ratio": (plan.config_json or {}).get("aspect_ratio") or "16:9",
                 "transform_id": plan.transform_id,
                 "profile_id": transform.target_profile_id if transform else None},
        "chapter": {"id": chapter.id, "title": chapter.title, "novel_id": chapter.novel_id}
        if chapter else None,
        "scenes": [{"id": sc.id, "order_no": sc.order_no, "title": sc.title,
                    "location": sc.location_text, "time_of_day": sc.time_of_day}
                   for sc in sorted(scenes.values(), key=lambda x: x.order_no)],
        "shots": cards,
    }


@router.get("/plans/{plan_id}/cast")
def plan_cast(plan_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """这份分镜里出场的角色，带各视角与设定图的地址 —— 资产面板直接用。

    按表演单统计出场镜数；取的是这一章所在时期的参考集（同一个人不同时期
    衣着不同，画布上看到的必须是出图时真正用的那一套）。
    """
    from app.pipelines.epochs import resolve_epoch
    from app.pipelines.identity import reference_elements

    plan = db.get(ShotPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="shot plan not found")
    transform = db.get(WorldTransform, plan.transform_id) if plan.transform_id else None
    if transform is None:
        return {"cast": []}
    doc = db.get(ScriptDoc, plan.script_doc_id)
    chapter = db.get(Chapter, doc.chapter_id) if doc else None
    order = chapter.order_no if chapter else None

    counts = dict(db.execute(
        select(ShotPerformance.entity_id, func.count(ShotPerformance.id))
        .join(Shot, Shot.id == ShotPerformance.shot_id)
        .where(Shot.shot_plan_id == plan.id)
        .group_by(ShotPerformance.entity_id)
    ).all())
    cast = []
    for eid, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        entity = db.get(WorldEntity, eid)
        if entity is None:
            continue
        epoch = resolve_epoch(db, eid, transform.target_profile_id, order)
        ref = (epoch.reference_set_json or {}) if epoch else {}
        views = {k: v.get("asset_id") for k, v in (ref.get("views") or {}).items()
                 if isinstance(v, dict) and v.get("asset_id")}
        urls = {a.id: a.url for a in db.execute(
            select(Asset).where(Asset.id.in_(list(views.values()) or [""]))).scalars()}
        elements = reference_elements(epoch) if epoch else {}
        cast.append({
            "entity_id": eid, "name": entity.display_name, "shots": n,
            "epoch": epoch.epoch_key if epoch else None,
            "look": (elements.get("wardrobe") or {}).get("en"),
            "views": {k: urls.get(aid) for k, aid in views.items()},
        })
    return {"cast": cast}
