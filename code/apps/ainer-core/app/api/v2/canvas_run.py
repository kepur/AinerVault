"""画布「一键出片」接口：给一张画布（或它的几镜）开一个工作流，查进度，取消。

画布前端和外部系统（旅拍、相册、别的小说系统）用的是同一组接口，流程见 pipelines/canvas_run.py。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v2.canvas import _get_board, scope_shot_ids
from app.db import get_db
from app.ids import new_id
from app.models import Shot, StudioRun
from app.pipelines import canvas_run as cr

router = APIRouter(prefix="/api/v2/studio", tags=["studio-run"])


def run_out(db: Session, run: StudioRun) -> dict[str, Any]:
    """工作流的样子（前端 model.ts 的 RunState）。当前那一镜正在导演出片时，带上它的实时进度。"""
    items = list(run.items_json or [])
    summary = cr.summarize(items)
    cur = summary.get("current")
    if cur and cur.get("step") == "director" and cur.get("submitted"):
        from app.director import from_shot

        shot = db.get(Shot, cur["shot_id"])
        cur["director"] = from_shot.run_status(db, shot) if shot is not None else None
    return {
        "id": run.id, "board_id": run.board_id, "plan_id": run.shot_plan_id, "status": run.status,
        "profile": run.profile, "options": run.options_json or {}, "items": items, "summary": summary,
        "error": run.error,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


class RunIn(BaseModel):
    #: keyframe = 关键帧方案（默认，借鉴纳逗：定妆照＋场景图 → 关键帧 → 视频模型钉住它出片）；
    #: director = 3D 白模控制（LLM 搭景 → Blender 预演 → 身份首帧 → LTX 按控制出片）
    method: str = Field("keyframe", pattern="^(keyframe|director)$")
    #: local = 本机（FLUX.2-klein 关键帧 → LTX 2.5）；cloud = 云端（通义图像编辑 → 万相图生视频，付费）。只对 keyframe 有效
    engine: str = Field("local", pattern="^(local|cloud)$")
    #: fast = 768×448（最快，默认）；hd = 1024×576
    profile: str = Field("fast", pattern="^(fast|hd)$")
    #: auto = 有台词就先按角色音色配音、再用台词轨驱动口型；generate = 现场生成；none = 不要声音
    audio: str = Field("auto", pattern="^(auto|generate|none)$")
    #: 只补还没出片的镜头（默认）；关掉 = 范围内全部重出
    only_missing: bool = True
    #: 用户在 3D-BOX 里调过的场景沿用（默认）；关掉 = 让 LLM 重新搭景、重新定运镜（白模方案）
    reuse_scene: bool = True
    #: 这一镜已经有本方案画的关键帧就沿用（默认）；关掉 = 重画（关键帧方案）
    reuse_frames: bool = True
    #: frame = 只出分镜图（关键帧 / 身份首帧），审过再出视频；video = 一路出到视频（默认，外部系统一键出片）
    stop_after: str = Field("video", pattern="^(frame|video)$")
    #: 关键帧方案：出图前先导演审片（本机 LM Studio 把一场戏连起来看：谁是谁、首帧静态描述、LTX 运动描述）。默认开
    review: bool = True
    #: 已经审过的镜头也重审（reuse_frames=False 重画时自动重审）
    re_review: bool = False
    #: 每镜出几张关键帧候选（>1 时本机视觉模型对着定妆照挑一张）。默认 2
    candidates: int = Field(2, ge=1, le=4)
    #: 只跑这几镜（要在画布范围内）；不给 = 画布范围内全部
    shot_ids: list[str] = Field(default_factory=list, max_length=2000)


@router.post("/canvases/{board_id}:run")
def start_run(board_id: str, body: RunIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    """一键出片：画布范围内的镜头按顺序 补配音 → 关键帧 → 视频（或 3D 白模控制出片）→ 挂回。"""
    board = _get_board(db, board_id)
    if not board.shot_plan_id:
        raise HTTPException(status_code=422, detail="这张画布没挂分镜，没有镜头可出（空白画布用生成面板单独出）")
    scope = scope_shot_ids(board)
    rows = db.execute(select(Shot.id, Shot.order_no, Shot.video_asset_id)
                      .where(Shot.shot_plan_id == board.shot_plan_id)).all()
    in_scope = [(sid, no, bool(v)) for sid, no, v in rows if scope is None or sid in set(scope)]
    if body.shot_ids and not set(body.shot_ids) <= {sid for sid, _no, _v in in_scope}:
        raise HTTPException(status_code=422, detail="有镜头不在这张画布的范围里")
    items = cr.pick_items(in_scope, body.shot_ids or None, body.only_missing)
    if not items:
        raise HTTPException(status_code=422, detail={
            "code": "NOTHING_TO_RUN",
            "message": "范围内的镜头都已经出过片了（要重出请关掉「只补没出片的」）",
        })
    busy = db.execute(select(StudioRun).where(StudioRun.board_id == board.id,
                                              StudioRun.status.in_(cr.ACTIVE))).scalars().first()
    if busy is not None:
        raise HTTPException(status_code=409, detail={
            "code": "RUN_EXISTS", "message": "这张画布已经有一个工作流在跑了", "run_id": busy.id,
        })
    run = StudioRun(id=new_id("run"), board_id=board.id, shot_plan_id=board.shot_plan_id, status="queued",
                    profile=body.profile, items_json=items,
                    options_json={"method": body.method, "engine": body.engine, "audio": body.audio,
                                  "only_missing": body.only_missing, "reuse_scene": body.reuse_scene,
                                  "reuse_frames": body.reuse_frames, "stop_after": body.stop_after,
                                  "review": body.review, "re_review": body.re_review, "candidates": body.candidates})
    db.add(run)
    db.commit()
    cr.kick()
    ahead = db.execute(select(StudioRun.id).where(StudioRun.status.in_(cr.ACTIVE),
                                                  StudioRun.created_at < run.created_at)).all()
    return {**run_out(db, run), "queued_behind": len(ahead)}


@router.get("/runs/{run_id}")
def get_run(run_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    run = db.get(StudioRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="工作流不存在")
    if run.status in cr.ACTIVE:
        cr.ensure_worker()                            # core 重启后第一次有人来看，顺手把后台线程拉起来
    return run_out(db, run)


@router.get("/canvases/{board_id}/runs")
def board_runs(board_id: str, limit: int = Query(5, ge=1, le=50), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    _get_board(db, board_id)
    rows = db.execute(select(StudioRun).where(StudioRun.board_id == board_id)
                      .order_by(StudioRun.created_at.desc()).limit(limit)).scalars().all()
    if any(r.status in cr.ACTIVE for r in rows):
        cr.ensure_worker()
    return [run_out(db, r) for r in rows]


@router.get("/runs")
def active_runs(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """所有没跑完的工作流（排在前面的先跑）。"""
    rows = db.execute(select(StudioRun).where(StudioRun.status.in_(cr.ACTIVE))
                      .order_by(StudioRun.created_at)).scalars().all()
    if rows:
        cr.ensure_worker()
    return [run_out(db, r) for r in rows]


@router.post("/runs/{run_id}:cancel")
def cancel_run(run_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    run = db.get(StudioRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="工作流不存在")
    if run.status not in cr.ACTIVE:
        return run_out(db, run)
    return run_out(db, cr.cancel(db, run))
