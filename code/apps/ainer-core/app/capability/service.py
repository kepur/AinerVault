"""GenTask 生命周期：提交 → 回调/轮询 → 落库 → 重试。

gen_tasks 表本身就是任务状态源；回调直接改表，不需要额外的编排层。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.capability.client import CapabilityClient, canonical_idempotency_key
from app.capability.errors import (
    MAX_ATTEMPTS, RETRY_BACKOFF_SEC, CapabilityError, CapErrorCode,
)
from app.capability.router import ResolvedRoute, resolve_one, resolve_routes
from app.capability.schemas import (
    TERMINAL_STATES, Capability, Task, TaskOptions, TaskState,
)
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
    tier: str | None = None,
    max_cost: float | None = None,
    force: bool = False,
) -> GenTask:
    """提交一次能力调用并落 gen_tasks。

    同 idempotency_key 命中已有记录时直接返回，不重复提交、不重复计费。

    force=True 绕开这层复用 —— **这是「重新生成」唯一能真正生效的方式。**
    在此之前，各管线的 regenerate 只做到「不跳过已有产物的规格」，
    到了这里又被幂等命中挡回去：任务不重跑、产物不变、界面上却报「已提交 30 条」。
    人会以为改了参数没效果，实际上根本没调过模型。
    force 只应由人明确点「重新生成」时传入 —— 它绕开的正是防重复计费那一层。
    """
    cap = Capability(capability) if isinstance(capability, str) else capability
    route = route or resolve_one(db, cap, purpose, tier)

    merged = {**route.default_params, **payload}
    idem = canonical_idempotency_key(
        cap.value, merged, endpoint_id=route.endpoint.id, model=route.model
    )
    if force:
        # 键里掺一个随机段，让这次必然错开历史任务。
        # 不改 request_json —— 送给模型的内容必须和不 force 时完全一致，
        # 否则「重出一张」会变成「换个参数出一张」，两者不可比。
        idem = f"{idem}:force:{new_id('f')}"

    existing = db.execute(
        select(GenTask).where(GenTask.idempotency_key == idem)
    ).scalars().first()
    if existing is not None and existing.status not in {TaskStatus.failed, TaskStatus.cancelled}:
        # 幂等命中已完成的任务时，产物仍挂在当初那个引用对象上。
        # 重新编译分镜会造出新的 FrameSpec，若不在这里补挂，
        # 新帧永远等不到图 —— 任务不会再跑第二次，回调也不会重来。
        if existing.status == TaskStatus.succeeded and ref_id and (
            existing.ref_kind != ref_kind or existing.ref_id != ref_id
        ):
            done = list(db.execute(
                select(Asset).where(Asset.gen_task_id == existing.id)
            ).scalars())
            _attach_to_ref(db, existing, done, ref_kind=ref_kind, ref_id=ref_id)
            db.flush()
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
        try:
            with db.begin_nested():
                db.flush()
        except IntegrityError:
            # 幂等键唯一约束撞车：另一个请求在我们查完 existing 之后插了同一把键。
            # 后台连点两次、或前一次请求还在跑就重发，都会走到这里。
            # 这不是错误 —— 幂等的语义本就是「让后来者拿到同一个任务」。
            db.expunge(task)
            raced = db.execute(
                select(GenTask).where(GenTask.idempotency_key == idem)
            ).scalars().first()
            if raced is None:
                raise
            log.info("幂等键并发撞车，复用已有任务 %s", raced.id)
            return raced
    else:
        db.flush()

    options = TaskOptions(
        callback_url=f"{settings.public_base_url}/api/v2/gen-tasks/callback",
        callback_secret=settings.callback_secret,
        max_cost=max_cost,
        trace_id=task.id,
    )

    # 同步方言没有任务队列 —— 直连供应商时一次 HTTP 就是全部。
    # 不在这里改道的话，submit() 会当场抛「没有任务队列」，
    # 而调用方（出图、出音）根本不知道端点是哪种方言，也不该知道
    from app.capability.dialects import SYNC_ONLY_DIALECTS

    sync = sync or (route.endpoint.dialect or "") in SYNC_ONLY_DIALECTS

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
    task.submitted_at = utcnow()
    if accepted.estimated_ms:
        task.estimated_ms = accepted.estimated_ms

    if accepted.status in TERMINAL_STATES:
        # 中间层幂等命中已完成的任务时，只回 {task_id, status}，不带 output。
        # 直接照抄状态会得到「succeeded 但没有产物」的僵尸任务 ——
        # 必须再查一次拿完整结果。
        with CapabilityClient.from_route(route) as client:
            try:
                result = client.get_task(accepted.task_id)
                apply_task_result(db, task, result)
                return task
            except CapabilityError as exc:
                log.warning("终态任务回查失败 task=%s: %s", accepted.task_id, exc)

    task.status = _STATE_MAP.get(accepted.status, TaskStatus.submitted)
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
        created = _materialize_assets(db, task)
        _attach_to_ref(db, task, created)

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


def _attach_to_ref(
    db: Session, task: GenTask, assets: list[Asset],
    *, ref_kind: str | None = None, ref_id: str | None = None,
) -> None:
    """产物落地后自动挂回引用它的对象。

    回调是产物落地的自然时机 —— 让前端在 :generate 之后再手工调一次 :sync，
    既容易忘，也必然撞上回调还没到的时序窗口。
    """
    ref_kind = ref_kind or task.ref_kind
    ref_id = ref_id or task.ref_id
    if not assets or not ref_id:
        return
    try:
        if ref_kind == "asset_variant":
            from app.models import AssetVariant

            variant = db.get(AssetVariant, ref_id)
            if variant is not None:
                merged = list(dict.fromkeys(
                    [*(variant.ref_asset_ids or []), *(a.id for a in assets)]
                ))
                variant.ref_asset_ids = merged
        elif ref_kind == "frame_spec":
            from app.models import FrameSpec, SpecStatus

            frame = db.get(FrameSpec, ref_id)
            if frame is not None and _supersedes(db, frame, task):
                frame.asset_id = assets[0].id
                frame.status = SpecStatus.ready
        elif ref_kind == "audio_spec":
            from app.models import AudioSpec, SpecStatus

            spec = db.get(AudioSpec, ref_id)
            if spec is not None and _supersedes(db, spec, task):
                spec.asset_id = assets[0].id
                spec.status = SpecStatus.ready
                meta = assets[0].meta_json or {}
                if meta.get("duration_ms"):
                    spec.duration_ms = int(meta["duration_ms"])
                ts = (task.result_json or {}).get("timestamps")
                if ts:
                    spec.timestamps_json = ts
    except Exception:  # noqa: BLE001 - 回挂失败不应让回调整体失败
        log.exception("产物回挂失败 task=%s ref=%s/%s", task.id, ref_kind, ref_id)



def _supersedes(db: Session, spec: Any, task: GenTask) -> bool:
    """这个任务的产物是否应该覆盖规格上现有的那一份。

    原判据是「规格还没有产物」，于是重出（regenerate）永远无效：
    任务跑了、钱花了、新产物也落库了，规格却还指着旧的那一张 ——
    界面上看不出任何异常，只是重出没有生效。

    也不能改判「gen_task_id 等于本任务」：同步方言在 submit_task **内部**
    就完成回挂，而管线是在它返回**之后**才写 gen_task_id，那时比较必然不成立。

    所以按产物新旧判：新任务的产出覆盖旧的，迟到的旧回调不覆盖新的。
    这条规则对同步与异步两种方言都成立，不依赖调用顺序。
    """
    aid = getattr(spec, "asset_id", None)
    if not aid:
        return True
    current = db.get(Asset, aid)
    if current is None or not current.gen_task_id or current.gen_task_id == task.id:
        return True
    prev = db.get(GenTask, current.gen_task_id)
    if prev is None or prev.created_at is None or task.created_at is None:
        return True
    return prev.created_at <= task.created_at


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

    with CapabilityClient(
        ep.base_url, auth=ep.auth_json or {}, timeout_sec=ep.timeout_sec,
        dialect=ep.dialect or "capability",
    ) as c:
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
