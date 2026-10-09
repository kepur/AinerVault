"""Create an isolated, bounded production plan without invoking any model."""
from copy import deepcopy
from sqlalchemy import select, func
from app.ids import new_id
from app.models import (ShotPlan, Shot, FrameSpec, AudioSpec, ShotMotion,
                        CrewSheet, ShotPerformance, ShotAssetBinding, SpecStatus)


def select_sample(shots, target_ms=30_000, start_order=1):
    selected, total = [], 0
    for shot in shots:
        if shot.order_no < start_order:
            continue
        duration = shot.duration_ms or 0
        if duration <= 0:
            raise ValueError(f"镜 {shot.order_no} 缺有效时长")
        if total + duration > target_ms:
            break  # Keep dialogue and shots intact; never skip ahead.
        selected.append(shot)
        total += duration
    if not selected:
        raise ValueError("首个镜头超过试片预算，请调整起始镜或先拆分长镜头")
    return selected, total


def _clone(row, **overrides):
    values = {c.key: deepcopy(getattr(row, c.key)) for c in row.__table__.columns
              if c.key not in {"id", "created_at", "updated_at"}}
    values.update(overrides)
    return type(row)(id=new_id("sm"), **values)


def create_sample(db, source, target_ms=30_000, start_order=1):
    # Serialize version allocation for this document.
    from app.models import ScriptDoc, DocStatus
    db.execute(select(ScriptDoc).where(ScriptDoc.id == source.script_doc_id).with_for_update()).scalar_one()
    shots, duration = select_sample(list(db.execute(select(Shot).where(
        Shot.shot_plan_id == source.id).order_by(Shot.order_no)).scalars()), target_ms, start_order)
    version = db.scalar(select(func.max(ShotPlan.version)).where(
        ShotPlan.script_doc_id == source.script_doc_id)) or 0
    plan = _clone(source, version=version + 1, config_json={
        **(source.config_json or {}), "sample": True, "source_plan_id": source.id,
        "target_duration_ms": target_ms, "sample_duration_ms": duration,
    }, stats_json={"shots": len(shots), "duration_ms": duration})
    # **试片不抢 active。**
    #
    # 从前这里把现有 active 方案全部归档、让试片顶上去。后果：给一章做了个
    # 30 秒试片，215 镜的完整方案就被降级，后台从此显示「这一章 2 个分镜」，
    # 进度、渲染、交付也全都转去跟那 2 镜走 —— 而做试片的人只是想看一眼效果。
    # 实测坏蛋第一章就是这么变成 6.4 秒的。
    #
    # 试片存成 draft：它照样可以按 plan_id 出帧、出视频、渲染，
    # 只是不冒充这一章的正式方案。章节级视图找 active 时仍然找到完整方案。
    plan.status = DocStatus.draft
    db.add(plan); db.flush()
    for shot in shots:
        copied = _clone(shot, shot_plan_id=plan.id)
        db.add(copied); db.flush()
        for model in (FrameSpec, AudioSpec, ShotMotion, CrewSheet, ShotPerformance, ShotAssetBinding):
            for row in db.execute(select(model).where(model.shot_id == shot.id)).scalars():
                extra = {"shot_id": copied.id}
                if hasattr(row, "gen_task_id"):
                    extra["gen_task_id"] = None
                    if row.status == SpecStatus.generating:
                        extra["status"] = SpecStatus.ready if row.asset_id else SpecStatus.pending
                db.add(_clone(row, **extra))
    db.flush()
    return {"shot_plan_id": plan.id, "source_plan_id": source.id,
            "shots": len(shots), "duration_ms": duration, "target_ms": target_ms}
