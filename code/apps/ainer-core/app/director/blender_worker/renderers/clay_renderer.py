"""白模：Workbench 单色＋棚拍光＋凹凸描边（cavity）。体块、轮廓最干净，适合看构图和做重绘底。"""
from __future__ import annotations

from .sequence import render_sequence, set_view


def render(scene, out_dir: str, frames: int) -> str:
    scene.render.engine = "BLENDER_WORKBENCH"
    sh = scene.display.shading
    sh.light = "STUDIO"
    sh.color_type = "SINGLE"
    sh.single_color = (0.78, 0.78, 0.8)
    sh.show_cavity = True
    try:
        sh.cavity_type = "BOTH"
    except TypeError:
        pass
    sh.show_shadows = True
    sh.shadow_intensity = 0.45
    scene.display.render_aa = "8"
    old = tuple(scene.world.color)
    scene.world.color = (0.16, 0.16, 0.17)
    scene.view_layers[0].material_override = None
    set_view(scene, "Standard")
    try:
        return render_sequence(scene, out_dir, "clay", frames)
    finally:
        scene.world.color = old
