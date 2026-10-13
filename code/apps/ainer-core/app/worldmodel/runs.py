"""world-greybox 运行的生命周期：建运行（需开关）→ 后台 worker（独立进程，防 core 热重载打断；Mac 上套 caffeinate 防睡眠）。"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ids import new_id
from app.models import WorldPipelineRun
from app.worldmodel import switches

CORE_ROOT = Path(__file__).resolve().parents[2]


class RunError(RuntimeError):
    def __init__(self, code: str, msg: str, status: int = 400):
        super().__init__(msg)
        self.code, self.status = code, status


def create(db: Session, *, world_id: str, scope_kind: str, scope_id: str, config: dict[str, Any],
           title: str | None = None, out_dir: str | None = None, import_state: str | None = None,
           check_switch: bool = True) -> WorldPipelineRun:
    if check_switch:
        d = switches.resolve(db, **{scope_kind: scope_id})
        if not d.enabled:
            raise RunError("greybox_disabled", f"world-greybox 未对 {scope_kind}={scope_id} 打开：{d.reason}"
                           "（默认路径是原动态漫剧管线；需要 feature flag + 作用域开关）", 409)
        config = {**config, "fallback_to_original": config.get("fallback_to_original", d.fallback_to_original)}
    run = WorldPipelineRun(id=new_id("wpr"), world_id=world_id, scope_kind=scope_kind, scope_id=scope_id, title=title, config=config,
                           status="pending", progress=0.0, out_dir=out_dir or "", state={"shots": {}})
    db.add(run)
    db.flush()
    if not run.out_dir:
        run.out_dir = str(CORE_ROOT.parents[2] / "var" / "world_greybox" / "runs" / run.id)
    if import_state:
        st = json.loads(Path(import_state).read_text())
        run.state = {"shots": {k: {kk: vv for kk, vv in v.items() if kk != "final"} for k, v in st.get("shots", {}).items()},
                     "music": st.get("music") or {}, "imported_from": import_state}
    db.flush()
    return run


def worker_pid(run: WorldPipelineRun) -> int | None:
    pid = (run.state or {}).get("worker_pid")
    if not pid:
        return None
    try:
        os.kill(int(pid), 0)
        return int(pid)
    except (OSError, ValueError):
        return None


def start(db: Session, run: WorldPipelineRun, *, force: list[int] | None = None, only: list[int] | None = None) -> int:
    """起后台 worker；同一运行同时只允许一个。"""
    pid = worker_pid(run)
    if pid:
        raise RunError("already_running", f"运行 {run.id} 的 worker 仍在跑（pid {pid}）", 409)
    Path(run.out_dir).mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-u", "-m", "app.worldmodel.pipeline_worker", run.id]
    if force:
        cmd += ["--force", ",".join(map(str, force))]
    if only:
        cmd += ["--only", ",".join(map(str, only))]
    if shutil.which("caffeinate"):
        cmd = ["caffeinate", "-dims", *cmd]
    log = open(Path(run.out_dir) / "worker.log", "ab")
    env = {k: v for k, v in os.environ.items()}
    p = subprocess.Popen(cmd, cwd=str(CORE_ROOT), stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                         start_new_session=True, env=env)
    run.state = {**(run.state or {}), "worker_pid": p.pid}
    run.status = "queued"
    db.commit()
    return p.pid


def out(run: WorldPipelineRun, *, with_state: bool = False) -> dict[str, Any]:
    st = run.state or {}
    d = {"id": run.id, "world_id": run.world_id, "scope_kind": run.scope_kind, "scope_id": run.scope_id,
         "title": run.title, "status": run.status, "progress": run.progress, "error": run.error, "out_dir": run.out_dir,
         "running": worker_pid(run) is not None, "report": st.get("report"), "final": st.get("final"),
         "created_at": run.created_at.isoformat() if run.created_at else None,
         "updated_at": run.updated_at.isoformat() if run.updated_at else None}
    if with_state:
        d["state"] = st
        d["config"] = run.config
    return d


def list_runs(db: Session, scope_id: str | None = None) -> list[WorldPipelineRun]:
    q = select(WorldPipelineRun).order_by(WorldPipelineRun.created_at.desc())
    if scope_id:
        q = q.where(WorldPipelineRun.scope_id == scope_id)
    return list(db.scalars(q.limit(50)))
