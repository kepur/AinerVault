"""在本机无头 Blender 里跑 world_multicam（一次一个进程；最小环境变量；不执行外来代码）。"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from app.director import blender_adapter

WORKER = Path(__file__).resolve().parents[1] / "director" / "blender_worker" / "world_multicam.py"
LOCK = Path(os.environ.get("AINER_BLENDER_LOCK", "/tmp/ainer_blender.lock"))


class BlenderRunError(RuntimeError):
    pass


def run(job: dict[str, Any], *, timeout_s: int = 900, log_path: str | None = None) -> dict[str, Any]:
    exe = blender_adapter.binary()
    if not exe:
        raise BlenderRunError("找不到 Blender 可执行文件")
    out = Path(job["out_dir"])
    out.mkdir(parents=True, exist_ok=True)
    jp = out / "job.json"
    jp.write_text(json.dumps(job), encoding="utf-8")
    # 单 GPU：同时只跑一个 Blender（锁文件，进程退出即释放）
    t0 = time.time()
    while True:
        try:
            fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            break
        except FileExistsError:
            try:
                pid = int(LOCK.read_text() or 0)
                os.kill(pid, 0)
            except (ValueError, ProcessLookupError, PermissionError):
                LOCK.unlink(missing_ok=True)
                continue
            if time.time() - t0 > timeout_s:
                raise BlenderRunError("等待其它 Blender 任务超时")
            time.sleep(2)
    try:
        cmd = [exe, "-b", "--factory-startup", "--python", str(WORKER), "--", str(jp)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s, env=blender_adapter._env(),
                           stdin=subprocess.DEVNULL)
    finally:
        LOCK.unlink(missing_ok=True)
    if log_path:
        Path(log_path).write_text(r.stdout[-200000:] + "\n--- stderr ---\n" + r.stderr[-50000:], encoding="utf-8")
    done = [ln for ln in r.stdout.splitlines() if ln.startswith("AINER_DONE ")]
    if r.returncode != 0 or not done:
        err = [ln for ln in r.stdout.splitlines() if ln.startswith("AINER_ERROR ")]
        raise BlenderRunError((err[-1] if err else r.stderr[-1500:]) or f"Blender 退出码 {r.returncode}")
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    manifest["check"] = json.loads((out / "check.json").read_text(encoding="utf-8"))
    return manifest
