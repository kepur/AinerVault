"""创作画布的自由生成：模型下拉、提交、查任务。

组装逻辑全在 app.capability.generic；这里只做 HTTP 形状。
任务本身仍是普通的 gen_tasks 行（ref_kind=canvas_node），任务中心里照样看得到、能重试。
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.capability import generic
from app.db import get_db

router = APIRouter(prefix="/api/v2/studio", tags=["studio-generate"])


@router.get("/models")
def models(media: Literal["image", "video"] = Query(...),
           db: Session = Depends(get_db)) -> dict[str, Any]:
    """生成面板的模型下拉（前端 ModelOption[]）。被付费闸拦着的 ready=false 并注明原因。"""
    return {"models": generic.list_models(db, media)}


@router.post("/generate")
def generate(body: generic.GenerateIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    """提交 count 条生成任务（前端 GenerateResult）。

    409 COST_CONFIRM_REQUIRED：预估花费超过阈值，带 confirm_cost=true 再发一次。
    409 MODEL_BLOCKED：付费模型没被批准 / 免费额度用尽 —— confirm_cost 放不过去，
        批准只在 设置 › 能力路由 里给（service.route_blocked 的规矩）。
    """
    try:
        result = generic.submit(db, body)
    except generic.GenerateError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail()) from exc
    # **先提交再回应**（同 blocking.py）：get_db 的 commit 在响应发出之后才跑，
    # 前端拿到 task id 立刻来查，可能查到「task not found」
    db.commit()
    return result


@router.get("/generate/{task_id}")
def generate_state(task_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """任务状态（前端 GenTaskState）。assets 只给本库 /media 地址，网关临时地址一律不给。"""
    state = generic.task_state(db, task_id)
    if state is None:
        raise HTTPException(status_code=404, detail="task not found")
    db.commit()
    return state
