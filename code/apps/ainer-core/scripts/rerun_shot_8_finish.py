"""补第 8 镜：改掉服化单空洞词，再按绑定 → 首帧 → 尾帧 → 视频走完。"""
from __future__ import annotations

import time

from sqlalchemy import select

from app.capability.service import poll_task
from app.db import SessionLocal
from app.models import (
    CrewSheet, FrameSpec, GenTask, Shot, ShotPlan, TaskStatus,
    WorldProfile, WorldTransform,
)
from app.pipelines import crew_sheets as cs
from app.pipelines import cut
from app.pipelines import frame_compose
from app.worldview.crew import CREW_BY_ROLE

PLAN_ID = "sp_01M20G8W1RN8BZ7FVE6FQHZ0P6"
SHOT_ID = "sh_01M20GB9SGV09GZDNYA4EHKSYH"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def poll_open(db) -> int:
    settled = 0
    open_st = {TaskStatus.queued, TaskStatus.submitted, TaskStatus.running}
    tasks = list(db.execute(select(GenTask).where(GenTask.status.in_(open_st))).scalars())
    for t in tasks:
        before = t.status
        try:
            poll_task(db, t)
        except Exception as exc:  # noqa: BLE001
            log(f"  poll {t.id} {exc}")
            continue
        log(f"  poll {t.id} {before.value}->{t.status.value} cap={t.capability}")
        if t.status != before and t.status in {TaskStatus.succeeded, TaskStatus.failed}:
            settled += 1
    db.commit()
    return settled


def main() -> int:
    db = SessionLocal()
    plan = db.get(ShotPlan, PLAN_ID)
    shot = db.get(Shot, SHOT_ID)
    ids = [shot.id]
    t = db.get(WorldTransform, plan.transform_id)
    profile = db.get(WorldProfile, t.target_profile_id)
    spec = CREW_BY_ROLE["costume_makeup"]

    log("改第 8 镜服化单：把「自然的」换成可验收描述")
    row = db.execute(select(CrewSheet).where(
        CrewSheet.shot_id == SHOT_ID, CrewSheet.role == "costume_makeup",
    )).scalars().first()
    data = dict(row.payload_json or {})
    for key, val in list(data.items()):
        if isinstance(val, str) and "自然的" in val:
            data[key] = val.replace("自然的", "未经漂染的")
    missing, rejected = cs._check(spec, data)
    row.payload_json = data
    row.prompt = cs._compose(spec, data)
    row.prompt_en = cs._compose_en(spec, data)
    row.missing_json = missing or None
    row.rejected_json = rejected or None
    row.edited_by_human = True
    db.commit()
    log(f"  missing={missing} rejected={rejected} prompt_en={bool(row.prompt_en)}")
    if missing or rejected:
        log("  服化单仍未过验收，停")
        return 1

    log("重新绑定")
    r = frame_compose.bind_and_compose(db, plan, t, shot_ids=ids)
    log(f"  {r.as_dict()}")
    db.commit()

    log("出首帧")
    r = frame_compose.generate_first_frames(
        db, plan, shot_ids=ids, regenerate=True, confirm_cost=True)
    log(f"  {r.as_dict()}")
    db.commit()
    for i in range(40):
        n = poll_open(db)
        log(f"  first poll {i+1} settled={n}")
        pending = [f for f in db.execute(select(FrameSpec).where(
            FrameSpec.shot_id.in_(ids), FrameSpec.role == "first",
        )).scalars() if f.status.value == "generating"]
        if not pending:
            break
        time.sleep(15)
    log(f"  {frame_compose.sync_frame_assets(db, plan)}")
    db.commit()

    log("出尾帧")
    r = frame_compose.generate_last_frames(
        db, plan, shot_ids=ids, regenerate=True, confirm_cost=True)
    log(f"  {r.as_dict()}")
    db.commit()
    for i in range(40):
        n = poll_open(db)
        log(f"  last poll {i+1} settled={n}")
        pending = [f for f in db.execute(select(FrameSpec).where(
            FrameSpec.shot_id.in_(ids), FrameSpec.role == "last",
        )).scalars() if f.status.value == "generating"]
        if not pending:
            break
        time.sleep(15)
    log(f"  {frame_compose.sync_frame_assets(db, plan)}")
    db.commit()

    log("出视频")
    r = cut.generate_videos(db, plan, limit=1, regenerate=True, shot_ids=ids)
    log(f"  {r}")
    db.commit()
    for i in range(60):
        n = poll_open(db)
        log(f"  video poll {i+1} settled={n}")
        db.expire_all()
        s = db.get(Shot, SHOT_ID)
        open_v = list(db.execute(select(GenTask).where(
            GenTask.ref_kind == "shot", GenTask.ref_id == SHOT_ID,
            GenTask.status.in_([TaskStatus.queued, TaskStatus.submitted, TaskStatus.running]),
        )).scalars())
        if s.video_asset_id and not open_v:
            break
        if not open_v:
            break
        time.sleep(20)
    log(f"  {frame_compose.sync_frame_assets(db, plan)}")
    db.commit()

    db.expire_all()
    s = db.get(Shot, SHOT_ID)
    fs = list(db.execute(select(FrameSpec).where(FrameSpec.shot_id == s.id)).scalars())
    log("结果")
    log(f"  镜8 frames={[(f.role.value, f.status.value, bool(f.asset_id)) for f in fs]} video={s.video_asset_id}")
    return 0 if s.video_asset_id else 2


if __name__ == "__main__":
    raise SystemExit(main())
