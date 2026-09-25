"""逐帧渲染一个通道到 PNG 序列，进度打到 stdout（ainer-core 靠它判断是不是卡死了）。"""
from __future__ import annotations

import json
import os
import subprocess

import bpy


def emit(kind: str, **kw) -> None:
    """AINER_PROGRESS / AINER_STAGE / AINER_DONE / AINER_ERROR + JSON，一行一条。"""
    print(f"AINER_{kind} " + json.dumps(kw, ensure_ascii=False), flush=True)


def frames_dir(out_dir: str, name: str) -> str:
    d = os.path.join(out_dir, "frames", name)
    os.makedirs(d, exist_ok=True)
    return d


def render_sequence(scene: bpy.types.Scene, out_dir: str, name: str, frames: int) -> str:
    d = frames_dir(out_dir, name)
    st = scene.render.image_settings
    if hasattr(st, "media_type"):
        st.media_type = "IMAGE"
    st.file_format = "PNG"
    st.color_mode = "RGB"
    st.color_depth = "8"
    scene.render.filepath = os.path.join(d, "####")
    scene.render.use_file_extension = True
    scene.frame_start, scene.frame_end = 1, frames

    def on_write(sc, *_):
        emit("PROGRESS", **{"pass": name, "frame": sc.frame_current, "total": frames})
    bpy.app.handlers.render_write.append(on_write)
    try:
        bpy.ops.render.render(animation=True)
    finally:
        bpy.app.handlers.render_write.remove(on_write)
    return d


def set_view(scene: bpy.types.Scene, transform: str) -> None:
    try:
        scene.view_settings.view_transform = transform
        scene.view_settings.look = "None"
    except TypeError:
        pass
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0


def encode(ffmpeg: str, src_dir: str, dst: str, fps: int, crf: int = 16) -> str:
    """PNG 序列 → H.264 mp4（yuv420p，各家播放器、视频模型都认）。"""
    subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-framerate", str(fps),
                    "-i", os.path.join(src_dir, "%04d.png"), "-c:v", "libx264", "-preset", "medium",
                    "-crf", str(crf), "-pix_fmt", "yuv420p", "-movflags", "+faststart", dst],
                   check=True, stdin=subprocess.DEVNULL, capture_output=True, timeout=900)
    return dst
