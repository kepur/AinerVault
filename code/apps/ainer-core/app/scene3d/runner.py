"""3D-BOX 场景脚本的执行器：起一个 node 子进程，在 vm 沙箱里跑 scene.js。

脚本多半是 LLM 写的，当不可信代码：
  - 子进程只带最小的环境变量（不把数据库串、密钥带进去）、工作目录在临时目录
  - node 限内存；沙箱内同步超时，外面再加一道墙钟超时，到点直接杀
  - 沙箱细节见 runner.mjs

运行时本体（vendor/scene-runtime.iife.js）由前端 ainer-studio 的 src/scene 打包而来：
`npm run build:runtime`。前端渲染与后端执行用同一份代码，场景文档两边一致。
"""
from __future__ import annotations

import functools
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

RUNNER = Path(__file__).with_name("runner.mjs")
RUNTIME = Path(__file__).with_name("vendor") / "scene-runtime.iife.js"


class SceneRunError(RuntimeError):
    """执行器自己坏了（找不到 node、子进程崩溃、输出不是 JSON）—— 不是脚本写错。"""


@functools.lru_cache(maxsize=1)
def node_bin() -> str:
    for cand in (os.environ.get("CORE_NODE_BIN"), shutil.which("node"),
                 "/opt/homebrew/bin/node", "/usr/local/bin/node", "/usr/bin/node"):
        if cand and Path(cand).exists():
            return cand
    raise SceneRunError("找不到 node：3D-BOX 场景脚本要用 Node.js 执行（设 CORE_NODE_BIN 指向 node）")


def _call(payload: dict[str, Any], *, wall_timeout: float) -> dict[str, Any]:
    if not RUNTIME.exists():
        raise SceneRunError(f"缺少场景运行时 {RUNTIME}：在 ainer-studio 里跑 npm run build:runtime")
    try:
        proc = subprocess.run(
            [node_bin(), "--max-old-space-size=384", "--disallow-code-generation-from-strings", str(RUNNER)],
            input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            capture_output=True, timeout=wall_timeout,
            # 空环境：LLM 写的脚本即便逃出 vm，也拿不到数据库串和密钥
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
            cwd=tempfile.gettempdir(),
        )
    except subprocess.TimeoutExpired as exc:
        raise SceneRunError(f"场景执行超过 {wall_timeout:.0f} 秒被终止") from exc
    if proc.returncode != 0 and not proc.stdout:
        raise SceneRunError(f"node 退出码 {proc.returncode}：{proc.stderr.decode('utf-8', 'replace')[-400:]}")
    try:
        return json.loads(proc.stdout.decode("utf-8"))
    except ValueError as exc:
        raise SceneRunError(f"执行器输出不是 JSON：{proc.stdout[:200]!r} {proc.stderr[-300:]!r}") from exc


def compile_scene(script: str, *, seed: int = 1, overrides: dict[str, Any] | None = None,
                  timeout_ms: int = 4000) -> dict[str, Any]:
    """跑一遍脚本。返回 {ok, errors[{message,line,col}], warnings[], summary, doc, ms}。

    脚本报错不抛异常 —— 报错本身就是给智能体看的结果（ok=false、errors 带行号），
    已经搭好的部分照样出文档，界面上能看到停在哪。
    """
    return _call({"mode": "compile", "script": script, "seed": seed,
                  "overrides": overrides or None, "timeoutMs": timeout_ms},
                 wall_timeout=timeout_ms / 1000 + 15)


@functools.lru_cache(maxsize=1)
def catalog() -> dict[str, Any]:
    """预制件、体型、姿势、运镜预设的目录（给智能体和界面）。"""
    return _call({"mode": "catalog"}, wall_timeout=20)


def shot_reports(doc: dict[str, Any], shots: list[dict[str, Any]]) -> list[str]:
    """机位在某一刻的构图报告：画面里有谁、在哪、多大、被谁挡住。"""
    if not doc or not shots:
        return []
    r = _call({"mode": "shot", "doc": doc, "shots": shots}, wall_timeout=20)
    return list(r.get("reports") or [])


def bake_scene(doc: dict[str, Any], *, fps: int | None = None, camera: str | None = None,
               frames: int | None = None, t0: float = 0.0, timeout_ms: int = 60000) -> dict[str, Any]:
    """逐帧解算渲染场景（给 Blender／UE）：几何部件表、逐帧位姿、人偶关节、机位。

    在沙箱里算 —— 文档出自不可信的场景脚本，求值时照样不给它宿主对象。
    """
    options = {k: v for k, v in {"fps": fps, "camera": camera, "frames": frames, "t0": t0}.items() if v is not None}
    r = _call({"mode": "bake", "doc": doc, "options": options, "timeoutMs": timeout_ms},
              wall_timeout=timeout_ms / 1000 + 20)
    if "errors" in r and not r.get("objects"):
        raise SceneRunError("烘焙失败：" + "；".join(e.get("message", "") for e in r["errors"]))
    return r
