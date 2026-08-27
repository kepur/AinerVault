"""分镜与首尾帧：参考图 → 分镜编译 → 素材绑定 → 首帧 → 尾帧。

依赖顺序是硬的，API 会挡住越级操作：
  素材参考图未就绪 → 分镜可以编，但首帧的一致性没有根
  素材未绑定       → 首帧 prompt 是空的，拒绝生成
  首帧未落地       → 尾帧无从派生，跳过并报告
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import (
    Chapter, DirectorProfile, DocStatus, FrameRole, FrameSpec, Scene, ScriptDoc, Shot,
    ShotPlan, WorldTransform,
)
from app.models.world import TransformStatus
from app.pipelines import asset_refs, frame_compose, shot_plan as sp
from app.pipelines.base import PipelineError

router = APIRouter(prefix="/api/v2", tags=["shots"])


def _transform(db: Session, tid: str) -> WorldTransform:
    t = db.get(WorldTransform, tid)
    if t is None:
        raise HTTPException(status_code=404, detail="transform not found")
    return t


def _plan(db: Session, plan_id: str) -> ShotPlan:
    p = db.get(ShotPlan, plan_id)
    if p is None:
        raise HTTPException(status_code=404, detail="shot plan not found")
    return p


def _active_doc(db: Session, chapter_id: str) -> ScriptDoc:
    doc = db.execute(
        select(ScriptDoc).where(
            ScriptDoc.chapter_id == chapter_id, ScriptDoc.status == DocStatus.active
        )
    ).scalars().first()
    if doc is None:
        raise HTTPException(status_code=409, detail="该章节还没有 active 剧本")
    return doc


# ── 1. 素材参考图（一致性的根，必须先做）────────────────────────────────────────

class RefIn(BaseModel):
    variant_ids: list[str] = Field(default_factory=list)
    kinds: list[str] = Field(default_factory=list)
    require_approved: bool = True
    regenerate: bool = False
    n: int = 1
    confirm_cost: bool = False


@router.post("/transforms/{transform_id}/asset-refs:generate")
def generate_asset_refs(transform_id: str, body: RefIn,
                        db: Session = Depends(get_db)) -> dict:
    """为素材变体生成参考图。

    style 素材先行 —— 它是其余素材的 style reference，全书画风的根。
    成本超阈值会返回 requires_confirm，带 confirm_cost=true 再调一次确认。
    """
    t = _transform(db, transform_id)
    try:
        return asset_refs.generate_refs(
            db, t, variant_ids=body.variant_ids or None,
            kinds=body.kinds or None, require_approved=body.require_approved,
            regenerate=body.regenerate, n=body.n, confirm_cost=body.confirm_cost,
        ).as_dict()
    except PipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/transforms/{transform_id}/asset-refs:sync")
def sync_asset_refs(transform_id: str, db: Session = Depends(get_db)) -> dict:
    """把已完成任务的产图挂回素材变体。"""
    return asset_refs.sync_all_refs(db, _transform(db, transform_id))


# ── 2. 分镜编译（接入导演包）──────────────────────────────────────────────────

class PlanIn(BaseModel):
    director_code: str
    transform_id: str | None = None
    target_language: str | None = None
    aspect_ratio: str = "16:9"
    activate: bool = True


@router.post("/chapters/{chapter_id}/shot-plan:generate")
def generate_shot_plan(chapter_id: str, body: PlanIn,
                       db: Session = Depends(get_db)) -> dict:
    """编译分镜。景别/运镜/切分密度由导演包的统计分布决定，不交给 LLM。"""
    if db.get(Chapter, chapter_id) is None:
        raise HTTPException(status_code=404, detail="chapter not found")
    doc = _active_doc(db, chapter_id)

    director = db.execute(
        select(DirectorProfile).where(DirectorProfile.code == body.director_code)
        .order_by(DirectorProfile.version.desc())
    ).scalars().first()
    if director is None:
        raise HTTPException(status_code=404,
                            detail=f"导演包 {body.director_code} 不存在")

    transform = None
    if body.transform_id:
        transform = _transform(db, body.transform_id)
    elif body.target_language:
        transform = db.execute(
            select(WorldTransform).where(
                WorldTransform.target_language_code == body.target_language,
                WorldTransform.status == TransformStatus.active,
            )
        ).scalars().first()

    try:
        res = sp.build_shot_plan(
            db, doc, director=director, transform=transform,
            target_language=body.target_language, activate=body.activate,
            aspect_ratio=body.aspect_ratio,
        )
    except PipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"director": director.code, **res.as_dict()}


@router.get("/chapters/{chapter_id}/shot-plan")
def get_shot_plan(chapter_id: str, db: Session = Depends(get_db)) -> dict:
    doc = _active_doc(db, chapter_id)
    plan = db.execute(
        select(ShotPlan).where(
            ShotPlan.script_doc_id == doc.id, ShotPlan.status == DocStatus.active
        )
    ).scalars().first()
    if plan is None:
        raise HTTPException(status_code=404, detail="该章节尚未编译分镜")

    shots = list(
        db.execute(
            select(Shot).where(Shot.shot_plan_id == plan.id).order_by(Shot.order_no)
        ).scalars()
    )
    frames = {}
    for f in db.execute(
        select(FrameSpec).where(FrameSpec.shot_id.in_([s.id for s in shots]))
    ).scalars():
        frames.setdefault(f.shot_id, {})[f.role.value] = f

    items = []
    for s in shots:
        pair = frames.get(s.id, {})
        scene = db.get(Scene, s.scene_id) if s.scene_id else None
        items.append({
            "id": s.id, "order_no": s.order_no,
            "scene": scene.title if scene else None,
            "shot_size": s.shot_size, "camera": s.camera_json or {},
            "duration_ms": s.duration_ms, "description": s.description,
            "status": s.status.value,
            "block_ids": s.block_ids_json or [],
            "frames": {
                role: {
                    "id": f.id, "role": role,
                    "prompt": f.prompt, "negative_prompt": f.negative_prompt,
                    "derive_from_first": f.derive_from_first,
                    "derive_instruction": f.derive_instruction,
                    "asset_keys": (f.params_json or {}).get("asset_keys") or [],
                    "reference_images": [
                        r.get("tag") for r in
                        ((f.params_json or {}).get("reference_images") or [])
                    ],
                    "asset_id": f.asset_id, "status": f.status.value,
                }
                for role, f in pair.items()
            },
        })

    return {
        "shot_plan_id": plan.id, "version": plan.version,
        "director_profile_id": plan.director_profile_id,
        "config": plan.config_json or {}, "stats": plan.stats_json or {},
        "shots": items,
    }


# ── 3. 素材绑定与 prompt 拼装 ─────────────────────────────────────────────────

class BindIn(BaseModel):
    transform_id: str
    shot_ids: list[str] = Field(default_factory=list)


@router.post("/shot-plans/{plan_id}/shots:bind-assets")
def bind_assets(plan_id: str, body: BindIn, db: Session = Depends(get_db)) -> dict:
    """绑定素材并拼好首尾帧 prompt。不调 LLM、不花钱。

    所有外观描述都来自 asset_variants —— 镜头自己只贡献「谁在哪做什么」。
    """
    plan = _plan(db, plan_id)
    t = _transform(db, body.transform_id)
    try:
        return frame_compose.bind_and_compose(
            db, plan, t, shot_ids=body.shot_ids or None
        ).as_dict()
    except PipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ── 4. 首尾帧生成 ─────────────────────────────────────────────────────────────

class FrameGenIn(BaseModel):
    shot_ids: list[str] = Field(default_factory=list)
    regenerate: bool = False
    confirm_cost: bool = False


@router.post("/shot-plans/{plan_id}/first-frames:generate")
def gen_first_frames(plan_id: str, body: FrameGenIn,
                     db: Session = Depends(get_db)) -> dict:
    """提交首帧生成。"""
    plan = _plan(db, plan_id)
    return frame_compose.generate_first_frames(
        db, plan, shot_ids=body.shot_ids or None,
        regenerate=body.regenerate, confirm_cost=body.confirm_cost,
    ).as_dict()


class LastFrameIn(FrameGenIn):
    strength: float = 0.35


@router.post("/shot-plans/{plan_id}/last-frames:generate")
def gen_last_frames(plan_id: str, body: LastFrameIn,
                    db: Session = Depends(get_db)) -> dict:
    """尾帧从首帧派生。strength 是改动幅度：0 保持原图，1 完全重绘。"""
    if not 0.0 <= body.strength <= 1.0:
        raise HTTPException(status_code=422, detail="strength 必须在 0..1")
    plan = _plan(db, plan_id)
    return frame_compose.generate_last_frames(
        db, plan, shot_ids=body.shot_ids or None, strength=body.strength,
        regenerate=body.regenerate, confirm_cost=body.confirm_cost,
    ).as_dict()


@router.post("/shot-plans/{plan_id}/frames:sync")
def sync_frames(plan_id: str, db: Session = Depends(get_db)) -> dict:
    """把已完成任务的产图挂回帧。"""
    return frame_compose.sync_frame_assets(db, _plan(db, plan_id))


class FramePatch(BaseModel):
    prompt: str | None = None
    negative_prompt: str | None = None
    derive_instruction: str | None = None
    strength: float | None = None


@router.patch("/frame-specs/{frame_id}")
def update_frame(frame_id: str, body: FramePatch,
                 db: Session = Depends(get_db)) -> dict:
    """人工改帧。改过之后 bind-assets 不再覆盖它。"""
    f = db.get(FrameSpec, frame_id)
    if f is None:
        raise HTTPException(status_code=404, detail="frame spec not found")
    if body.prompt is not None:
        f.prompt = body.prompt
    if body.negative_prompt is not None:
        f.negative_prompt = body.negative_prompt
    if body.derive_instruction is not None:
        f.derive_instruction = body.derive_instruction
    if body.strength is not None:
        params = dict(f.params_json or {})
        params["strength"] = body.strength
        f.params_json = params
    f.edited_by_human = True
    db.flush()
    return {"id": f.id, "role": f.role.value, "prompt": f.prompt,
            "edited_by_human": True}


# ── 就绪度总览 ────────────────────────────────────────────────────────────────

@router.get("/shot-plans/{plan_id}/readiness")
def readiness(plan_id: str, transform_id: str = Query(...),
              db: Session = Depends(get_db)) -> dict:
    """出图前的就绪度：素材包、绑定、首帧、尾帧各到哪一步。"""
    from app.pipelines.asset_pack import pack_status

    plan = _plan(db, plan_id)
    t = _transform(db, transform_id)
    pack = pack_status(db, t)

    shots = list(
        db.execute(select(Shot).where(Shot.shot_plan_id == plan.id)).scalars()
    )
    frames = list(
        db.execute(
            select(FrameSpec).where(FrameSpec.shot_id.in_([s.id for s in shots]))
        ).scalars()
    ) if shots else []

    firsts = [f for f in frames if f.role == FrameRole.first]
    lasts = [f for f in frames if f.role == FrameRole.last]
    return {
        "asset_pack": {
            "ready": pack["ready_for_shots"],
            "totals": pack["totals"],
            "without_reference_image": pack["totals"]["without_reference_image"],
        },
        "shots": len(shots),
        "frames": {
            "first_total": len(firsts),
            "first_composed": sum(1 for f in firsts if f.prompt),
            "first_ready": sum(1 for f in firsts if f.asset_id),
            "last_total": len(lasts),
            "last_ready": sum(1 for f in lasts if f.asset_id),
        },
        "next_step": _next_step(pack, firsts, lasts),
    }


def _next_step(pack: dict, firsts: list, lasts: list) -> str:
    if not pack["ready_for_shots"]:
        return "补齐素材包：缺变体或结构化字段不全"
    if pack["totals"]["without_reference_image"]:
        return "生成素材参考图 —— 首帧的一致性依赖它"
    if not firsts:
        return "编译分镜"
    if any(not f.prompt for f in firsts):
        return "绑定素材并拼装 prompt"
    if any(not f.asset_id for f in firsts):
        return "生成首帧"
    if any(not f.asset_id for f in lasts):
        return "从首帧派生尾帧"
    return "首尾帧已就绪，可出片段"
