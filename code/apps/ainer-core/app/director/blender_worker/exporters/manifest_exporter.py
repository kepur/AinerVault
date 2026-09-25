"""manifest.json：这次任务产出了什么、在哪。ainer-core 按它把文件登记成资产。"""
from __future__ import annotations

import json
import os


def write(out_dir: str, job: dict, baked: dict, outputs: dict[str, str], timings: dict[str, float]) -> str:
    rel = {k: os.path.relpath(v, out_dir) for k, v in outputs.items() if v and os.path.exists(v)}
    doc = {
        "job_id": job.get("job_id"), "scene_id": job.get("scene_id"),
        "fps": baked["fps"], "frames": baked["frames"], "duration_sec": baked["duration"],
        "resolution": job.get("resolution"), "passes": job.get("passes"),
        "outputs": rel, "timings_sec": {k: round(v, 2) for k, v in timings.items()},
        "blender": job.get("blender_version"),
    }
    path = os.path.join(out_dir, "manifest.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    return path
