"""深度：近白远黑的视差图（1/z 线性映射到 near–far），和 Depth Anything / DepthCrafter 的输出同一种形态 ——
视频模型的深度控制是拿那种图训练的。

做法：整层材质替换成一个自发光材质，亮度 = f(相机空间深度)；背景纯黑；色彩变换用 Raw，
自发光值原样写进 PNG。near/far 按整段镜头里机位到物体的距离定，全片固定（逐帧归一化会闪）。
"""
from __future__ import annotations

import bpy

from .sequence import render_sequence, set_view


def _material(near: float, far: float) -> bpy.types.Material:
    m = bpy.data.materials.new("ainer depth")
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    cam = nt.nodes.new("ShaderNodeCameraData")

    def math(op: str, a, b, clamp: bool = False):
        n = nt.nodes.new("ShaderNodeMath")
        n.operation = op
        n.use_clamp = clamp
        for i, v in enumerate((a, b)):
            if isinstance(v, (int, float)):
                n.inputs[i].default_value = float(v)
            else:
                nt.links.new(v, n.inputs[i])
        return n.outputs[0]

    z = math("MAXIMUM", cam.outputs["View Z Depth"], 1e-3)
    inv = math("DIVIDE", 1.0, z)
    span = (1.0 / near) - (1.0 / far)
    v = math("MULTIPLY", math("SUBTRACT", inv, 1.0 / far), 1.0 / span, clamp=True)
    em = nt.nodes.new("ShaderNodeEmission")
    nt.links.new(v, em.inputs["Color"])
    em.inputs["Strength"].default_value = 1.0
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
    return m


def render(scene, out_dir: str, frames: int, near: float, far: float) -> str:
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 4
    vl = scene.view_layers[0]
    vl.material_override = _material(near, far)
    bg = scene.world.node_tree.nodes.get("Background")
    old = (tuple(bg.inputs["Color"].default_value), bg.inputs["Strength"].default_value)
    bg.inputs["Color"].default_value = (0, 0, 0, 1)
    bg.inputs["Strength"].default_value = 0.0
    set_view(scene, "Raw")
    try:
        return render_sequence(scene, out_dir, "depth", frames)
    finally:
        vl.material_override = None
        bg.inputs["Color"].default_value, bg.inputs["Strength"].default_value = old
        set_view(scene, "Standard")
