"""人物色块：每个人一个编号，Workbench 按物体填纯色（亮度 = 编号 × STEP），其余物体和背景全黑。

两个用途：
  1. **谁真的露在画面里。** 只看骨架投影算不出遮挡 —— 坏蛋第 1 镜实跑，骨架说瘦男孩和一个染发少年都在取景框里，
     渲出来的预演却只有一面墙：LLM 把楼和柜子摆在了机位和人之间。数色块像素才知道
  2. **每个人在首帧里的精确轮廓**：分区身份出成片首帧时，每人只在自己的区域里画自己的脸

平光、关抗锯齿、Raw 视图：像素值原样落盘，边缘不会混出别人的编号；解码时就近取整。
"""
from __future__ import annotations

import os

import bpy
import numpy as np

from .sequence import set_view

STEP = 8                     # 编号之间差 8/255：最多 30 个人，JPEG 之类的压缩也分得开（这里存 PNG，本来就无损）


def assign(actors: dict[str, dict]) -> dict[str, int]:
    """给每个人（连同他人偶的所有部件）编号，其余物体归 0。返回 {actor_id: 编号}。"""
    ids: dict[str, int] = {}
    for ob in bpy.data.objects:
        ob.color = (0.0, 0.0, 0.0, 1.0)
    for i, (aid, a) in enumerate(actors.items(), 1):
        ids[aid] = i
        v = i * STEP / 255.0
        root = a["obj"]
        for ob in (root, *root.children_recursive):
            ob.color = (v, v, v, 1.0)
    return ids


class IdMaskView:
    """进入：Workbench 平光按物体色、黑背景、关抗锯齿、Raw；退出时原样还回去（后面还要渲别的通道）。"""

    def __init__(self, scene):
        self.scene = scene

    def __enter__(self):
        sc = self.scene
        sh = sc.display.shading
        self.saved = {
            "engine": sc.render.engine, "light": sh.light, "color_type": sh.color_type,
            "cavity": sh.show_cavity, "shadows": sh.show_shadows, "aa": sc.display.render_aa,
            "world": tuple(sc.world.color), "outline": getattr(sh, "show_object_outline", False),
            "spec": getattr(sh, "show_specular_highlight", False),
            "view": sc.view_settings.view_transform,
        }
        sc.render.engine = "BLENDER_WORKBENCH"
        sh.light = "FLAT"
        sh.color_type = "OBJECT"
        sh.show_cavity = False
        sh.show_shadows = False
        for attr in ("show_object_outline", "show_specular_highlight", "show_xray"):
            if hasattr(sh, attr):
                setattr(sh, attr, False)
        sc.display.render_aa = "OFF"
        sc.world.color = (0.0, 0.0, 0.0)
        sc.view_layers[0].material_override = None
        set_view(sc, "Raw")
        return self

    def __exit__(self, *exc):
        sc, s = self.scene, self.saved
        sh = sc.display.shading
        sc.render.engine = s["engine"]
        sh.light, sh.color_type = s["light"], s["color_type"]
        sh.show_cavity, sh.show_shadows = s["cavity"], s["shadows"]
        if hasattr(sh, "show_object_outline"):
            sh.show_object_outline = s["outline"]
        if hasattr(sh, "show_specular_highlight"):
            sh.show_specular_highlight = s["spec"]
        sc.display.render_aa = s["aa"]
        sc.world.color = s["world"]
        set_view(sc, s["view"])
        return False


def render_ids(scene, frame: int, path: str, size: tuple[int, int] | None = None) -> np.ndarray:
    """渲一帧色块，返回每个像素的编号（H×W，上到下）。size 给定时临时改分辨率（探测机位用小图）。"""
    r = scene.render
    old = (r.resolution_x, r.resolution_y, r.resolution_percentage, r.filepath)
    if size:
        r.resolution_x, r.resolution_y, r.resolution_percentage = int(size[0]), int(size[1]), 100
    st = r.image_settings
    if hasattr(st, "media_type"):
        st.media_type = "IMAGE"
    st.file_format, st.color_mode, st.color_depth = "PNG", "RGB", "8"
    scene.frame_set(frame)
    r.filepath = path
    try:
        bpy.ops.render.render(write_still=True)
    finally:
        r.resolution_x, r.resolution_y, r.resolution_percentage, r.filepath = old
    img = bpy.data.images.load(path, check_existing=False)
    try:
        w, h = img.size
        px = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, img.channels)[..., 0]
    finally:
        bpy.data.images.remove(img)
    return np.flipud(np.rint(px * 255.0 / STEP).astype(np.int32))


def coverage(idx: np.ndarray, ids: dict[str, int]) -> dict[str, float]:
    """每个人占画面的比例（0–1）。"""
    total = float(idx.size) or 1.0
    counts = np.bincount(idx.ravel(), minlength=max(ids.values(), default=0) + 1)
    return {aid: round(float(counts[i]) / total, 5) for aid, i in ids.items()}


def write_masks(idx: np.ndarray, ids: dict[str, int], out_dir: str) -> dict[str, str]:
    """首帧里每个人的轮廓存成黑底白形 PNG（分区身份用），返回 {actor_id: 路径}；不在画面里的人不写。"""
    os.makedirs(out_dir, exist_ok=True)
    paths: dict[str, str] = {}
    h, w = idx.shape
    for aid, i in ids.items():
        m = idx == i
        if not m.any():
            continue
        img = bpy.data.images.new(f"mask_{aid}", width=w, height=h, alpha=False)
        v = np.flipud(m).astype(np.float32)
        rgba = np.stack([v, v, v, np.ones_like(v)], axis=-1).ravel()
        img.pixels.foreach_set(rgba)
        p = os.path.join(out_dir, f"{aid}.png")
        img.filepath_raw = p
        img.file_format = "PNG"
        img.save()
        bpy.data.images.remove(img)
        paths[aid] = p
    return paths
