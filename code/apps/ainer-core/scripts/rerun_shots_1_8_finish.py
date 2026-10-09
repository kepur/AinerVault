"""补齐第 1–8 镜被挡下的制作单、换新素材键、等帧落地后再出视频。"""
from __future__ import annotations

import time

from sqlalchemy import select

from app.capability.service import poll_task
from app.db import SessionLocal
from app.models import FrameSpec, GenTask, Shot, ShotPlan, TaskStatus, WorldProfile, WorldTransform
from app.pipelines import crew_sheets as cs
from app.pipelines import cut
from app.pipelines import frame_compose

PLAN_ID = "sp_01M20G8W1RN8BZ7FVE6FQHZ0P6"
KEY_MAP = {
    "scene_corridor_90s": "location.school_corridor_1f",
    "cost_uniform_male": "costume.student_uniform_shoei",
}


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
    shots = list(db.execute(
        select(Shot).where(Shot.shot_plan_id == plan.id, Shot.order_no <= 8)
        .order_by(Shot.order_no)
    ).scalars())
    ids = [s.id for s in shots]
    t = db.get(WorldTransform, plan.transform_id)
    profile = db.get(WorldProfile, t.target_profile_id)

    log("换掉过期 asset_keys")
    for f in db.execute(select(FrameSpec).where(FrameSpec.shot_id.in_(ids))).scalars():
        params = dict(f.params_json or {})
        keys = []
        for k in params.get("asset_keys") or []:
            mapped = KEY_MAP.get(k)
            if mapped:
                keys.append(mapped)
            elif k.startswith("location.") or k.startswith("costume.") or k.startswith("prop."):
                keys.append(k)
        keys = list(dict.fromkeys(keys)) or ["location.school_corridor_1f"]
        params["asset_keys"] = keys
        f.params_json = params
    db.commit()

    log("重出被拒的制作单（最多 3 轮）")
    for attempt in range(1, 4):
        r = cs.generate_sheets(
            db, plan, profile,
            roles=["production_design", "costume_makeup"],
            shot_ids=ids,
        )
        log(f"  第{attempt}轮 {r.as_dict()}")
        db.commit()
        bad = [x for x in r.incomplete if x["shot"] in {3, 4, 6, 8}]
        if not bad:
            break

    log("重出偏薄的运动单 2/3/7")
    thin_ids = [s.id for s in shots if s.order_no in {2, 3, 7}]
    log(f"  {cs.generate_motion(db, plan, shot_ids=thin_ids)}")
    db.commit()

    log("重新绑定")
    r = frame_compose.bind_and_compose(db, plan, t, shot_ids=ids)
    log(f"  {r.as_dict()}")
    db.commit()

    log("轮询进行中的帧/视频任务")
    for i in range(40):
        n = poll_open(db)
        log(f"  round {i+1} settled={n}")
        open_n = db.execute(select(GenTask).where(GenTask.status.in_(
            [TaskStatus.queued, TaskStatus.submitted, TaskStatus.running]
        ))).scalars().all()
        mine = [x for x in open_n if x.ref_id in set(ids) or (
            x.ref_kind == "frame_spec")]
        if not mine:
            break
        time.sleep(15)

    log("同步帧")
    log(f"  {frame_compose.sync_frame_assets(db, plan)}")
    db.commit()

    log("补出未完成的首帧")
    r = frame_compose.generate_first_frames(
        db, plan, shot_ids=ids, regenerate=True, confirm_cost=True)
    log(f"  {r.as_dict()}")
    db.commit()
    for i in range(40):
        n = poll_open(db)
        log(f"  first poll {i+1} settled={n}")
        pending = [f for f in db.execute(select(FrameSpec).where(
            FrameSpec.shot_id.in_(ids), FrameSpec.role == "first"
        )).scalars() if f.status.value == "generating"]
        if not pending:
            break
        time.sleep(15)
    log(f"  {frame_compose.sync_frame_assets(db, plan)}")
    db.commit()

    log("补出尾帧")
    r = frame_compose.generate_last_frames(
        db, plan, shot_ids=ids, regenerate=True, confirm_cost=True)
    log(f"  {r.as_dict()}")
    db.commit()
    for i in range(40):
        n = poll_open(db)
        log(f"  last poll {i+1} settled={n}")
        pending = [f for f in db.execute(select(FrameSpec).where(
            FrameSpec.shot_id.in_(ids), FrameSpec.role == "last"
        )).scalars() if f.status.value == "generating"]
        if not pending:
            break
        time.sleep(15)
    log(f"  {frame_compose.sync_frame_assets(db, plan)}")
    db.commit()

    log("出视频（等新帧）")
    r = cut.generate_videos(db, plan, limit=8, regenerate=True, shot_ids=ids)
    log(f"  {r}")
    db.commit()
    for i in range(60):
        n = poll_open(db)
        log(f"  video poll {i+1} settled={n}")
        pending = [s for s in db.execute(select(Shot).where(Shot.id.in_(ids))).scalars()
                   if not s.video_asset_id]
        open_v = [x for x in db.execute(select(GenTask).where(
            GenTask.ref_kind == "shot", GenTask.ref_id.in_(ids),
            GenTask.status.in_([TaskStatus.queued, TaskStatus.submitted, TaskStatus.running]),
        )).scalars()]
        if not open_v:
            break
        time.sleep(20)
    log(f"  {frame_compose.sync_frame_assets(db, plan)}")
    db.commit()

    log("结果")
    for s in db.execute(select(Shot).where(Shot.id.in_(ids)).order_by(Shot.order_no)).scalars():
        fs = list(db.execute(select(FrameSpec).where(FrameSpec.shot_id == s.id)).scalars())
        log(f"  镜{s.order_no} frames={[ (f.role.value, f.status.value, bool(f.asset_id)) for f in fs ]} video={bool(s.video_asset_id)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
