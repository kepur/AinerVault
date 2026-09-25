"""UE 适配器：协议＋烘焙 → UE 计划（物体、序列、机位、渲染队列）＋三段 Unreal Python 脚本。

plan() 是纯函数，开关关着也能跑（dry-run：看翻译结果、导出脚本离线调试）。
execute() 真连 UE（Remote Control），要 feature_flags.ue_enabled=true —— V1 关着，调用即 FeatureDisabled。
"""
from __future__ import annotations

from typing import Any

from app.director import config
from app.director.ue_worker.remote.http_client import UERemoteHTTP
from app.director.ue_worker.scripts import build_level, render_queue, setup_camera
from app.director.ue_worker.translator import camera_to_sequencer, scene_to_ue, timeline_to_sequencer


def plan(protocol: dict[str, Any], baked: dict[str, Any], cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = cfg if cfg is not None else config.load("ue")
    level = scene_to_ue.translate(protocol, baked, cfg)
    seq = timeline_to_sequencer.translate(protocol, baked, cfg)
    cams = camera_to_sequencer.translate(baked)
    rp = protocol.get("render_plan") or {}
    render = {"name": seq["name"], "sequence": f"{seq['root']}/{seq['name']}.{seq['name']}", "level": level["level"],
              "resolution": list(rp.get("output_resolution") or [1920, 1080]),
              "output_dir": (cfg.get("movie_render_queue") or {}).get("output_dir") or "",
              "preset": (cfg.get("movie_render_queue") or {}).get("preset") or ""}
    return {
        "enabled": config.enabled("ue_enabled"),
        "level": level, "sequence": seq, "cameras": cams, "render": render,
        "scripts": {"build_level.py": build_level.generate(level),
                    "setup_camera.py": setup_camera.generate(seq, cams),
                    "render_queue.py": render_queue.generate(render)},
        "stats": {"actors": len(level["actors"]), "placeholders": sum(1 for a in level["actors"] if a.get("placeholder")),
                  "cameras": len(cams["cameras"]), "cuts": len(cams["cuts"]), "animations": len(seq["animations"])},
    }


def execute(protocol: dict[str, Any], baked: dict[str, Any], *, client: UERemoteHTTP | None = None) -> dict[str, Any]:
    """真在 UE 里摆场景、建序列、排渲染。V1 关闭。"""
    config.require("ue_enabled", "Unreal Engine 执行")
    cfg = config.load("ue")
    p = plan(protocol, baked, cfg)
    rc = cfg.get("remote_control") or {}
    own = client is None
    client = client or UERemoteHTTP(rc.get("http") or "http://127.0.0.1:30010", timeout=float(rc.get("timeout_sec") or 30))
    try:
        info = client.info()
        results = {name: client.run_python(src) for name, src in p["scripts"].items()}
    finally:
        if own:
            client.close()
    return {"ue": info, "results": results, "stats": p["stats"]}
