"""world-greybox 可选路径的接口：开关、运行（启动/续跑/进度）、逐镜 QA、单镜重渲、选择/审批（原管线 vs greybox）。

默认路径（原动态漫剧管线）不经过这里；所有写操作都要 feature flag world_greybox_enabled + 作用域开关。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import WorldGreyboxSwitch, WorldPerformance, WorldPipelineRun, WorldTake
from app.worldmodel import pipeline, runs, switches
from app.worldmodel import service as ws

router = APIRouter(prefix="/api/v2/world-greybox", tags=["world-greybox"])


def _err(e: runs.RunError):
    raise HTTPException(e.status, detail={"code": e.code, "message": str(e)}) from e


def _run(db: Session, run_id: str) -> WorldPipelineRun:
    r = db.get(WorldPipelineRun, run_id)
    if r is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "运行不存在"})
    return r


# ---------------------------------------------------------------- 开关
class SwitchIn(BaseModel):
    scope_kind: Literal["novel", "chapter", "production", "plan", "shot"]
    scope_id: str
    enabled: bool
    fallback_to_original: bool = True
    note: str | None = None


@router.get("/flag")
def flag() -> dict:
    return {"world_greybox_enabled": switches.global_enabled(), "default_path": "original motion-comic pipeline"}


@router.get("/switches")
def list_switches(scope_id: str | None = None, db: Session = Depends(get_db)) -> dict:
    q = select(WorldGreyboxSwitch)
    if scope_id:
        q = q.where(WorldGreyboxSwitch.scope_id == scope_id)
    return {"switches": [switches.out(s) for s in db.scalars(q)], "flag": switches.global_enabled()}


@router.put("/switches")
def put_switch(body: SwitchIn, db: Session = Depends(get_db)) -> dict:
    sw = switches.set_switch(db, body.scope_kind, body.scope_id, enabled=body.enabled,
                             fallback_to_original=body.fallback_to_original, note=body.note)
    db.commit()
    return switches.out(sw)


@router.get("/switches:resolve")
def resolve(shot: str | None = None, plan: str | None = None, chapter: str | None = None,
            production: str | None = None, novel: str | None = None, db: Session = Depends(get_db)) -> dict:
    d = switches.resolve(db, shot=shot, plan=plan, chapter=chapter, production=production, novel=novel)
    return {"enabled": d.enabled, "fallback_to_original": d.fallback_to_original, "scope": d.scope, "reason": d.reason}


# ---------------------------------------------------------------- 运行
class RunIn(BaseModel):
    world_id: str
    scope_kind: Literal["novel", "chapter", "production", "plan", "shot"]
    scope_id: str
    title: str | None = None
    config: dict[str, Any]
    out_dir: str | None = None
    import_state: str | None = None
    start: bool = True


@router.post("/runs")
def create_run(body: RunIn, db: Session = Depends(get_db)) -> dict:
    try:
        r = runs.create(db, world_id=body.world_id, scope_kind=body.scope_kind, scope_id=body.scope_id,
                        config=body.config, title=body.title, out_dir=body.out_dir, import_state=body.import_state)
        db.commit()
        if body.start:
            runs.start(db, r)
    except runs.RunError as e:
        db.rollback()
        _err(e)
    return runs.out(r)


@router.get("/runs")
def list_runs(scope_id: str | None = None, db: Session = Depends(get_db)) -> dict:
    return {"runs": [runs.out(r) for r in runs.list_runs(db, scope_id)]}


@router.get("/runs/{run_id}")
def get_run(run_id: str, full: bool = False, db: Session = Depends(get_db)) -> dict:
    return runs.out(_run(db, run_id), with_state=full)


@router.post("/runs/{run_id}:start")
def start_run(run_id: str, db: Session = Depends(get_db)) -> dict:
    r = _run(db, run_id)
    try:
        runs.start(db, r)
    except runs.RunError as e:
        _err(e)
    return runs.out(r)


@router.get("/runs/{run_id}/shots")
def shots(run_id: str, db: Session = Depends(get_db)) -> dict:
    r = _run(db, run_id)
    ctx = pipeline.Ctx(db, r)
    return {"shots": pipeline.shot_rows(ctx), "running": runs.worker_pid(r) is not None}


@router.post("/runs/{run_id}/shots/{n}:rerender")
def rerender(run_id: str, n: int, db: Session = Depends(get_db)) -> dict:
    """单镜重渲（有界：在已有尝试之上最多再 max_retry+1 次）；跑完自动重拼成片。"""
    r = _run(db, run_id)
    if runs.worker_pid(r):
        raise HTTPException(409, detail={"code": "busy", "message": "运行正在进行，结束后再重渲这一镜"})
    st = r.state or {"shots": {}}
    sh = st.setdefault("shots", {}).setdefault(str(n), {})
    sh["rerender_requested"] = True
    sh.pop("final", None)
    r.state = {**st}
    db.commit()
    try:
        runs.start(db, r, force=[n], only=[n])
    except runs.RunError as e:
        _err(e)
    return runs.out(r)


class SelectIn(BaseModel):
    source: Literal["greybox", "original", "auto"]
    attempt_index: int | None = None
    approve: bool = False


@router.post("/runs/{run_id}/shots/{n}:select")
def select_take(run_id: str, n: int, body: SelectIn, db: Session = Depends(get_db)) -> dict:
    """人工选择/审批：本镜用原管线成片还是某次 greybox 尝试（覆盖自动选择）；auto = 撤销覆盖。改完需 :start 重拼成片。"""
    r = _run(db, run_id)
    if runs.worker_pid(r):
        raise HTTPException(409, detail={"code": "busy", "message": "运行正在进行"})
    ctx = pipeline.Ctx(db, r)
    rec = ctx.rec(n)
    if body.source == "auto":
        rec.pop("override", None)
    else:
        rec["override"] = {"source": body.source, "attempt_index": body.attempt_index}
    rec["approved"] = body.approve
    s = ctx.shot_cfg(n)
    pipeline.select(ctx, s)
    ctx.save()
    return {"shot": n, "final": rec.get("final"), "approved": rec["approved"]}


@router.get("/runs/{run_id}/file")
def file(run_id: str, path: str = Query(...), db: Session = Depends(get_db)):
    """只许读本运行目录和 core media 下的文件（片段、白模、成片）。"""
    r = _run(db, run_id)
    p = Path(path).resolve()
    roots = [Path(r.out_dir).resolve(), pipeline.MEDIA.resolve()]
    for k in ("frames",):
        src = (r.config or {}).get(k) or {}
        if src.get("path"):
            roots.append(Path(src["path"]).resolve().parent)
    if not any(p.is_relative_to(root) for root in roots) or not p.is_file():
        raise HTTPException(404, detail={"code": "not_found", "message": "文件不在本运行范围内"})
    return FileResponse(p)


@router.get("/runs/{run_id}/world")
def world_map(run_id: str, db: Session = Depends(get_db)) -> dict:
    """面板用：区域/chunk/实例/地标 + 每场表演的走位轨迹 + 每镜相机。"""
    r = _run(db, run_id)
    snap = ws.snapshot(db, r.world_id)
    perfs = []
    for pid in (r.config or {}).get("performances", []):
        p = db.get(WorldPerformance, pid)
        if p is None:
            continue
        tks = db.scalars(select(WorldTake).where(WorldTake.performance_id == p.id).order_by(WorldTake.order_no))
        perfs.append({"id": p.id, "scene_key": p.scene_key, "region_key": p.region_key, "duration_ms": p.duration_ms,
                      "rev": p.rev, "check_ok": (p.check_report or {}).get("ok"),
                      "tracks": {a: {"keys": tr["keys"], "clips": tr.get("clips", [])} for a, tr in p.tracks.items()},
                      "takes": [{"n": t.order_no, "start_ms": t.start_ms, "end_ms": t.end_ms, "camera": t.camera,
                                 "status": t.status} for t in tks]})
    return {"world": snap["world"], "version": snap["version"], "regions": snap["regions"], "chunks": snap["chunks"],
            "instances": snap["instances"], "landmarks": snap["landmarks"], "portals": snap.get("portals", []),
            "performances": perfs}
