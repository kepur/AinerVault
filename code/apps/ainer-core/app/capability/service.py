"""GenTask 生命周期：提交 → 回调/轮询 → 落库 → 重试。

gen_tasks 表本身就是任务状态源；回调直接改表，不需要额外的编排层。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.capability.client import CapabilityClient, canonical_idempotency_key
from app.capability.errors import (
    MAX_ATTEMPTS, RETRY_BACKOFF_SEC, CapabilityError, CapErrorCode,
)
from app.capability.router import ResolvedRoute, resolve_one, resolve_routes
from app.capability.schemas import Capability, Task, TaskOptions, TaskState
from app.config import settings
from app.ids import new_id
from app.models import Asset, AssetKind, AssetSource, GenTask, TaskStatus, utcnow

log = logging.getLogger(__name__)

#: 契约 TaskState → 本地 TaskStatus
_STATE_MAP: dict[TaskState, TaskStatus] = {
    TaskState.queued: TaskStatus.submitted,
    TaskState.running: TaskStatus.running,
    TaskState.succeeded: TaskStatus.succeeded,
    TaskState.failed: TaskStatus.failed,
    TaskState.cancelled: TaskStatus.cancelled,
}

#: 结果里的媒体字段 → 资产类型
_OUTPUT_ASSET_FIELDS: tuple[tuple[str, AssetKind, bool], ...] = (
    ("images", AssetKind.image, True),
    ("audio", AssetKind.audio, False),
    ("video", AssetKind.video, False),
    ("last_frame", AssetKind.image, False),
)


class CostGate(Exception):
    """预估成本超过阈值，需要前端二次确认。"""

    def __init__(self, estimated: float, count: int) -> None:
        self.estimated = estimated
        self.count = count
        super().__init__(f"预估 {count} 次调用共 ${estimated:.4f}，需确认")


def estimate_cost(db: Session, capability: Capability | str, purpose: str, count: int) -> float | None:
    routes = resolve_routes(db, capability, purpose)
    if not routes:
        return None
    unit = routes[0].unit_cost()
    return None if unit is None else round(unit * count, 6)


def submit_task(
    db: Session,
    capability: Capability | str,
    payload: dict[str, Any],
    *,
    purpose: str = "*",
    ref_kind: str | None = None,
    ref_id: str | None = None,
    novel_id: str | None = None,
    chapter_id: str | None = None,
    sync: bool = False,
    route: ResolvedRoute | None = None,
    max_cost: float | None = None,
) -> GenTask:
    """提交一次能力调用并落 gen_tasks。

    同 idempotency_key 命中已有记录时直接返回，不重复提交、不重复计费。
    """
    cap = Capability(capability) if isinstance(capability, str) else capability
    route = route or resolve_one(db, cap, purpose)

    merged = {**route.default_params, **payload}
    idem = canonical_idempotency_key(cap.value, merged)

    existing = db.execute(
        select(GenTask).where(GenTask.idempotency_key == idem)
    ).scalars().first()
    if existing is not None and existing.status not in {TaskStatus.failed, TaskStatus.cancelled}:
        return existing

    task = existing or GenTask(id=new_id("gt"), idempotency_key=idem)
    task.capability = cap.value
    task.request_json = merged
    task.endpoint_id = route.endpoint.id
    task.model = route.model
    task.status = TaskStatus.queued
    task.attempt = (task.attempt or 0) + 1
    task.error_json = None
    task.ref_kind = ref_kind
    task.ref_id = ref_id
    task.novel_id = novel_id
    task.chapter_id = chapter_id
    task.estimated_ms = route.estimated_ms()
    if existing is None:
        db.add(task)
    db.flush()

    options = TaskOptions(
        callback_url=f"{settings.public_base_url}/api/v2/gen-tasks/callback",
        callback_secret=settings.callback_secret,
        max_cost=max_cost,
        trace_id=task.id,
    )

    with CapabilityClient.from_route(route) as client:
        try:
            if sync:
                result = client.invoke(
                    cap, merged, model=route.model, options=options, idempotency_key=idem
                )
                apply_task_result(db, task, result)
                return task

            accepted = client.submit(
                cap, merged, model=route.model, options=options, idempotency_key=idem
            )
        except CapabilityError as exc:
            _mark_failed(task, exc)
            db.flush()
            return task

    task.provider_task_id = accepted.task_id
    task.status = _STATE_MAP.get(accepted.status, TaskStatus.submitted)
    task.submitted_at = utcnow()
    if accepted.estimated_ms:
        task.estimated_ms = accepted.estimated_ms
    task.poll_after = _next_poll_at(task)
    db.flush()
    return task


def _next_poll_at(task: GenTask) -> datetime:
    """轮询兜底时刻：submitted_at + estimated_ms × factor，不低于下限。"""
    est_sec = (task.estimated_ms or 1000) / 1000 * settings.poll_fallback_factor
    return utcnow() + timedelta(seconds=max(est_sec, settings.poll_fallback_min_sec))


def _mark_failed(task: GenTask, exc: CapabilityError) -> None:
    task.status = TaskStatus.failed
    task.error_json = exc.to_json()
    task.finished_at = utcnow()
    task.poll_after = None


def apply_task_result(db: Session, task: GenTask, result: Task) -> GenTask:
    """把中间层返回的终态写回本地，并把产物转成 assets。

    回调与轮询共用此函数 —— 按 task_id 天然幂等，重复送达不会重复建资产。
    """
    task.status = _STATE_MAP.get(result.status, TaskStatus.running)
    task.provider = result.provider or task.provider
    task.model = result.model or task.model
    if result.usage:
        task.usage_json = result.usage.model_dump(mode="json")
    if result.output is not None:
        task.result_json = result.output
        warnings = result.warnings
        if warnings:
            task.warnings_json = warnings
    if result.error:
        task.error_json = result.error.model_dump(mode="json")

    if result.is_terminal:
        task.finished_at = utcnow()
        task.poll_after = None
    else:
        task.poll_after = _next_poll_at(task)

    if task.status == TaskStatus.succeeded:
        _materialize_assets(db, task)

    db.flush()
    return task


def _materialize_assets(db: Session, task: GenTask) -> list[Asset]:
    """把 output 里的媒体登记为 assets。按 gen_task_id + url 去重。"""
    output = task.result_json or {}
    existing_urls = {
        a.url
        for a in db.execute(
            select(Asset).where(Asset.gen_task_id == task.id)
        ).scalars()
    }
    created: list[Asset] = []
    cost = (task.usage_json or {}).get("cost")

    for field, kind, is_list in _OUTPUT_ASSET_FIELDS:
        raw = output.get(field)
        if not raw:
            continue
        items = raw if is_list else [raw]
        for item in items:
            if not isinstance(item, dict) or not item.get("url"):
                continue
            if item["url"] in existing_urls:
                continue
            asset = Asset(
                id=new_id("as"),
                kind=kind,
                url=item["url"],
                sha256=item.get("sha256"),
                mime=item.get("mime"),
                bytes=item.get("bytes"),
                meta_json=item.get("meta") or {},
                source=AssetSource.generated,
                gen_task_id=task.id,
                novel_id=task.novel_id,
                cost=cost if not created else None,   # 成本只记在首个产物上，避免重复统计
            )
            db.add(asset)
            created.append(asset)
            existing_urls.add(item["url"])

    db.flush()
    return created


def poll_task(db: Session, task: GenTask) -> GenTask:
    """主动查询一次中间层。回调迟到或丢失时的兜底。"""
    if task.status in {TaskStatus.succeeded, TaskStatus.failed, TaskStatus.cancelled}:
        return task
    if not task.provider_task_id or not task.endpoint_id:
        return task

    from app.models import CapabilityEndpoint

    ep = db.get(CapabilityEndpoint, task.endpoint_id)
    if ep is None:
        return task

    with CapabilityClient(ep.base_url, auth=ep.auth_json or {}, timeout_sec=ep.timeout_sec) as c:
        try:
            result = c.get_task(task.provider_task_id)
        except CapabilityError as exc:
            if not exc.retryable:
                _mark_failed(task, exc)
                db.flush()
            else:
                task.poll_after = _next_poll_at(task)
                db.flush()
            return task
    return apply_task_result(db, task, result)


def due_for_poll(db: Session, limit: int = 50) -> list[GenTask]:
    now = datetime.now(timezone.utc)
    return list(
        db.execute(
            select(GenTask)
            .where(
                GenTask.status.in_([TaskStatus.submitted, TaskStatus.running]),
                GenTask.poll_after.is_not(None),
                GenTask.poll_after <= now,
            )
            .order_by(GenTask.poll_after.asc())
            .limit(limit)
        ).scalars()
    )


def retry_task(db: Session, task: GenTask) -> GenTask:
    """重试一个失败任务。不可重试的错误直接拒绝，避免无谓烧钱。"""
    if task.status != TaskStatus.failed:
        raise ValueError(f"任务当前为 {task.status.value}，无需重试")
    err = task.error_json or {}
    if err.get("retryable") is False:
        raise ValueError(
            f"错误 {err.get('code')} 不可重试：{err.get('message')}。请先修正输入或配置。"
        )
    if (task.attempt or 0) >= MAX_ATTEMPTS:
        raise ValueError(f"已重试 {task.attempt} 次（上限 {MAX_ATTEMPTS}）")

    cap = Capability(task.capability)
    return submit_task(
        db, cap, dict(task.request_json or {}),
        ref_kind=task.ref_kind, ref_id=task.ref_id,
        novel_id=task.novel_id, chapter_id=task.chapter_id,
    )


def backoff_for(attempt: int) -> int:
    idx = max(0, min(attempt - 1, len(RETRY_BACKOFF_SEC) - 1))
    return RETRY_BACKOFF_SEC[idx]
