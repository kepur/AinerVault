"""边缘图：对预演（没有就白模）逐帧做 Canny。ffmpeg 的 edgedetect 就是 Canny（高斯平滑、梯度、非极大抑制、双阈值）。"""
from __future__ import annotations

import os
import subprocess

from .sequence import emit, frames_dir


def render(ffmpeg: str, out_dir: str, source: str, frames: int, low: float = 0.08, high: float = 0.22) -> str:
    d = frames_dir(out_dir, "canny")
    src = os.path.join(out_dir, "frames", source, "%04d.png")
    subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", src,
                    "-vf", f"edgedetect=low={low}:high={high},format=rgb24", "-start_number", "1",
                    os.path.join(d, "%04d.png")],
                   check=True, stdin=subprocess.DEVNULL, capture_output=True, timeout=900)
    emit("PROGRESS", **{"pass": "canny", "frame": frames, "total": frames})
    return d
