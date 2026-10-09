"""按最新生产链重跑第一章第 1–8 镜：调度 → 八工种 → 运动 → 绑定 → 首帧 → 尾帧 → 视频。"""
from __future__ import annotations

import sys
import time
import traceback

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Shot, ShotPlan, WorldProfile, WorldTransform
from app.pipelines import crew_sheets as cs
from app.pipelines import frame_compose
from app.pipelines import performance as perf_pipe
from app.pipelines import cut
from app.pipelines.base import PipelineError

PLAN_ID = "sp_01M20G8W1RN8BZ7FVE6FQHZ0P6"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    db = SessionLocal()
    plan = db.get(ShotPlan, PLAN_ID)
    if plan is None:
        log("分镜计划不存在")
        return 1
    shots = list(db.execute(
        select(Shot).where(Shot.shot_plan_id == plan.id, Shot.order_no <= 8)
        .order_by(Shot.order_no)
    ).scalars())
    ids = [s.id for s in shots]
    log(f"目标 {len(ids)} 镜：{[s.order_no for s in shots]}")
    t = db.get(WorldTransform, plan.transform_id)
    profile = db.get(WorldProfile, t.target_profile_id) if t else None
    if profile is None:
        log("没有世界观档案")
        return 1

    try:
        log("1/7 调度与表演")
        r = perf_pipe.extract_performance(db, plan, batch_size=6, shot_ids=ids)
        log(f"  {r.as_dict() if hasattr(r, 'as_dict') else r}")

        log("2/7 八工种制作单")
        r = cs.generate_sheets(db, plan, profile, shot_ids=ids)
        log(f"  {r.as_dict() if hasattr(r, 'as_dict') else r}")

        log("3/7 运动与物理连续")
        r = cs.generate_motion(db, plan, shot_ids=ids)
        log(f"  {r}")

        log("4/7 绑定素材并拼 prompt")
        r = frame_compose.bind_and_compose(db, plan, t, shot_ids=ids)
        log(f"  {r.as_dict() if hasattr(r, 'as_dict') else r}")

        log("5/7 首帧（regenerate）")
        r = frame_compose.generate_first_frames(
            db, plan, shot_ids=ids, regenerate=True, confirm_cost=True)
        log(f"  {r.as_dict() if hasattr(r, 'as_dict') else r}")
        log(f"  sync {frame_compose.sync_frame_assets(db, plan)}")

        log("6/7 尾帧（regenerate）")
        r = frame_compose.generate_last_frames(
            db, plan, shot_ids=ids, regenerate=True, confirm_cost=True)
        log(f"  {r.as_dict() if hasattr(r, 'as_dict') else r}")
        log(f"  sync {frame_compose.sync_frame_assets(db, plan)}")

        log("7/7 动态镜头（本机 LTXV）")
        r = cut.generate_videos(
            db, plan, limit=8, regenerate=True, shot_ids=ids)
        log(f"  {r}")
        db.commit()
    except PipelineError as exc:
        db.rollback()
        log(f"PIPELINE {exc}")
        return 2
    except Exception:
        db.rollback()
        traceback.print_exc()
        return 3

    shots = list(db.execute(
        select(Shot).where(Shot.id.in_(ids)).order_by(Shot.order_no)
    ).scalars())
    from app.models import FrameRole, FrameSpec
    log("结果：")
    for s in shots:
        fs = {f.role: f for f in db.execute(
            select(FrameSpec).where(FrameSpec.shot_id == s.id)).scalars()}
        first = fs.get(FrameRole.first)
        last = fs.get(FrameRole.last)
        log(f"  镜{s.order_no} first={'ok' if first and first.asset_id else '—'} "
            f"last={'ok' if last and last.asset_id else '—'} "
            f"video={'ok' if s.video_asset_id else '—'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
