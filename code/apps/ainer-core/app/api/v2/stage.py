"""舞台（Plan A）接口。P0：素材卡。

    GET   /api/v2/stage/cards?plan_id=…[&scene_id=…][&shot_ids=a,b]   这几镜要用到的素材卡（人 + 地点）
    PATCH /api/v2/stage/cards/{card_id}/physical                        人改物理尺寸（身高、体型），写进本章那一期
范围可以是一镜、几镜（shot_ids）、一场（scene_id）或整份分镜（只给 plan_id）。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.stage import cards as C
from app.stage.schema import Physical

router = APIRouter(prefix="/api/v2/stage", tags=["stage"])


def _plan_and_shots(db: Session, plan_id: str, scene_id: str | None, shot_ids: str | None):
    from app.models import Shot, ShotPlan

    plan = db.get(ShotPlan, plan_id)
    if plan is None:
        raise HTTPException(404, "没有这份分镜计划")
    q = select(Shot).where(Shot.shot_plan_id == plan_id)
    if scene_id:
        q = q.where(Shot.scene_id == scene_id)
    if shot_ids:
        q = q.where(Shot.id.in_([s for s in shot_ids.split(",") if s]))
    shots = list(db.execute(q.order_by(Shot.order_no)).scalars())
    if not shots:
        raise HTTPException(404, "这个范围里没有镜头")
    return plan, shots


@router.get("/cards")
def list_cards(plan_id: str | None = None, scene_id: str | None = None, shot_ids: str | None = None,
               novel_id: str | None = None, board_id: str | None = None,
               world_profile_id: str | None = None,
               db: Session = Depends(get_db)) -> dict[str, Any]:
    if sum(bool(i) for i in (plan_id, novel_id, board_id)) != 1:
        raise HTTPException(422, detail={"code": "scope_required", "message": "指定 plan_id、novel_id、board_id 之一", "issues": []})
    if plan_id:
        plan, shots = _plan_and_shots(db, plan_id, scene_id, shot_ids)
        cards = C.cards_for_shots(db, plan, shots)
        return {"plan_id": plan_id, "shots": len(shots), "cards": [c.model_dump() for c in cards]}
    if scene_id or shot_ids:
        raise HTTPException(422, detail="scene_id/shot_ids 筛选需要 plan_id")
    from app.models import Chapter, EntityKind, Novel, WorldEntity
    from app.production import service as svc
    from app.stage.schema import AssetCard

    issues, chapter_order, transform_id = [], None, None
    try:
        if board_id:
            row = svc.board(db, board_id)
            ctx, issues = svc.context_for(db, row)
            novel_id, profile_id, transform_id = ctx.novel_id, ctx.world_profile_id, ctx.transform_id
            if world_profile_id and world_profile_id != profile_id:
                raise svc.ProductionError("world_mismatch", "世界观与画布不一致")
            if ctx.chapter_id:
                chapter_order = svc.get(db, Chapter, ctx.chapter_id, row.workspace_id).order_no
            workspace = row.workspace_id
        else:
            novel = svc.get(db, Novel, novel_id)
            profile_id, workspace = world_profile_id or novel.source_world_profile_id, novel.workspace_id
        if not novel_id:
            return {"board_id": board_id, "novel_id": None, "plan_id": None, "shots": 0, "cards": [], "issues": issues}
        rows = list(db.scalars(select(WorldEntity).where(WorldEntity.novel_id == novel_id,
                                                       WorldEntity.workspace_id == workspace,
                                                       WorldEntity.kind.in_([EntityKind.character, EntityKind.location, EntityKind.prop])).order_by(WorldEntity.id)))
        out = []
        for ent in rows:
            name = svc.entity_data(db, ent, transform_id)
            views, epoch_key = {}, None
            if ent.kind == EntityKind.character:
                physical = C.infer_physical(ent.appearance, ent.summary, ent.visual_prompt)
            else:
                physical = Physical(height_m=None, build=None, source="default")
            try:
                epoch = svc.choose_epoch(db, ent, profile_id, chapter_order=chapter_order)
                pack = svc.pack_data(db, ent, epoch)
                epoch_key = epoch.epoch_key
                if ent.kind == EntityKind.character:
                    views = {k: p["media"]["url"] for k, p in pack["views"].items()}
                    issues.extend({**i, "entity_id": ent.id} for i in pack["issues"])
                    if pack.get("physical") and pack["physical"].get("source") in ("user", "inferred", "default"):
                        physical = Physical(**{k: v for k, v in pack["physical"].items() if k in Physical.model_fields})
                else:
                    stored_views = (epoch.reference_set_json or {}).get("views") or {}
                    urls = C._urls(db, [v.get("asset_id") for v in stored_views.values() if isinstance(v, dict)])
                    views = {k: urls[v["asset_id"]] for k, v in stored_views.items() if isinstance(v, dict) and v.get("asset_id") in urls and k != "sheet"}
            except svc.ProductionError as exc:
                issues.append({"code": exc.code, "message": str(exc), "entity_id": ent.id})
            prefix = {EntityKind.character: "e", EntityKind.location: "l", EntityKind.prop: "p"}[ent.kind]
            out.append(AssetCard(id=f"{prefix}:{ent.id}", kind=ent.kind.value, entity_id=ent.id,
                                 name=ent.display_name, screen_name=name["screen_name"], epoch=epoch_key,
                                 views=views, physical=physical, look_en=(ent.visual_prompt or "")[:400]).model_dump())
        return {"board_id": board_id, "novel_id": novel_id, "plan_id": None, "shots": 0, "cards": out, "issues": issues}
    except svc.ProductionError as exc:
        raise HTTPException(exc.status, detail={"code": exc.code, "message": str(exc), "issues": []}) from exc


@router.patch("/cards/{card_id}/physical")
def patch_physical(card_id: str, body: Physical, plan_id: str = Query(...), db: Session = Depends(get_db)) -> dict[str, Any]:
    from app.models import Chapter, ScriptDoc, ShotPlan, WorldTransform

    plan = db.get(ShotPlan, plan_id)
    if plan is None:
        raise HTTPException(404, "没有这份分镜计划")
    doc = db.get(ScriptDoc, plan.script_doc_id) if plan.script_doc_id else None
    chapter = db.get(Chapter, doc.chapter_id) if doc else None
    transform = db.get(WorldTransform, plan.transform_id) if plan.transform_id else None
    try:
        p = C.set_physical(db, card_id, body, profile_id=transform.target_profile_id if transform else None,
                           chapter_order=getattr(chapter, "order_no", None))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    db.commit()
    return {"card_id": card_id, "physical": p.model_dump()}


class StageCompileReq(Physical.__base__):
    stage: Any
    shots: list[Any] = []
    fps: int = 24
    title: str | None = None


@router.post("/compile")
def compile_stage(req: dict[str, Any]) -> dict[str, Any]:
    """将剧情舞台 (SceneStage) 与镜头覆盖 (CoverageShot) 编译为标准 3D-BOX / Blender SceneProtocol。"""
    from app.stage.compile import compile_stage_to_protocol
    from app.stage.schema import CoverageShot, SceneStage

    try:
        stage = SceneStage.model_validate(req.get("stage"))
        shots = [CoverageShot.model_validate(s) for s in (req.get("shots") or [])]
        fps = int(req.get("fps") or 24)
        title = req.get("title")
        protocol = compile_stage_to_protocol(stage, shots, fps=fps, title=title)
        return {"ok": True, "protocol": protocol}
    except Exception as exc:
        raise HTTPException(422, detail=f"舞台编译失败：{exc}") from exc


@router.post("/state-at")
def get_state_at(req: dict[str, Any]) -> dict[str, Any]:
    """计算舞台在任意时间 t（秒）的连续空间站位、朝向与表演状态。"""
    from app.stage.compile import state_at
    from app.stage.schema import SceneStage

    try:
        stage = SceneStage.model_validate(req.get("stage"))
        t = float(req.get("t", 0.0))
        res = state_at(stage, t)
        return {"ok": True, "state": res}
    except Exception as exc:
        raise HTTPException(422, detail=f"状态推演失败：{exc}") from exc

