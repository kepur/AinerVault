"""外部资产：图片板贴图（V1），以及以后换真模型用的 glTF / FBX 导入。

V1 的人和物都是程序化白模（部件表），不需要外部文件；图片板会把贴图读进来。
asset_registry（job.json 里的 assets 映射：model_ref → 本地文件）留好了口子：
以后给某个角色配上绑好骨骼的 glTF，actor_builder 就改用它，而不是人偶。
"""
from __future__ import annotations

import os

import bpy


def local_media(url: str | None, media_root: str | None) -> str | None:
    """/media/xxx.png 或 http://…/media/xxx.png → 媒体目录里的本地文件；找不到返回 None。"""
    if not url or not media_root:
        return None
    i = url.find("/media/")
    if i < 0:
        return None
    path = os.path.join(media_root, os.path.basename(url[i + len("/media/"):]))
    return path if os.path.exists(path) else None


def image_material(path: str) -> bpy.types.Material:
    img = bpy.data.images.load(path, check_existing=True)
    m = bpy.data.materials.new(f"board {os.path.basename(path)}")
    m.use_nodes = True
    nt = m.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Emission Color"])
    bsdf.inputs["Emission Strength"].default_value = 0.6
    return m


def board_face(name: str, width: float, height: float, path: str, parent, coll):
    """图片板正面的贴图面：与 SceneRender 的 BoardImage 同样的位置（离板面 3.5cm）。"""
    from ..common import new_object
    w, h = width * 0.96, height * 0.96
    me = bpy.data.meshes.new(name)
    y0 = height / 2 - h / 2
    me.from_pydata([(-w / 2, y0, 0.035), (w / 2, y0, 0.035), (w / 2, y0 + h, 0.035), (-w / 2, y0 + h, 0.035)], [], [(0, 1, 2, 3)])
    uv = me.uv_layers.new()
    for i, co in enumerate(((0, 0), (1, 0), (1, 1), (0, 1))):
        uv.data[i].uv = co
    me.materials.append(image_material(path))
    return new_object(name, me, parent, coll)


def import_model(path: str) -> list[bpy.types.Object]:
    """导入 glTF / FBX，返回新加的物体。V1 不启用（没有资产映射时不会调到）。"""
    before = set(bpy.data.objects)
    ext = os.path.splitext(path)[1].lower()
    if ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    else:
        raise ValueError(f"不支持的模型格式：{ext}")
    return [o for o in bpy.data.objects if o not in before]
