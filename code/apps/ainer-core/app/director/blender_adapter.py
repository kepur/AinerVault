"""Blender 适配器：烘焙好的场景 → job.json → Blender 无头进程 → 控制素材。

- 一次只起一个 Blender（本机单 GPU，一个一个跑）
- 逐行读进度（AINER_PROGRESS）；stall_sec 秒没有新进度就当卡死：杀掉进程，换一个新进程重来（retries 次）
- 子进程只拿到最少的环境变量（PATH/HOME/TMPDIR/LANG）：数据库地址、密钥一概不传
- Blender 只读数据（job.json、烘焙 JSON），不执行任何 LLM 写的代码
"""
from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from app.director import config

WORKER = Path(__file__).resolve().parent / "blender_worker" / "worker.py"
PASSES = ["preview", "clay", "depth", "pose", "canny"]


class BlenderError(RuntimeError):
    pass


class BlenderCancelled(BlenderError):
    pass


def binary() -> str | None:
    cfg = config.load("blender")
    b = cfg.get("binary")
    if b and os.path.exists(b):
        return b
    return shutil.which("blender")


@lru_cache
def version() -> str | None:
    b = binary()
    if not b:
        return None
    try:
        out = subprocess.run([b, "-b", "--factory-startup", "--version"], capture_output=True, stdin=subprocess.DEVNULL,
                             timeout=60, env=_env()).stdout.decode("utf-8", "replace")
        return out.splitlines()[0].strip() if out else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def status() -> dict[str, Any]:
    return {"enabled": config.enabled("blender_enabled"), "binary": binary(), "version": version()}


def _env() -> dict[str, str]:
    keep = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL") if k in os.environ}
    keep.setdefault("PATH", "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin")
    return keep


def _reader(stream, q: queue.Queue) -> None:
    for raw in iter(stream.readline, b""):
        q.put(raw.decode("utf-8", "replace").rstrip("\n"))
    q.put(None)


def render(*, job_id: str, scene_id: str | None, baked_path: str, out_dir: str, resolution: tuple[int, int],
           passes: list[str] | None = None, on_progress: Callable[[dict[str, Any]], None] | None = None,
           cancelled: Callable[[], bool] | None = None, media_root: str | None = None) -> dict[str, Any]:
    """跑一次 Blender，返回 manifest（dict）。失败抛 BlenderError（重试用完之后）。"""
    config.require("blender_enabled", "Blender 渲染")
    b = binary()
    if not b:
        raise BlenderError("找不到 Blender：装在 /Applications/Blender.app，或在 configs/director/blender.yaml 写 binary")
    cfg = config.load("blender")
    job = {
        "job_id": job_id, "scene_id": scene_id, "out_dir": out_dir, "baked_path": baked_path,
        "resolution": [int(resolution[0]), int(resolution[1])],
        "passes": [p for p in (passes or cfg.get("passes") or PASSES) if p in PASSES],
        "ffmpeg": shutil.which("ffmpeg") or "ffmpeg", "media_root": media_root,
        "preview_samples": int(cfg.get("preview_samples") or 16), "save_blend": bool(cfg.get("save_blend", True)),
    }
    job_path = os.path.join(out_dir, "job.json")
    with open(job_path, "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False, indent=1)

    stall = float(cfg.get("stall_sec") or 180)
    deadline = time.time() + float(cfg.get("timeout_sec") or 1800)
    retries = int(cfg.get("retries") or 0)
    last_err = "未知错误"
    for attempt in range(retries + 1):
        log_path = os.path.join(out_dir, f"blender.{attempt + 1}.log")
        proc = subprocess.Popen([b, "-b", "--factory-startup", "--python", str(WORKER), "--", job_path],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=_env())
        q: queue.Queue = queue.Queue()
        threading.Thread(target=_reader, args=(proc.stdout, q), daemon=True).start()
        last = time.time()
        manifest_path, error = None, None
        with open(log_path, "w", encoding="utf-8") as log:
            while True:
                if cancelled and cancelled():
                    proc.kill()
                    raise BlenderCancelled("任务被取消")
                try:
                    line = q.get(timeout=1.0)
                except queue.Empty:
                    now = time.time()
                    if now - last > stall or now > deadline:
                        proc.kill()
                        error = f"Blender {int(now - last)} 秒没有进度，判定卡死，已杀掉进程" if now - last > stall else "超过总时限"
                        break
                    continue
                if line is None:
                    break
                log.write(line + "\n")
                if not line.startswith("AINER_"):
                    continue
                last = time.time()
                kind, _, payload = line.partition(" ")
                try:
                    data = json.loads(payload) if payload else {}
                except json.JSONDecodeError:
                    data = {"raw": payload}
                if kind in ("AINER_PROGRESS", "AINER_STAGE") and on_progress:
                    on_progress({"kind": kind[6:].lower(), "attempt": attempt + 1, **data})
                elif kind == "AINER_DONE":
                    manifest_path = data.get("manifest")
                elif kind == "AINER_ERROR":
                    error = data.get("message") or "Blender 报错"
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
        if manifest_path and os.path.exists(manifest_path):
            with open(manifest_path, encoding="utf-8") as f:
                return json.load(f)
        last_err = error or f"Blender 退出码 {proc.returncode}，没有产出 manifest（日志：{log_path}）"
        if on_progress:
            on_progress({"kind": "retry", "attempt": attempt + 1, "error": last_err})
    raise BlenderError(last_err)


def probe(*, baked_path: str, out_dir: str, resolution: tuple[int, int], lens_mm: float = 40.0,
          shot_size: str | None = None, focus: str | None = None, timeout_s: float = 180.0) -> dict[str, Any]:
    """试机位（只渲小色块图，约 5 秒）：返回 {planner: LLM 原机位的得分和每人露出面积, best: 最佳机位（协议坐标）}。"""
    config.require("blender_enabled", "Blender 渲染")
    b = binary()
    if not b:
        raise BlenderError("找不到 Blender")
    os.makedirs(out_dir, exist_ok=True)
    job = {"job_id": "probe", "out_dir": out_dir, "baked_path": baked_path,
           "resolution": [int(resolution[0]), int(resolution[1])], "passes": [], "save_blend": False,
           "probe": {"lens_mm": float(lens_mm), "shot_size": shot_size, "focus": focus}}
    job_path = os.path.join(out_dir, "job.json")
    with open(job_path, "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False)
    proc = subprocess.run([b, "-b", "--factory-startup", "--python", str(WORKER), "--", job_path],
                          capture_output=True, text=True, stdin=subprocess.DEVNULL, env=_env(), timeout=timeout_s)
    path = os.path.join(out_dir, "probe.json")
    if not os.path.exists(path):
        tail = "\n".join((proc.stdout or "").splitlines()[-8:])
        raise BlenderError(f"试机位失败：{tail[-600:]}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)
