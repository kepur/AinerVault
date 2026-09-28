"""Job Orchestrator：渲染任务排队、执行、状态、取消。

一个工作线程，一个接一个跑（本机一块 GPU：Blender 与视频模型别抢）。
提交时就把场景烘焙成快照（scene_resolved.json）放进任务目录 —— 之后再改场景，排着的任务照旧按提交时的样子渲。
服务重启：内存队列丢了，启动时把「运行中」的标成失败（说明原因）、「排队中」的重新排上。
"""
from __future__ import annotations

import json
import logging
import queue
import shutil
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.capability.mediastore import media_root
from app.db import SessionLocal
from app.director import blender_adapter, config, outputs, store
from app.director.protocol import RenderPlan
from app.director.renderers import registry
from app.director.renderers.base import RenderRequest, RendererError
from app.ids import new_id
from app.models import DirectorJob, DirectorOutput, DirectorScene
from app.models.base import utcnow
from app.scene3d.runner import bake_scene

log = logging.getLogger(__name__)

_Q: "queue.Queue[str]" = queue.Queue()
_CANCEL: set[str] = set()
_LOCK = threading.Lock()
_WORKER: threading.Thread | None = None
_RECOVERED = False

#: Blender 各通道在总进度里的份量（按实测耗时）
_WEIGHT = {"build": 2, "walk": 3, "pose": 3, "preview": 45, "clay": 10, "depth": 30, "canny": 3, "encode": 4}


class JobError(ValueError):
    pass


def job_out(j: DirectorJob, db: Session | None = None) -> dict[str, Any]:
    out = {
        "id": j.id, "scene_id": j.scene_id, "parent_id": j.parent_id, "job_type": j.job_type, "backend": j.backend,
        "status": j.status, "progress": j.progress_json or {}, "error": j.error, "attempts": j.attempts,
        "input": {k: v for k, v in (j.input_json or {}).items() if k not in ("baked_path",)},
        "manifest": j.output_manifest_json, "created_at": j.created_at.isoformat() if j.created_at else None,
        "started_at": j.started_at.isoformat() if j.started_at else None,
        "finished_at": j.finished_at.isoformat() if j.finished_at else None,
    }
    if db is not None:
        out["outputs"] = outputs.outputs_of(db, j.id)
    return out


# ── 提交 ────────────────────────────────────────────────

def submit_blender(db: Session, scene: DirectorScene, render_plan: dict[str, Any] | None = None,
                   chain: dict[str, Any] | None = None) -> DirectorJob:
    """chain：渲完之后接着做什么（{"final": 成片参数, "shot_id": 出完挂到哪一镜}）。入队前写进任务，
    执行线程读到的就是全的 —— 事后再补，线程手里那份可能还是旧的。"""
    config.require("blender_enabled", "Blender 渲染")
    rp = RenderPlan.model_validate({**((scene.protocol_json or {}).get("render_plan") or {}), **(render_plan or {})})
    cfg = config.load("blender")
    if not render_plan or "output_resolution" not in render_plan:
        w, h = cfg.get("resolution") or [1024, 576]
        rp = rp.model_copy(update={"output_resolution": (int(w) // 32 * 32, int(h) // 32 * 32)})
    doc = store.scene_doc(db, scene)
    job = DirectorJob(id=new_id("djob"), scene_id=scene.id, job_type="blender_render", backend="blender", status="queued",
                      attempts=0, input_json={"render_plan": rp.model_dump(mode="json"), "scene_version": scene.version})
    db.add(job)
    db.flush()
    jd = config.job_dir(job.id)
    baked = bake_scene(doc, fps=rp.fps, camera=None if rp.camera == "cut" else rp.camera)
    (jd / "scene_resolved.json").write_text(json.dumps(baked, ensure_ascii=False), encoding="utf-8")
    (jd / "scene_protocol.json").write_text(json.dumps(scene.protocol_json, ensure_ascii=False, indent=1), encoding="utf-8")
    job.input_json = {**job.input_json, "baked_path": str(jd / "scene_resolved.json"), "frames": baked["frames"],
                      "duration": baked["duration"], "fps": baked["fps"], **({"chain": chain} if chain else {})}
    db.commit()
    enqueue(job.id)
    return job


def _control_output(db: Session, parent: DirectorJob, kind: str) -> DirectorOutput | None:
    return db.execute(select(DirectorOutput).where(DirectorOutput.job_id == parent.id, DirectorOutput.kind == kind)).scalars().first()


def submit_final(db: Session, parent: DirectorJob, body: dict[str, Any]) -> DirectorJob:
    if parent.job_type != "blender_render" or parent.status != "succeeded":
        raise JobError("先把控制素材渲出来（Blender 任务成功之后才能出成片）")
    name = body.get("renderer") or "ltx_097"
    renderer = registry.get(name)
    config.require(renderer.flag, f"渲染器 {name} ")
    cfg = renderer.cfg()
    ctype = body.get("control_type") or cfg.get("default_mode") or "v2v"
    source = (body.get("v2v_source") or (cfg.get("v2v") or {}).get("source") or "preview") if ctype == "v2v" else ctype
    videos: dict[str, str] = {}
    if ctype == "union":
        # union：深度／骨架／边缘几路同时喂（LTX 2.x 的 Union Control），有哪路给哪路
        for kind in (cfg.get("union_control") or {}).get("types") or ("depth", "pose", "canny"):
            out = _control_output(db, parent, kind)
            if out is not None and out.url:
                videos[kind] = out.url
        if not videos:
            raise JobError("控制素材里没有深度／骨架／边缘任何一路：重新渲一遍并勾上它们")
        ctl = _control_output(db, parent, next(iter(videos)))
    else:
        ctl = _control_output(db, parent, source)
    if ctl is None or not ctl.url:
        raise JobError(f"控制素材里没有 {source} 通道：重新渲一遍并勾上它")
    first = _control_output(db, parent, "first_frame")
    scene = db.get(DirectorScene, parent.scene_id) if parent.scene_id else None
    protocol = (scene.protocol_json if scene else None) or {}
    refs = [u for u in (body.get("reference_images") or []) if isinstance(u, str) and u]
    inp = {
        "renderer": name, "control_type": ctype, "control_source": source, "control_video": ctl.url,
        "control_videos": videos, **({"chain": body["chain"]} if body.get("chain") else {}),
        "first_frame": first.url if first else None, "user_prompt": (body.get("prompt") or "").strip(),
        "negative_prompt": body.get("negative_prompt") or "", "seed": body.get("seed"), "denoise": body.get("denoise"),
        "strength": body.get("strength"), "pin_first": bool(body.get("pin_first", bool(refs))), "reference_images": refs,
        "style": body.get("style"), "style_prompt": body.get("style_prompt") or "",
        "resolution": body.get("resolution") or cfg.get("resolution") or [768, 448],
        "duration_sec": (parent.input_json or {}).get("duration") or (protocol.get("meta") or {}).get("duration_sec") or 6,
        "fps": (parent.input_json or {}).get("fps") or 24, "use_llm_prompt": bool(body.get("use_llm_prompt", True)),
    }
    job = DirectorJob(id=new_id("djob"), scene_id=parent.scene_id, parent_id=parent.id, job_type="final_render",
                      backend=name, status="queued", attempts=0, input_json=inp)
    db.add(job)
    db.commit()
    enqueue(job.id)
    return job


# ── 队列 ────────────────────────────────────────────────

def enqueue(job_id: str) -> None:
    global _WORKER
    _Q.put(job_id)
    with _LOCK:
        if _WORKER is None or not _WORKER.is_alive():
            _WORKER = threading.Thread(target=_work, daemon=True, name="director-jobs")
            _WORKER.start()


def recover() -> int:
    """服务刚起：运行中的标失败（进程已经没了），排队中的重新排上。返回重排的个数。"""
    global _RECOVERED
    if _RECOVERED:
        return 0
    _RECOVERED = True
    n = 0
    with SessionLocal() as db:
        for j in db.execute(select(DirectorJob).where(DirectorJob.status.in_(("running", "queued")))).scalars():
            if j.status == "running":
                j.status, j.error, j.finished_at = "failed", "服务重启，任务中断（可以重新提交）", utcnow()
            else:
                n += 1
                _Q.put(j.id)
        db.commit()
    return n


def cancel(db: Session, job: DirectorJob) -> DirectorJob:
    if job.status == "queued":
        job.status, job.finished_at = "cancelled", utcnow()
    elif job.status == "running":
        _CANCEL.add(job.id)
    db.commit()
    return job


def _work() -> None:
    while True:
        job_id = _Q.get()
        try:
            _run(job_id)
        except Exception:          # noqa: BLE001 —— 一个任务炸了不能拖垮队列
            log.exception("director 任务异常：%s", job_id)


class _Progress:
    """进度写库（节流：一秒一次），用单独的会话，不和任务主会话抢事务。"""

    def __init__(self, job_id: str, passes: list[str] | None = None):
        self.job_id, self.last, self.state = job_id, 0.0, {}
        self.passes = passes or []
        self.done: set[str] = set()

    def percent(self) -> int:
        stages = ["build", "walk"] + [p for p in self.passes if p != "pose"] + ["encode"]
        total = sum(_WEIGHT.get(s, 5) for s in stages) or 1
        got = sum(_WEIGHT.get(s, 5) for s in self.done if s in stages)
        cur = self.state.get("stage")
        if cur in stages and cur not in self.done and self.state.get("total"):
            got += _WEIGHT.get(cur, 5) * min(1.0, (self.state.get("frame") or 0) / self.state["total"])
        return int(100 * got / total)

    def __call__(self, ev: dict[str, Any]) -> None:
        kind = ev.get("kind")
        if kind == "stage":
            prev = self.state.get("stage")
            if prev:
                self.done.add(prev)
            self.state = {"stage": ev.get("stage"), **{k: v for k, v in ev.items() if k not in ("kind", "stage")}}
        elif kind == "progress":
            self.state.update({"stage": ev.get("pass") or self.state.get("stage"), "frame": ev.get("frame"), "total": ev.get("total")})
        elif kind == "retry":
            self.state.update({"retry": ev.get("attempt"), "last_error": ev.get("error")})
        elif kind == "task":
            self.state.update({"task": ev.get("label"), "task_status": ev.get("status"), "elapsed": ev.get("elapsed")})
        now = time.time()
        if now - self.last < 1.0 and kind not in ("stage", "retry"):
            return
        self.last = now
        with SessionLocal() as db:
            j = db.get(DirectorJob, self.job_id)
            if j is not None:
                j.progress_json = {**self.state, "percent": self.percent() if self.passes else self.state.get("percent")}
                db.commit()


def _run(job_id: str) -> None:
    with SessionLocal() as db:
        job = db.get(DirectorJob, job_id)
        if job is None or job.status != "queued":
            return
        job.status, job.started_at, job.attempts, job.error = "running", utcnow(), (job.attempts or 0) + 1, None
        db.commit()
        try:
            if job.job_type == "blender_render":
                _run_blender(db, job)
            elif job.job_type == "final_render":
                _run_final(db, job)
            else:
                raise JobError(f"不认识的任务类型：{job.job_type}")
            job.status = "succeeded"
            db.commit()
            try:
                _chain(db, job)
            except Exception:          # noqa: BLE001 —— 下一步提交失败不能把这一步改判成失败
                log.exception("director 串联下一步失败：%s", job_id)
                db.rollback()
        except (blender_adapter.BlenderCancelled,) as exc:
            job.status, job.error = "cancelled", str(exc)
        except RendererError as exc:
            job.status, job.error = ("cancelled" if "取消" in str(exc) else "failed"), str(exc)
        except Exception as exc:          # noqa: BLE001
            log.exception("director 任务失败：%s", job_id)
            job.status, job.error = "failed", f"{type(exc).__name__}: {exc}"[:2000]
        finally:
            _CANCEL.discard(job_id)
            job.finished_at = utcnow()
            db.commit()


def _run_blender(db: Session, job: DirectorJob) -> None:
    inp = job.input_json or {}
    rp = inp.get("render_plan") or {}
    out = config.job_dir(job.id)
    prog = _Progress(job.id, list(rp.get("passes") or blender_adapter.PASSES))
    manifest = blender_adapter.render(
        job_id=job.id, scene_id=job.scene_id, baked_path=inp["baked_path"], out_dir=str(out),
        resolution=tuple(rp.get("output_resolution") or (1024, 576)), passes=rp.get("passes"),
        on_progress=prog, cancelled=lambda: job.id in _CANCEL, media_root=str(media_root()))
    files = dict(manifest.get("outputs") or {})
    files["manifest"] = "manifest.json"
    outputs.register(db, job, files)
    job.output_manifest_json = manifest
    job.progress_json = {"stage": "done", "percent": 100}


def _has_audio(path: Path) -> bool:
    import subprocess
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                              "-of", "csv=p=0", str(path)], capture_output=True, text=True, timeout=60).stdout
        return bool(out.strip())
    except Exception:  # noqa: BLE001
        return False


def _chain(db: Session, job: DirectorJob) -> None:
    """任务成功之后的下一步：Blender 渲完 → 按 chain.final 提交成片；成片出完 → 挂到 chain.shot_id 那一镜。"""
    ch = (job.input_json or {}).get("chain") or {}
    if not ch:
        return
    if job.job_type == "blender_render" and ch.get("final"):
        submit_final(db, job, {**ch["final"], "chain": {k: v for k, v in ch.items() if k != "final"}})
    elif job.job_type == "final_render" and ch.get("shot_id"):
        from app.models import Asset, Shot, SpecStatus

        out = _control_output(db, job, "final")
        shot = db.get(Shot, ch["shot_id"])
        if out is None or not out.asset_id or shot is None:
            return
        asset = db.get(Asset, out.asset_id)
        if asset is not None:
            asset.meta_json = {**(asset.meta_json or {}), "shot_id": shot.id, "via": "director"}
        shot.video_asset_id = out.asset_id
        shot.status = SpecStatus.ready
        cam = dict(shot.camera_json or {})
        cam["director"] = {"scene_id": job.scene_id, "blender_job_id": job.parent_id, "final_job_id": job.id}
        shot.camera_json = cam
        db.commit()


def _download(url: str, dst: Path) -> Path:
    with urllib.request.urlopen(url, timeout=600) as r, open(dst, "wb") as f:
        shutil.copyfileobj(r, f)
    return dst


def _run_final(db: Session, job: DirectorJob) -> None:
    from app.director import planner

    inp = job.input_json or {}
    scene = db.get(DirectorScene, job.scene_id) if job.scene_id else None
    protocol = (scene.protocol_json if scene else None) or {}
    prog = _Progress(job.id)
    prog({"kind": "stage", "stage": "prompt"})
    extra = " ".join(x for x in (inp.get("user_prompt"), inp.get("style_prompt")) if x)
    seen = None
    motion_path = config.job_dir(job.parent_id) / "motion.json" if job.parent_id else None
    if motion_path and motion_path.exists():
        seen = planner.visibility(json.loads(motion_path.read_text(encoding="utf-8")))
    if inp.get("use_llm_prompt", True) or not inp.get("user_prompt"):
        pr = planner.render_prompt(db, protocol, extra, use_llm=bool(inp.get("use_llm_prompt", True)), seen=seen)
    else:
        pr = {"prompt": extra, "subject": planner.template_prompt(protocol)["subject"], "by": "user"}
    job.input_json = {**inp, "prompt": pr["prompt"], "prompt_by": pr.get("by"), "first_frame_subject": pr.get("subject"),
                      "visibility": seen}
    db.commit()
    renderer = registry.get(job.backend)
    req = RenderRequest(
        renderer=job.backend, prompt=pr["prompt"], negative_prompt=inp.get("negative_prompt") or "",
        control_type=inp["control_type"], control_video=inp["control_video"],
        control_videos=inp.get("control_videos") or {}, first_frame=inp.get("first_frame"),
        pin_first=bool(inp.get("pin_first")), reference_images=inp.get("reference_images") or [], seed=inp.get("seed"),
        fps=int(inp.get("fps") or 24), resolution=tuple(inp.get("resolution") or (768, 448)),
        duration_sec=float(inp.get("duration_sec") or 6), denoise=inp.get("denoise"), strength=inp.get("strength"),
        style=inp.get("style"),
    )
    res = renderer.generate(db, req, on_progress=prog, cancelled=lambda: job.id in _CANCEL,
                            **({"first_frame_subject": pr.get("subject", "")} if job.backend == "ltx_097" else {}))
    out = config.job_dir(job.id)
    files: dict[str, str] = {}
    if res.video_url:
        files["final"] = str(_download(res.video_url, out / "final.mp4"))
    if res.first_frame_url:
        files["styled_first_frame"] = str(_download(res.first_frame_url, out / "styled_first_frame.png"))
    meta: dict[str, Any] = {"renderer": job.backend, "control_type": req.control_type}
    if job.backend == "ltx_25" and files.get("final"):
        # 时间线按素材上的 model / has_audio 决定能不能直接用片子自带的同步音效
        meta.update(model="ltx-2.5-22b-distilled", has_audio=_has_audio(Path(files["final"])))
    outputs.register(db, job, files, meta=meta)
    manifest = {"job_id": job.id, "parent_id": job.parent_id, "renderer": job.backend, "control_type": req.control_type,
                "prompt": pr["prompt"], "outputs": {k: Path(v).name for k, v in files.items()}, "meta": res.meta}
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    job.output_manifest_json = manifest
    job.progress_json = {"stage": "done", "percent": 100}
