"""预演：EEVEE，白模本色＋天光＋太阳阴影。给人看的「成片预览」，也是边缘图的来源。"""
from __future__ import annotations

from .sequence import render_sequence, set_view


def render(scene, out_dir: str, frames: int, samples: int = 16) -> str:
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = samples
    if hasattr(scene.eevee, "use_shadows"):
        scene.eevee.use_shadows = True
    scene.render.film_transparent = False
    scene.view_layers[0].material_override = None
    set_view(scene, "Standard")
    return render_sequence(scene, out_dir, "preview", frames)
