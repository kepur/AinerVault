"""手动模式的接口。

和交付清单（/manifest）指向同一批数据，区别只在投影方式：
manifest 给程序，handoff 给人。所以这里除了 JSON，还出三种落地文件 ——
字幕、剪辑标记表、离线手册。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ShotPlan
from app.pipelines import handoff as hf

router = APIRouter(prefix="/api/v2", tags=["handoff"])


def _plan(plan_id: str, db: Session) -> ShotPlan:
    plan = db.get(ShotPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="shot plan not found")
    return plan


@router.get("/shot-plans/{plan_id}/handoff")
def get_handoff(plan_id: str, target: str = Query("generic"),
                db: Session = Depends(get_db)) -> dict:
    """轨道化时间轴 + 每格可复制的提示词。"""
    return hf.build_handoff(db, _plan(plan_id, db), target=target)


@router.get("/shot-plans/{plan_id}/handoff.srt", response_class=PlainTextResponse)
def get_srt(plan_id: str, target: str = Query("generic"),
            db: Session = Depends(get_db)) -> PlainTextResponse:
    data = hf.build_handoff(db, _plan(plan_id, db), target=target)
    return PlainTextResponse(hf.to_srt(data), media_type="text/plain; charset=utf-8")


@router.get("/shot-plans/{plan_id}/handoff.csv", response_class=PlainTextResponse)
def get_csv(plan_id: str, target: str = Query("generic"),
            db: Session = Depends(get_db)) -> PlainTextResponse:
    data = hf.build_handoff(db, _plan(plan_id, db), target=target)
    # BOM 是给 Excel 的：没有它，中文列在 Windows 上打开是乱码，
    # 而这份表的用途正是拖进剪辑软件之前先用表格核一遍
    return PlainTextResponse("﻿" + hf.to_csv(data),
                             media_type="text/csv; charset=utf-8")


@router.get("/shot-plans/{plan_id}/handoff.md", response_class=PlainTextResponse)
def get_markdown(plan_id: str, target: str = Query("generic"),
                 db: Session = Depends(get_db)) -> PlainTextResponse:
    data = hf.build_handoff(db, _plan(plan_id, db), target=target)
    return PlainTextResponse(hf.to_markdown(data),
                             media_type="text/markdown; charset=utf-8")
