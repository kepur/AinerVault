"""本机出图队列：风格封面、官方角色立绘、表情九宫格、造型室试穿 —— 一张一张跑。

本机只有一块 GPU，同时提交只会互相拖慢、把单张推过超时。所以只有一个工作线程，
按优先级（造型室试穿是人在等，排最前）先来先出；每张提交后轮询到出结果再提交下一张。
队列在内存里：服务重启就清空，已经出好的图都已落库。
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy import select

from app.capability.schemas import Capability
from app.capability.service import poll_task, submit_task
from app.db import SessionLocal
from app.ids import new_id
from app.models import Asset, GenTask, TaskStatus

log = logging.getLogger(__name__)

TERMINAL = {TaskStatus.succeeded, TaskStatus.failed, TaskStatus.cancelled}


@dataclass
class Job:
    title: str
    capability: Capability
    payload: dict[str, Any] | Callable[[Any], dict[str, Any] | None]
    on_done: Callable[[Any, Asset], None]
    purpose: str = "preset_asset"
    priority: int = 0
    group: str = ""
    id: str = field(default_factory=lambda: new_id("job"))
    status: str = "queued"           # queued / running / done / failed / skipped
    error: str | None = None
    result_url: str | None = None
    task_id: str | None = None
    created: float = field(default_factory=time.time)


_QUEUE: list[Job] = []
#: 正在跑的（一个工作线程，所以最多一个）。别省：出队之后、进 _DONE 之前的任务要能查到 ——
#: 漏了它，前端轮询正好碰上「正在出图」就拿到 404，以为服务重启过
_RUNNING: list[Job] = []
_DONE: list[Job] = []
_LOCK = threading.Condition()
_WORKER: threading.Thread | None = None


def enqueue(job: Job) -> Job:
    global _WORKER
    with _LOCK:
        _QUEUE.append(job)
        _QUEUE.sort(key=lambda j: (-j.priority, j.created))
        _LOCK.notify_all()
        if _WORKER is None or not _WORKER.is_alive():
            _WORKER = threading.Thread(target=_work, daemon=True, name="preset-jobs")
            _WORKER.start()
    return job


def get(job_id: str) -> Job | None:
    with _LOCK:
        return next((j for j in _RUNNING + _QUEUE + _DONE if j.id == job_id), None)


def snapshot(group: str | None = None) -> list[dict[str, Any]]:
    with _LOCK:
        rows = _RUNNING + _QUEUE + _DONE[-60:]
    return [{"id": j.id, "title": j.title, "status": j.status, "error": j.error, "url": j.result_url, "group": j.group}
            for j in rows if not group or j.group == group]


def pending(group: str) -> int:
    with _LOCK:
        return sum(1 for j in _QUEUE if j.group == group)


def _work() -> None:
    while True:
        with _LOCK:
            while not _QUEUE:
                _LOCK.wait(30)
            job = _QUEUE.pop(0)
            job.status = "running"
            _RUNNING.append(job)
        try:
            _run(job)
        except Exception as exc:          # noqa: BLE001 —— 一张失败不能拖垮整条队列
            log.exception("出图任务失败：%s", job.title)
            job.status, job.error = "failed", str(exc)[:300]
        with _LOCK:
            if job in _RUNNING:
                _RUNNING.remove(job)
            _DONE.append(job)
            del _DONE[:-200]


def _run(job: Job) -> None:
    db = SessionLocal()
    try:
        payload = job.payload(db) if callable(job.payload) else job.payload
        if payload is None:
            job.status = "skipped"
            return
        task = submit_task(db, job.capability, payload, purpose=job.purpose, ref_kind="preset_job", ref_id=job.id, force=True)
        db.commit()
        job.task_id = task.id
        deadline = time.time() + 15 * 60
        while task.status not in TERMINAL and time.time() < deadline:
            time.sleep(3)
            task = poll_task(db, db.get(GenTask, task.id))
            db.commit()
        if task.status != TaskStatus.succeeded:
            err = task.error_json or {}
            job.status, job.error = "failed", str(err.get("message") or task.status.value)[:300]
            return
        asset = db.execute(select(Asset).where(Asset.gen_task_id == task.id)).scalars().first()
        if asset is None:
            job.status, job.error = "failed", "任务成功但没有产物"
            return
        job.on_done(db, asset)
        db.commit()
        job.status, job.result_url = "done", asset.url
    finally:
        db.close()
