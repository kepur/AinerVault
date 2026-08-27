"""音频与交付：编译 → TTS → 时长回填 → manifest。

本系统不生成视频。交付物是「首尾帧 + 音频 + 指令」，
按下游视频模型是否自带音频投影成两种 manifest。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AudioKind, AudioSpec, Scene, Shot, ShotPlan, WorldTransform
from app.pipelines import audio_compose as ac
from app.pipelines import delivery
from app.pipelines.base import PipelineError

router = APIRouter(prefix="/api/v2", tags=["audio"])


def _plan(db: Session, plan_id: str) -> ShotPlan:
    p = db.get(ShotPlan, plan_id)
    if p is None:
        raise HTTPException(status_code=404, detail="shot plan not found")
    return p


class CompileIn(BaseModel):
    transform_id: str
    include_bgm: bool = True
    include_room_tone: bool = True


@router.post("/shot-plans/{plan_id}/audio:compile")
def compile_audio(plan_id: str, body: CompileIn, db: Session = Depends(get_db)) -> dict:
    """把分镜编译成音频规格。对白绑定角色的 voice 素材，不自由挑音色。"""
    plan = _plan(db, plan_id)
    t = db.get(WorldTransform, body.transform_id)
    if t is None:
        raise HTTPException(status_code=404, detail="transform not found")
    try:
        return ac.compile_audio(
            db, plan, t, include_bgm=body.include_bgm,
            include_room_tone=body.include_room_tone,
        ).as_dict()
    except PipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class AudioGenIn(BaseModel):
    kinds: list[str] = Field(default_factory=list)
    regenerate: bool = False
    confirm_cost: bool = False


@router.post("/shot-plans/{plan_id}/audio:generate")
def generate_audio(plan_id: str, body: AudioGenIn,
                   db: Session = Depends(get_db)) -> dict:
    """提交音频生成。对白带上素材的参考音频作 voice reference。"""
    plan = _plan(db, plan_id)
    return ac.generate_audio(
        db, plan, kinds=body.kinds or None,
        regenerate=body.regenerate, confirm_cost=body.confirm_cost,
    ).as_dict()


@router.post("/shot-plans/{plan_id}/audio:backfill-durations")
def backfill_durations(plan_id: str, db: Session = Depends(get_db)) -> dict:
    """把 TTS 真实时长回填到镜头。

    时长权威链的落点。无论下游视频模型带不带音频都要做 ——
    带音频的模型也需要确定的时长约束，否则字幕对不上。
    """
    return ac.backfill_durations(db, _plan(db, plan_id))


@router.get("/shot-plans/{plan_id}/audio")
def list_audio(plan_id: str, kind: str | None = Query(None),
               db: Session = Depends(get_db)) -> dict:
    plan = _plan(db, plan_id)
    shots = list(
        db.execute(
            select(Shot).where(Shot.shot_plan_id == plan.id).order_by(Shot.order_no)
        ).scalars()
    )
    order = {s.id: s.order_no for s in shots}
    scene_ids = [s.scene_id for s in shots if s.scene_id]

    q = select(AudioSpec).where(
        (AudioSpec.shot_id.in_(list(order)))
        | ((AudioSpec.shot_id.is_(None)) & (AudioSpec.scene_id.in_(scene_ids)))
    )
    if kind:
        q = q.where(AudioSpec.kind == AudioKind(kind))
    rows = list(db.execute(q).scalars())

    items = []
    for a in rows:
        params = a.params_json or {}
        items.append({
            "id": a.id, "kind": a.kind.value,
            "shot_order": order.get(a.shot_id),
            "scene_id": a.scene_id,
            "text": (a.text or "")[:120],
            "language": a.language_code,
            "voice_asset_key": params.get("voice_asset_key"),
            "voice_id": params.get("voice_id"),
            "has_voice_reference": bool(params.get("voice_reference_asset_ids")),
            "duration_ms": a.duration_ms,
            "asset_id": a.asset_id, "status": a.status.value,
        })
    items.sort(key=lambda x: (x["shot_order"] is None, x["shot_order"] or 0))
    voiced = sum(1 for i in items if i["asset_id"])
    return {
        "items": items,
        "stats": {
            "total": len(items), "generated": voiced,
            "with_voice_reference": sum(1 for i in items if i["has_voice_reference"]),
            "total_voiced_ms": sum(i["duration_ms"] or 0 for i in items),
        },
    }


# ── 交付 ──────────────────────────────────────────────────────────────────────

@router.get("/delivery/projection")
def get_projection(db: Session = Depends(get_db)) -> dict:
    """探测下游视频模型是否自带音频。

    contract 扩展：video.image_to_video 的模型可声明
      supports: {native_audio, voice_reference, audio_track_input}
    未声明按 silent 处理 —— 保守假设不会出错，多生成的音频总能用上。
    """
    mode, detail = delivery.detect_projection(db)
    return {"projection": mode, "detail": detail}


@router.get("/shot-plans/{plan_id}/manifest")
def get_manifest(
    plan_id: str,
    projection: str = Query("auto", pattern="^(auto|native_audio|silent)$"),
    subtitles: bool = Query(True),
    db: Session = Depends(get_db),
) -> dict:
    """交付清单 —— 本系统的最终产出。

    projection=auto 按 Discovery 自动判断；也可强制指定，
    两种投影的上游产出完全相同，只是清单形态不同。
    """
    return delivery.build_manifest(
        db, _plan(db, plan_id), projection=projection,  # type: ignore[arg-type]
        include_subtitles=subtitles,
    )
