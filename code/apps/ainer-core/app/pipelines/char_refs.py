"""小说角色一键重出定妆照：正面全身 → 其余视角（左前 3/4、头肩、侧面、背面）→ 拼设定图。

identity.generate_character_references 一次只推进一个依赖层（侧面要从正面派生，不能同一批），
以前要在后台按三次、每次等图落地。这里开一个后台线程把三步串起来，每步等任务结束再走下一步。

- 正面 regenerate=True：坏图（多出一双手、厨房背景）就是要换掉它；
- 其余视角不 regenerate：正面换了，它们的 source_asset_id 对不上，generate_character_references 自己判成过期重出；
- 只在本机出图（submit 时 max_cost=0）；
- 状态只放内存（core 重启就没了，重新点一次即可，已经落地的图不会白出）。
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

from sqlalchemy import select

from app.db import SessionLocal
from app.models import AssetEpoch, GenTask, TaskStatus, WorldEntity, WorldProfile

log = logging.getLogger("ainer-core")

#: 一张图的上限（本机 FLUX i2i 一张 25–50 秒，排在 LTX 后面会更久）
TASK_TIMEOUT_S = 15 * 60
POLL_EVERY_S = 5.0
DERIVED_VIEWS = ("three_quarter_left", "bust", "profile_left", "back")

_LOCK = threading.Lock()
_STATE: dict[str, dict[str, Any]] = {}


def status(entity_id: str) -> dict[str, Any] | None:
    with _LOCK:
        st = _STATE.get(entity_id)
        return dict(st) if st else None


def busy(entity_id: str) -> bool:
    st = status(entity_id)
    return bool(st and st.get("state") == "running")


def start(entity_id: str) -> dict[str, Any]:
    """开始（已经在跑就返回当前状态）。"""
    with _LOCK:
        st = _STATE.get(entity_id)
        if st and st.get("state") == "running":
            return dict(st)
        st = {"state": "running", "step": "front", "started_at": time.time(), "error": None, "notes": []}
        _STATE[entity_id] = st
    threading.Thread(target=_run, args=(entity_id,), name=f"char-refs-{entity_id}", daemon=True).start()
    return dict(st)


def _set(entity_id: str, **kw: Any) -> None:
    with _LOCK:
        _STATE.setdefault(entity_id, {}).update(kw)


def _note(entity_id: str, text: str) -> None:
    with _LOCK:
        _STATE.setdefault(entity_id, {}).setdefault("notes", []).append(text)


def _wait(db, task_ids: list[str]) -> list[str]:
    """等一批任务结束；返回失败的说明。"""
    from app.capability.service import poll_task

    deadline = time.time() + TASK_TIMEOUT_S
    left = set(task_ids)
    errors: list[str] = []
    while left and time.time() < deadline:
        for tid in list(left):
            db.expire_all()
            task = db.get(GenTask, tid)
            if task is None:
                left.discard(tid)
                continue
            if task.status not in (TaskStatus.succeeded, TaskStatus.failed, TaskStatus.cancelled):
                try:
                    task = poll_task(db, task)
                    db.commit()
                except Exception:                     # noqa: BLE001 —— 网关一时连不上：下一轮再问
                    db.rollback()
            if task.status in (TaskStatus.succeeded, TaskStatus.failed, TaskStatus.cancelled):
                left.discard(tid)
                if task.status != TaskStatus.succeeded:
                    msg = (task.error_json or {}).get("message") if isinstance(task.error_json, dict) else None
                    errors.append(str(msg or task.status.value)[:200])
        if left:
            time.sleep(POLL_EVERY_S)
    if left:
        errors.append(f"{len(left)} 张图超过 {TASK_TIMEOUT_S // 60} 分钟没出完")
    return errors


def _profiles(db, entity_id: str) -> list[WorldProfile]:
    """有脸锚的圈层才重出：别的圈层（另一套世界观映射）从没出过图，跟着跑只会报一串「先生成身份锚」。"""
    eps = list(db.execute(select(AssetEpoch).where(AssetEpoch.subject_key == entity_id)).scalars())
    anchored = {e.world_profile_id for e in eps if e.identity_ref_asset_id}
    pids = anchored or {e.world_profile_id for e in eps}
    return [p for p in (db.get(WorldProfile, pid) for pid in pids) if p is not None]


def _run(entity_id: str) -> None:
    from app.pipelines import identity

    db = SessionLocal()
    try:
        ent = db.get(WorldEntity, entity_id)
        if ent is None:
            raise RuntimeError("找不到这个角色")
        profiles = _profiles(db, entity_id)
        if not profiles:
            raise RuntimeError("这个角色还没有人物时期：先在后台「人物时期」里推导")

        for step, views, regen in (("front", ("front",), True), ("views", DERIVED_VIEWS, False)):
            _set(entity_id, step=step)
            tids: list[str] = []
            for prof in profiles:
                res = identity.generate_character_references(
                    db, ent.novel_id, prof, entity_ids=[entity_id], views=list(views),
                    regenerate=regen, confirm_cost=False)
                db.commit()
                if res.requires_confirm:
                    raise RuntimeError("出图要花钱（没有本机图像端点可用），没有提交")
                for b in res.blocked:
                    _note(entity_id, b)
                tids += [t["gen_task_id"] for t in res.tasks]
            if step == "front" and not tids:
                raise RuntimeError("；".join(status(entity_id).get("notes") or []) or "没有可重出的正面图")
            errors = _wait(db, tids)
            if errors and step == "front":
                raise RuntimeError("正面全身没出成：" + "；".join(errors))
            for e in errors:
                _note(entity_id, e)

        _set(entity_id, step="sheet")
        made = 0
        for prof in profiles:
            for epoch in identity.epochs_of(db, entity_id, prof.id):
                if identity.compose_reference_sheet(db, epoch):
                    made += 1
        db.commit()
        _set(entity_id, state="done", step="done", sheets=made, finished_at=time.time())
    except Exception as exc:                          # noqa: BLE001 —— 后台线程：错误放进状态给前端看
        db.rollback()
        log.warning("char_refs %s failed: %s", entity_id, exc)
        _set(entity_id, state="failed", error=str(exc)[:300], finished_at=time.time())
    finally:
        db.close()
