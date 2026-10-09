"""画布「一键出片」工作流：一组镜头按顺序 补配音 → 出画面 → 挂回镜头。

一镜的流水（都是现成的环节，这里只负责排队、推进、记账）：
  1. 配音（audio=auto 时）：这一镜有台词还没配音 → 按角色库定的音色出 TTS（audio_compose.generate_audio），
     等它落库再回填真实时长。等太久就不等了，这一镜退回现场生成声音（记一条 note，不算失败）。
  2. 出画面，两种方案（options.method）：
     keyframe（默认，借鉴纳逗，见 pipelines/keyframe）：本章定妆照＋场景图 → 图像编辑模型画关键帧（挂到首帧）
       → 视频模型钉住关键帧出片（本机 LTX 2.5 / 云端万相；options.engine）。不搭景、不渲 Blender，最快。
     director（3D 白模控制，from_shot.render_shot）：LLM 搭 3D 白模、定站位和运镜 → Blender 预演/控制素材 →
       身份首帧 → LTX 2.5 按控制出片。站位、机位必须严格照预演走的镜头用。
       用户在 3D-BOX 里调过的场景（director_run.scene_id）默认沿用，不重新搭。
  3. 挂回这一镜（Shot.video_asset_id），分镜画布上同步看得到。

为什么一镜跑完再交下一镜：导演任务本来就在单线程队列里串行，一口气全交上去的话队列里先排满 Blender，
全部预演渲完才开始出第一条成片 —— 用户要等几个小时才看到第一镜。现在每 8 分钟左右出一条。

状态全在 studio_runs 表里（items_json 每镜一条），后台线程每几秒推进一步；core 重启后线程接着推进。
同一时刻只推进最早的那个工作流：本机一块 GPU，两个工作流交错跑只会互相拖慢。
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import AudioKind, AudioSpec, DirectorJob, GenTask, Shot, ShotPlan, StudioRun, TaskStatus
from app.models.base import utcnow

log = logging.getLogger(__name__)

TICK_S = 6
#: 配音最多等多久：本机 TTS 一句几秒，十五分钟还没落库多半是服务没起
AUDIO_WAIT_S = 15 * 60
#: 一镜导演出片最多等多久（预演约 1 分钟、身份首帧约 1 分钟、768×448 成片约 4–6 分钟；排队另算）
SHOT_TIMEOUT_S = 60 * 60
#: 交了导演任务后多久还查不到进度就算丢了
LOST_S = 120

#: 一张关键帧最多等多久（本机 FLUX 约 30 秒，网关前面可能压着 LTX 出片）
FRAME_TIMEOUT_S = 30 * 60
#: 关键帧方案的一条视频最多等多久
VIDEO_TIMEOUT_S = 60 * 60
#: 任务在跑时多久主动问一次网关（回调丢了、后台轮询关着也推得动）
POLL_EVERY_S = 15

ACTIVE = ("queued", "running")
PROFILES = ("fast", "hd")
PROFILE_SIZE = {"fast": (768, 448), "hd": (1024, 576)}
AUDIO_MODES = ("auto", "generate", "none")
METHODS = ("keyframe", "director")
ENGINES = ("local", "cloud")


# ── 纯函数（单测直接测）────────────────────────────────────────────────

def pick_items(shots: Iterable[tuple[str, int, bool]], wanted: Iterable[str] | None = None,
               only_missing: bool = True) -> list[dict[str, Any]]:
    """要跑哪几镜，按镜头次序。shots = (shot_id, order_no, 已有成片)；wanted 为空 = 全部。"""
    want = set(wanted or [])
    return [{"shot_id": sid, "order_no": no, "step": "audio", "status": "pending"}
            for sid, no, has_video in sorted(shots, key=lambda r: r[1])
            if (not want or sid in want) and not (only_missing and has_video)]


def director_verdict(st: Mapping[str, Any] | None, submitted_at: float, now: float) -> tuple[str, str | None]:
    """导演出片走到哪了 → (running | succeeded | failed, 失败原因)。st = from_shot.run_status 的结果。"""
    if st is None:
        return ("failed", "导演任务不见了（服务重启过？）") if now - submitted_at > LOST_S else ("running", None)
    if st.get("done"):
        return "succeeded", None
    if st.get("status") in ("failed", "cancelled"):
        step = {"previs": "预演", "identity": "身份首帧", "final": "成片", "chain": "挂回"}.get(st.get("step") or "", "")
        return "failed", (st.get("error") or f"{step}{'已取消' if st.get('status') == 'cancelled' else '失败'}")
    if now - submitted_at > SHOT_TIMEOUT_S:
        return "failed", "超时（一小时没出完）"
    return "running", None


def task_verdict(status: str | None, error: str | None, submitted_at: float, now: float,
                 timeout_s: float) -> tuple[str, str | None]:
    """关键帧 / 视频任务走到哪了 → (running | succeeded | failed, 失败原因)。status = GenTask.status。"""
    if status is None:
        return "failed", "任务不见了"
    if status == TaskStatus.succeeded.value:
        return "succeeded", None
    if status in (TaskStatus.failed.value, TaskStatus.cancelled.value):
        return "failed", error or ("已取消" if status == TaskStatus.cancelled.value else "失败")
    if now - submitted_at > timeout_s:
        return "failed", f"超时（{int(timeout_s // 60)} 分钟没出完）"
    return "running", None


def after_audio(options: Mapping[str, Any]) -> str:
    """配音之后走哪一步。"""
    return "director" if options.get("method") == "director" else "frame"


def summarize(items: list[Mapping[str, Any]]) -> dict[str, Any]:
    count = {k: sum(1 for i in items if i.get("status") == k) for k in ("pending", "running", "succeeded", "failed", "skipped")}
    cur = next((i for i in items if i.get("status") == "running"), None) or \
        next((i for i in items if i.get("status") == "pending"), None)
    return {"total": len(items), **count, "current": dict(cur) if cur else None}


def finished_status(items: list[Mapping[str, Any]]) -> str:
    return "failed" if any(i.get("status") == "failed" for i in items) else "succeeded"


# ── 推进 ────────────────────────────────────────────────────────────────

def _dialogue(db: Session, shot_id: str) -> list[AudioSpec]:
    return [a for a in db.execute(select(AudioSpec).where(AudioSpec.shot_id == shot_id)).scalars()
            if a.kind == AudioKind.dialogue]


def _audio_step(db: Session, run: StudioRun, plan: ShotPlan, item: dict[str, Any], now: float) -> bool:
    """配音这一步走完了没有（True = 可以进导演出片）。"""
    if (run.options_json or {}).get("audio", "auto") != "auto":
        return True
    specs = _dialogue(db, item["shot_id"])
    if not specs:
        return True
    from app.pipelines import audio_compose as ac

    if all(a.asset_id for a in specs):
        if item.get("audio_submitted"):
            try:
                ac.backfill_durations(db, plan)       # 镜头长度跟着真实配音走（时长权威链）
                db.commit()
            except Exception as exc:                  # noqa: BLE001 —— 回填失败不挡出片，片长按估算
                db.rollback()
                item["note"] = f"配音时长没回填上：{exc}"[:200]
        return True
    if not item.get("audio_submitted"):
        try:
            res = ac.generate_audio(db, plan, kinds=["dialogue"], only_shot_ids=[item["shot_id"]])
            db.commit()
        except Exception as exc:                      # noqa: BLE001
            db.rollback()
            item["note"] = f"配音没提交上，这一镜现场生成声音：{exc}"[:200]
            return True
        if not res.submitted:
            why = "；".join(res.blocked[:2]) or ("要确认费用" if res.requires_confirm else "没有可配的台词")
            item["note"] = f"配音没提交（{why}），这一镜现场生成声音"[:200]
            return True
        item["audio_submitted"] = now
        item["status"] = "running"
        return False
    if now - float(item["audio_submitted"]) > AUDIO_WAIT_S:
        item["note"] = "配音等了十五分钟还没好（TTS 服务没起？），这一镜现场生成声音"
        return True
    return False


def _task_step(db: Session, item: dict[str, Any], key: str, now: float, timeout_s: float) -> tuple[str, str | None]:
    """等一个能力任务（关键帧 / 视频）：在跑就隔一会儿主动问一次网关，回调丢了也推得动。"""
    from app.capability.service import poll_task

    task = db.get(GenTask, item[key])
    if task is not None and task.status.value not in ("succeeded", "failed", "cancelled") \
            and now - float(item.get("polled") or 0) > POLL_EVERY_S:
        item["polled"] = now
        try:
            task = poll_task(db, task)
            db.commit()
        except Exception:                             # noqa: BLE001 —— 网关暂时连不上：下一轮再问
            db.rollback()
    err = None
    if task is not None and task.error_json:
        err = str(task.error_json.get("message") or task.error_json)[:300]
    return task_verdict(task.status.value if task is not None else None, err, float(item["submitted"]), now, timeout_s)


def _keyframe_ready(db: Session, shot: Shot, engine: str) -> bool:
    """这一镜已经有本方案画的关键帧（同一个引擎）：重跑时不再画一遍。分镜流水线的旧首帧不算。"""
    from app.models import FrameRole, FrameSpec

    fs = db.execute(select(FrameSpec).where(FrameSpec.shot_id == shot.id, FrameSpec.role == FrameRole.first)
                    ).scalars().first()
    if fs is None or not fs.asset_id or not fs.gen_task_id:
        return False
    kf = (fs.params_json or {}).get("keyframe")
    task = db.get(GenTask, fs.gen_task_id)
    return isinstance(kf, dict) and kf.get("engine") == engine and task is not None and task.status == TaskStatus.succeeded


def _cancel_shot_jobs(db: Session, item: Mapping[str, Any]) -> None:
    """取消正在出的这一镜：导演任务停掉；关键帧 / 视频任务穿透到网关（本机 GPU 队列里的 LTX 不停就一直占着卡）。"""
    from app.capability.service import cancel_task
    from app.director import from_shot, jobs

    shot = db.get(Shot, item["shot_id"])
    st = from_shot.run_status(db, shot) if shot is not None and item.get("blender_job_id") else None
    for jid in (item.get("blender_job_id"), (st or {}).get("final_job_id")):
        job = db.get(DirectorJob, jid) if jid else None
        if job is not None and job.status in ACTIVE:
            jobs.cancel(db, job)
    for tid in [item.get("frame_task"), item.get("video_task"), *(item.get("frame_tasks") or [])]:
        task = db.get(GenTask, tid) if tid else None
        if task is not None:
            cancel_task(db, task)
    db.commit()


def _recent_video_task(db: Session, shot_id: str, since: float) -> GenTask | None:
    """提交视频时抛了异常，任务却可能已经交上去了（镜 6、7 实跑过：交完解析返回值时崩，片子照样挂回）。
    找这一镜在 since 之后交的视频任务，认领它，别把一条在跑的片子记成失败。"""
    from datetime import datetime, timezone

    return db.execute(select(GenTask).where(
        GenTask.ref_kind == "shot", GenTask.ref_id == shot_id, GenTask.capability == "video.image_to_video",
        GenTask.created_at >= datetime.fromtimestamp(since - 5, tz=timezone.utc),
    ).order_by(GenTask.created_at.desc())).scalars().first()


def advance(db: Session, run: StudioRun, now: float | None = None) -> None:
    """把一个工作流往前推一步（一次只动当前那一镜）。"""
    from app.director import from_shot

    now = time.time() if now is None else now
    items = [dict(i) for i in run.items_json or []]
    if run.status == "queued":
        run.status, run.started_at = "running", utcnow()
    cur = next((i for i in items if i.get("status") in ("pending", "running")), None)
    if cur is None:
        run.status, run.finished_at = finished_status(items), utcnow()
        run.items_json = items
        db.commit()
        return
    opts = run.options_json or {}
    if _needs_review(opts):
        _review_step(db, run, items, now)
        return
    shot = db.get(Shot, cur["shot_id"])
    plan = db.get(ShotPlan, run.shot_plan_id)
    if shot is None or plan is None:
        cur.update(status="failed", error="镜头不在了（分镜重编译过？）", finished_at=now)
    elif cur.get("step") == "audio":
        cur.setdefault("started_at", now)
        if _audio_step(db, run, plan, cur, now):
            cur.update(step=after_audio(run.options_json or {}), status="pending")
    elif cur.get("step") == "frame":
        _frame_step(db, run, plan, shot, cur, now)
    elif cur.get("step") == "video":
        _video_step(db, run, plan, shot, cur, now)
    elif cur.get("step") == "director" and not cur.get("submitted"):
        opts = run.options_json or {}
        prev = (shot.camera_json or {}).get("director_run") or {}
        scene_id = prev.get("scene_id") if opts.get("reuse_scene", True) else None
        try:
            # 白模方案也守「先出分镜图」：frames_only 走到身份首帧就停，不出成片
            out = from_shot.render_shot(db, shot.id, scene_id=scene_id, profile=run.profile,
                                        audio=opts.get("audio", "auto"),
                                        frames_only=opts.get("stop_after") == "frame")
            cur.update(status="running", submitted=now, blender_job_id=out["blender_job_id"],
                       scene_id=out["scene_id"], audio=out.get("audio"), reused=bool(scene_id))
        except Exception as exc:                      # noqa: BLE001 —— 一镜搭景失败不拖垮整个工作流
            db.rollback()
            log.warning("一键出片：镜 %s 交不出导演任务：%s", cur.get("order_no"), exc)
            cur.update(status="failed", error=f"搭景/交任务失败：{exc}"[:300], finished_at=now)
    elif cur.get("step") == "director":
        verdict, error = director_verdict(from_shot.run_status(db, shot), float(cur["submitted"]), now)
        if verdict == "succeeded":
            cur.update(step="done", status="succeeded", finished_at=now)
        elif verdict == "failed":
            cur.update(status="failed", error=(error or "失败")[:300], finished_at=now)
    run.items_json = items                            # 换新列表：JSONB 原地改 SQLAlchemy 看不见
    db.commit()


def _needs_review(opts: Mapping[str, Any]) -> bool:
    """关键帧方案先导演审片（整批一次），审过（或审失败）记在 options_json["reviewed"]。
    要明写 review=True（接口默认开）；老的 run 没有这个键，不补审。"""
    return opts.get("method", "keyframe") == "keyframe" and opts.get("review") is True and not opts.get("reviewed")


def _review_step(db: Session, run: StudioRun, items: list[dict[str, Any]], now: float) -> None:
    """导演审片：这次要出的镜头按场次连起来过一遍（本机 LM Studio），结果挂在 shots.camera_json["review"]。
    审不成不拦出图：记下原因，接着按分镜原文出。"""
    from app.pipelines import director_review

    from app.models import StudioBoard

    plan = db.get(ShotPlan, run.shot_plan_id)
    picked = [i["shot_id"] for i in items if i.get("status") == "pending"]
    # 只重画几镜也按整张画布审：谁是谁要看整场戏（台词、站位在别的镜里）
    board = db.get(StudioBoard, run.board_id) if getattr(run, "board_id", None) else None
    scope = list((getattr(board, "scope_json", None) or {}).get("shot_ids") or [])
    ids = list(dict.fromkeys([*scope, *picked])) if scope else picked
    shots = [s for s in (db.get(Shot, i) for i in ids) if s is not None]
    opts = dict(run.options_json or {})
    if plan is not None and shots:
        # 重画分镜图（reuse_frames=False）时一并重审：用户点重画多半就是嫌上一版不对
        force = bool(opts.get("re_review")) or not opts.get("reuse_frames", True)
        res = director_review.review_shots(db, plan, shots, force=force)
        opts["review_result"] = {
            "reviewed": len(res["reviewed"]), "skipped": res["skipped"], "errors": res["errors"][:4],
            "continuity": res["continuity"][:4],
            "issues": [{"order_no": r["order_no"], "issues": r["issues"]} for r in res["reviewed"] if r["issues"]][:20],
        }
    opts["reviewed"] = now
    run.options_json = opts
    run.items_json = items
    db.commit()


def _pick_target(shot: Shot) -> str:
    from app.pipelines.director_review import review_of

    rv = review_of(shot)
    return (rv or {}).get("first_frame") or (shot.description or "")


def _frame_step(db: Session, run: StudioRun, plan: ShotPlan, shot: Shot, cur: dict[str, Any], now: float) -> None:
    """关键帧方案第一步：定妆照＋场景图 → 关键帧（可以几张候选，视觉模型挑一张），挂到这一镜的首帧。"""
    from app.pipelines import keyframe

    opts = run.options_json or {}
    engine = opts.get("engine", "local")
    if cur.get("frame_tasks"):
        _candidates_step(db, run, plan, shot, cur, now)
        return
    if not cur.get("frame_task"):
        if opts.get("reuse_frames", True) and _keyframe_ready(db, shot, engine):
            if opts.get("stop_after") == "frame":
                cur.update(step="done", status="succeeded", frame="reused", stopped="frame", finished_at=now)
            else:
                cur.update(step="video", status="pending", frame="reused")
            return
        try:
            n = int(opts.get("candidates", 1) or 1)
            if n > 1:
                tasks = keyframe.submit_candidates(db, plan, shot, engine, n)
                cur.update(status="running", frame_tasks=[t.id for t in tasks], submitted=now, polled=now)
            else:
                task = keyframe.submit_keyframe(db, plan, shot, engine)
                cur.update(status="running", frame_task=task.id, submitted=now, polled=now)
        except Exception as exc:                      # noqa: BLE001 —— 缺定妆照、模型不能用：这一镜失败，接着下一镜
            db.rollback()
            cur.update(status="failed", error=f"关键帧：{exc}"[:300], finished_at=now)
        return
    verdict, error = _task_step(db, cur, "frame_task", now, FRAME_TIMEOUT_S)
    if verdict == "succeeded":
        if opts.get("stop_after") == "frame":
            # 先出分镜图（9-29 定的原则）：审过关键帧再出视频，这一镜到这里就算完成
            cur.update(step="done", status="succeeded", stopped="frame", finished_at=now)
        else:
            cur.update(step="video", status="pending", submitted=None, polled=None)
    elif verdict == "failed":
        cur.update(status="failed", error=f"关键帧：{error}"[:300], finished_at=now)


def _after_frame(cur: dict[str, Any], opts: Mapping[str, Any], now: float) -> None:
    if opts.get("stop_after") == "frame":
        cur.update(step="done", status="succeeded", stopped="frame", finished_at=now)
    else:
        cur.update(step="video", status="pending", submitted=None, polled=None)


def _candidates_step(db: Session, run: StudioRun, plan: ShotPlan, shot: Shot, cur: dict[str, Any], now: float) -> None:
    """几张候选都出完后，让本机视觉模型对着定妆照挑一张挂上；挑图失败就用第一张成功的。"""
    from app.capability.service import poll_task
    from app.pipelines import frame_select, keyframe

    tasks = [db.get(GenTask, t) for t in cur["frame_tasks"]]
    if now - float(cur.get("polled") or 0) > POLL_EVERY_S:
        cur["polled"] = now
        for t in tasks:
            if t is not None and t.status.value not in ("succeeded", "failed", "cancelled"):
                try:
                    poll_task(db, t)
                    db.commit()
                except Exception:                     # noqa: BLE001 —— 网关暂时连不上：下一轮再问
                    db.rollback()
    states = [t.status.value if t is not None else "failed" for t in tasks]
    if any(st not in ("succeeded", "failed", "cancelled") for st in states):
        if now - float(cur["submitted"]) > FRAME_TIMEOUT_S * max(1, len(tasks)):
            cur.update(status="failed", error="关键帧候选超时", finished_at=now)
        return
    ok = [(t.id, got) for t in tasks if t is not None and t.status.value == "succeeded"
          and (got := keyframe.candidate_url(db, t.id))]
    if not ok:
        err = next((str((t.error_json or {}).get("message") or "") for t in tasks if t is not None and t.error_json), "")
        cur.update(status="failed", error=f"关键帧：{err or '候选全部失败'}"[:300], finished_at=now)
        return
    choice = frame_select.pick(db, keyframe.pick_refs(db, plan, shot), [u for _, (_, u) in ok], _pick_target(shot))
    best = ok[choice["best"]] if choice["best"] < len(ok) else ok[0]
    keyframe.attach_candidate(db, shot, best[0], best[1][0], {**choice, "candidates": [a for _, (a, _) in ok]})
    cur.update(pick={"best": choice["best"], "of": len(ok), "reason": choice["reason"]})
    db.commit()
    _after_frame(cur, run.options_json or {}, now)


def _video_step(db: Session, run: StudioRun, plan: ShotPlan, shot: Shot, cur: dict[str, Any], now: float) -> None:
    """关键帧方案第二步：视频模型钉住关键帧出片，按 ref_kind=shot 挂回这一镜。"""
    from app.pipelines import keyframe

    opts = run.options_json or {}
    if not cur.get("video_task"):
        try:
            res = keyframe.submit_video(db, plan, shot, opts.get("engine", "local"),
                                        size=PROFILE_SIZE.get(run.profile, PROFILE_SIZE["fast"]))
        except Exception as exc:                      # noqa: BLE001
            db.rollback()
            log.warning("一键出片：镜 %s 交视频出错：%s", cur.get("order_no"), exc)
            got = _recent_video_task(db, shot.id, now)
            res = {"task": got.id} if got is not None else {"skipped": str(exc)}
        if res.get("skipped"):
            cur.update(status="failed", error=f"出视频：{res['skipped']}"[:300], finished_at=now)
        else:
            cur.update(status="running", video_task=res["task"], submitted=now, polled=now,
                       audio=res.get("audio") or cur.get("audio"))
        return
    verdict, error = _task_step(db, cur, "video_task", now, VIDEO_TIMEOUT_S)
    if verdict == "succeeded":
        db.refresh(shot)
        if shot.video_asset_id:
            cur.update(step="done", status="succeeded", finished_at=now)
        elif now - float(cur["submitted"]) > VIDEO_TIMEOUT_S:
            cur.update(status="failed", error="视频出了但没挂回这一镜", finished_at=now)
    elif verdict == "failed":
        cur.update(status="failed", error=f"出视频：{error}"[:300], finished_at=now)


def cancel(db: Session, run: StudioRun) -> StudioRun:
    """取消：没开始的镜头标 skipped，正在跑的那一镜把导演任务也取消掉。"""
    items = [dict(i) for i in run.items_json or []]
    for i in items:
        if i.get("status") == "running":
            try:
                _cancel_shot_jobs(db, i)
            except Exception:                         # noqa: BLE001 —— 取消不了也照样把工作流停下
                log.exception("取消导演任务失败：%s", i.get("shot_id"))
            i.update(status="failed", error="已取消")
        elif i.get("status") == "pending":
            i["status"] = "skipped"
    run.items_json, run.status, run.finished_at = items, "cancelled", utcnow()
    db.commit()
    return run


# ── 后台线程 ────────────────────────────────────────────────────────────

_LOCK = threading.Lock()
_WAKE = threading.Event()
_WORKER: threading.Thread | None = None


def _tick() -> bool:
    """推进最早的那个工作流一步。返回还有没有在跑的。"""
    with SessionLocal() as db:
        run = db.execute(select(StudioRun).where(StudioRun.status.in_(ACTIVE))
                         .order_by(StudioRun.created_at).limit(1)).scalars().first()
        if run is None:
            return False
        try:
            advance(db, run)
        except Exception:                             # noqa: BLE001
            db.rollback()
            log.exception("一键出片推进失败：%s", run.id)
        return True


def _loop() -> None:
    from app.director import jobs

    try:
        # 先于任何提交：上个进程留下的「运行中」导演任务标失败、排队的重新排上。
        # 晚了的话，这个进程自己刚交的任务会被当成上个进程的残留标失败
        jobs.recover()
    except Exception:                                 # noqa: BLE001
        log.exception("恢复导演任务队列失败")
    while True:
        try:
            busy = _tick()
        except Exception:                             # noqa: BLE001 —— 库连不上之类，过一会儿再试
            log.exception("一键出片后台线程出错")
            busy = True
        # 闲着时睡久一点；有人提交新工作流会 kick() 叫醒
        _WAKE.wait(TICK_S if busy else 60)
        _WAKE.clear()


def ensure_worker() -> None:
    global _WORKER
    with _LOCK:
        if _WORKER is None or not _WORKER.is_alive():
            _WORKER = threading.Thread(target=_loop, daemon=True, name="canvas-runs")
            _WORKER.start()


def kick() -> None:
    ensure_worker()
    _WAKE.set()


def resume() -> int:
    """core 启动时调：有没跑完的工作流就把后台线程拉起来。返回在跑的个数。"""
    try:
        with SessionLocal() as db:
            n = len(db.execute(select(StudioRun.id).where(StudioRun.status.in_(ACTIVE))).all())
    except Exception:                                 # noqa: BLE001 —— 表还没迁移等，启动不能因此失败
        log.exception("检查一键出片工作流失败")
        return 0
    if n:
        kick()
    return n
