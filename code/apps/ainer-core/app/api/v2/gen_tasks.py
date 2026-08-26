"""任务中心 + 中间层回调入口。"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.capability.client import verify_signature
from app.capability.schemas import Task
from app.capability.service import poll_task, retry_task
from app.config import settings
from app.db import get_db
from app.models import GenTask, TaskStatus

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2/gen-tasks", tags=["gen-tasks"])


class GenTaskOut(BaseModel):
    id: str
    capability: str
    status: str
    provider: str | None = None
    model: str | None = None
    attempt: int
    ref_kind: str | None = None
    ref_id: str | None = None
    novel_id: str | None = None
    chapter_id: str | None = None
    error: dict | None = None
    usage: dict | None = None
    warnings: list | None = None
    result: dict | None = None
    submitted_at: str | None = None
    finished_at: str | None = None

    @classmethod
    def of(cls, t: GenTask) -> GenTaskOut:
        return cls(
            id=t.id, capability=t.capability, status=t.status.value,
            provider=t.provider, model=t.model, attempt=t.attempt or 0,
            ref_kind=t.ref_kind, ref_id=t.ref_id,
            novel_id=t.novel_id, chapter_id=t.chapter_id,
            error=t.error_json, usage=t.usage_json, warnings=t.warnings_json,
            result=t.result_json,
            submitted_at=t.submitted_at.isoformat() if t.submitted_at else None,
            finished_at=t.finished_at.isoformat() if t.finished_at else None,
        )


@router.post("/callback", include_in_schema=True)
async def capability_callback(request: Request, db: Session = Depends(get_db)) -> Response:
    """中间层任务终态回调。HMAC 校验，无需 JWT。

    按 provider_task_id 幂等 —— 重复送达不会重复建资产。
    """
    raw = await request.body()
    sig = request.headers.get("X-Cap-Signature")
    if not verify_signature(settings.callback_secret, raw, sig):
        log.warning("回调签名校验失败 task=%s", request.headers.get("X-Cap-Task-Id"))
        raise HTTPException(status_code=401, detail="invalid signature")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"invalid json: {exc}") from exc

    result = Task.model_validate(payload)
    task = db.execute(
        select(GenTask).where(GenTask.provider_task_id == result.task_id)
    ).scalars().first()
    if task is None:
        # 不是错误：可能是本地已清理的任务，或另一实例提交的。确认接收避免中间层无谓重试。
        log.info("回调对应的本地任务不存在 provider_task_id=%s", result.task_id)
        return Response(status_code=200)

    from app.capability.service import apply_task_result

    apply_task_result(db, task, result)
    return Response(status_code=200)


@router.get("")
def list_tasks(
    status: str | None = Query(None),
    capability: str | None = Query(None),
    chapter_id: str | None = Query(None),
    novel_id: str | None = Query(None),
    ref_kind: str | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    q = select(GenTask)
    if status:
        q = q.where(GenTask.status == TaskStatus(status))
    if capability:
        q = q.where(GenTask.capability == capability)
    if chapter_id:
        q = q.where(GenTask.chapter_id == chapter_id)
    if novel_id:
        q = q.where(GenTask.novel_id == novel_id)
    if ref_kind:
        q = q.where(GenTask.ref_kind == ref_kind)

    total = db.execute(select(func.count()).select_from(q.subquery())).scalar_one()
    rows = db.execute(
        q.order_by(GenTask.created_at.desc()).offset((page - 1) * size).limit(size)
    ).scalars().all()
    return {
        "items": [GenTaskOut.of(t).model_dump() for t in rows],
        "total": total, "page": page, "size": size,
    }


@router.get("/summary")
def task_summary(
    chapter_id: str | None = Query(None),
    novel_id: str | None = Query(None),
    db: Session = Depends(get_db),
) -> dict:
    """按状态聚合 + 累计成本。驱动顶栏的「N 任务运行中」和成本看板。"""
    q = select(GenTask.status, func.count(), func.coalesce(
        func.sum(func.cast(GenTask.usage_json["cost"].astext, __import__("sqlalchemy").Float)), 0.0
    ))
    if chapter_id:
        q = q.where(GenTask.chapter_id == chapter_id)
    if novel_id:
        q = q.where(GenTask.novel_id == novel_id)
    rows = db.execute(q.group_by(GenTask.status)).all()

    by_status = {s.value: 0 for s in TaskStatus}
    total_cost = 0.0
    for status, count, cost in rows:
        by_status[status.value] = count
        total_cost += float(cost or 0)
    active = by_status["queued"] + by_status["submitted"] + by_status["running"]
    return {
        "by_status": by_status,
        "active": active,
        "failed": by_status["failed"],
        "total_cost": round(total_cost, 6),
    }


@router.get("/{task_id}")
def get_task(task_id: str, db: Session = Depends(get_db)) -> dict:
    t = db.get(GenTask, task_id)
    if t is None:
        raise HTTPException(status_code=404, detail="task not found")
    return GenTaskOut.of(t).model_dump()


@router.post("/{task_id}:poll")
def poll(task_id: str, db: Session = Depends(get_db)) -> dict:
    t = db.get(GenTask, task_id)
    if t is None:
        raise HTTPException(status_code=404, detail="task not found")
    return GenTaskOut.of(poll_task(db, t)).model_dump()


@router.post("/{task_id}:retry")
def retry(task_id: str, db: Session = Depends(get_db)) -> dict:
    t = db.get(GenTask, task_id)
    if t is None:
        raise HTTPException(status_code=404, detail="task not found")
    try:
        return GenTaskOut.of(retry_task(db, t)).model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{task_id}:cancel")
def cancel(task_id: str, db: Session = Depends(get_db)) -> dict:
    from app.capability.client import CapabilityClient
    from app.capability.errors import CapabilityError
    from app.models import CapabilityEndpoint

    t = db.get(GenTask, task_id)
    if t is None:
        raise HTTPException(status_code=404, detail="task not found")
    if t.status in {TaskStatus.succeeded, TaskStatus.failed, TaskStatus.cancelled}:
        raise HTTPException(status_code=409, detail=f"任务已{t.status.value}")

    if t.provider_task_id and t.endpoint_id:
        ep = db.get(CapabilityEndpoint, t.endpoint_id)
        if ep:
            with CapabilityClient(ep.base_url, auth=ep.auth_json or {}) as c:
                try:
                    c.cancel(t.provider_task_id)
                except CapabilityError as exc:
                    log.info("上游取消失败（继续本地取消）: %s", exc)
    t.status = TaskStatus.cancelled
    t.poll_after = None
    db.flush()
    return GenTaskOut.of(t).model_dump()
