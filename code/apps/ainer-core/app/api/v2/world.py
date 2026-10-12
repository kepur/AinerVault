"""空间 World DB 接口：世界/版本快照、空间与文本查询、章节 delta、一场一演与逐镜 take、编译 Blender 任务。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import WorldDelta, WorldPerformance, WorldTake
from app.worldmodel import compile as wc
from app.worldmodel import service as ws

router = APIRouter(prefix="/api/v2/worlds", tags=["spatial-world"])


def _fail(db: Session, exc: ws.WorldError):
    db.rollback()
    raise HTTPException(exc.status, detail={"code": exc.code, "message": str(exc)}) from exc


class WorldCreate(BaseModel):
    title: str
    novel_id: str | None = None
    chunk_size_m: float = Field(8.0, gt=0.5, le=256)
    style_ref: dict | None = None


class DeltaPropose(BaseModel):
    ops: list[dict[str, Any]]
    chapter_id: str | None = None
    base_version: int | None = None
    note: str | None = None


class DeltaReject(BaseModel):
    reason: str = ""


class PerformanceCreate(BaseModel):
    scene_key: str
    region_key: str
    duration_ms: int
    tracks: dict[str, Any]
    fps: int = 24
    mood: dict | None = None
    director_scene_id: str | None = None
    check: bool = True
    max_rounds: int = Field(3, ge=0, le=5)


class TakeCreate(BaseModel):
    shot_key: str
    start_ms: int
    end_ms: int
    camera: dict[str, Any]
    order_no: int = 0
    route: str | None = None
    fps: int = 8
    focus: list[str] | None = None
    mood: str | None = None


def _delta_out(d: WorldDelta) -> dict[str, Any]:
    return {"id": d.id, "world_id": d.world_id, "chapter_id": d.chapter_id, "base_version": d.base_version,
            "ops": d.ops, "status": d.status, "result_version": d.result_version, "report": d.report, "note": d.note}


@router.post("")
def create_world(body: WorldCreate, db: Session = Depends(get_db)):
    w = ws.create_world(db, title=body.title, novel_id=body.novel_id, chunk_size_m=body.chunk_size_m,
                        style_ref=body.style_ref)
    db.commit()
    return ws.snapshot(db, w.id)["world"]


@router.get("/{world_id}")
def get_world(world_id: str, version: int | None = None, region: list[str] | None = Query(None),
              db: Session = Depends(get_db)):
    try:
        return ws.snapshot(db, world_id, version, region)
    except ws.WorldError as exc:
        _fail(db, exc)


@router.get("/{world_id}/regions")
def regions(world_id: str, near: str | None = None, radius: float = 10.0, q: str | None = None,
            version: int | None = None, db: Session = Depends(get_db)):
    try:
        if near:
            try:
                x, y = (float(v) for v in near.split(","))
            except ValueError:
                raise HTTPException(422, detail={"code": "bad_near", "message": "near 格式为 x,y"})
            return {"items": ws.regions_near(db, world_id, x, y, radius, version)}
        if q:
            return {"items": ws.search_regions(db, world_id, q, version)}
        return {"items": ws.snapshot(db, world_id, version)["regions"]}
    except ws.WorldError as exc:
        _fail(db, exc)


@router.post("/{world_id}/deltas:propose")
def propose(world_id: str, body: DeltaPropose, db: Session = Depends(get_db)):
    try:
        d = ws.propose_delta(db, world_id, body.ops, chapter_id=body.chapter_id, base_version=body.base_version,
                             note=body.note)
        db.commit()
        return _delta_out(d)
    except ws.WorldError as exc:
        _fail(db, exc)


@router.get("/{world_id}/deltas")
def list_deltas(world_id: str, db: Session = Depends(get_db)):
    rows = db.scalars(select(WorldDelta).where(WorldDelta.world_id == world_id).order_by(WorldDelta.created_at))
    return {"items": [_delta_out(d) for d in rows]}


@router.post("/deltas/{delta_id}:apply")
def apply(delta_id: str, db: Session = Depends(get_db)):
    try:
        d = ws.apply_delta(db, delta_id)
        db.commit()
        return _delta_out(d)
    except ws.WorldError as exc:
        # 冲突/拒绝的状态要留下来（不回滚状态记录）
        db.commit()
        raise HTTPException(exc.status, detail={"code": exc.code, "message": str(exc)}) from exc


@router.post("/deltas/{delta_id}:reject")
def reject(delta_id: str, body: DeltaReject, db: Session = Depends(get_db)):
    try:
        d = ws.reject_delta(db, delta_id, body.reason)
        db.commit()
        return _delta_out(d)
    except ws.WorldError as exc:
        _fail(db, exc)


@router.post("/{world_id}/performances")
def create_performance(world_id: str, body: PerformanceCreate, db: Session = Depends(get_db)):
    try:
        perf = body.model_dump(exclude={"check", "max_rounds"})
        report = None
        if body.check:
            snap = ws.snapshot(db, world_id, region_keys=[body.region_key])
            perf, rounds = wc.bounded_stage(snap, {**perf, "rev": 1}, body.max_rounds)
            report = {"rounds": rounds, "ok": rounds[-1]["ok"]}
        p = ws.create_performance(db, world_id, scene_key=body.scene_key, region_key=body.region_key,
                                  duration_ms=body.duration_ms, tracks=perf["tracks"], fps=body.fps, mood=body.mood,
                                  director_scene_id=body.director_scene_id)
        p.check_report = report
        db.commit()
        return ws.performance_out(p, [])
    except ws.WorldError as exc:
        _fail(db, exc)


def _perf(db: Session, pid: str) -> WorldPerformance:
    p = db.get(WorldPerformance, pid)
    if p is None:
        raise HTTPException(404, detail={"code": "performance_not_found", "message": "表演不存在"})
    return p


@router.get("/performances/{pid}")
def get_performance(pid: str, db: Session = Depends(get_db)):
    p = _perf(db, pid)
    return ws.performance_out(p, list(db.scalars(select(WorldTake).where(WorldTake.performance_id == p.id))))


@router.post("/performances/{pid}/takes")
def add_take(pid: str, body: TakeCreate, db: Session = Depends(get_db)):
    p = _perf(db, pid)
    try:
        t = ws.add_take(db, p, **body.model_dump())
        db.commit()
        return ws.take_out(t)
    except ws.WorldError as exc:
        _fail(db, exc)


@router.post("/performances/{pid}/takes/{take_id}:compile")
def compile_take(pid: str, take_id: str, width: int = 640, height: int = 384, db: Session = Depends(get_db)):
    p = _perf(db, pid)
    t = db.get(WorldTake, take_id)
    if t is None or t.performance_id != p.id:
        raise HTTPException(404, detail={"code": "take_not_found", "message": "take 不存在"})
    try:
        snap = ws.snapshot(db, p.world_id, p.world_version, [p.region_key])
    except ws.WorldError as exc:
        _fail(db, exc)
    return wc.compile_take_job(snap, ws.performance_out(p), ws.take_out(t), out_dir="", resolution=(width, height))
