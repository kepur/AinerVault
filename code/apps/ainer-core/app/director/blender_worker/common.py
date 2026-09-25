"""Blender 侧的公共小工具：坐标、欧拉角、颜色、材质、基本体网格。

坐标约定（与 3D-BOX 相同，见 ainer-studio/src/scene/bake.ts）：
  烘焙数据是 Y 向上、米、右手系，欧拉角是度、XYZ 次序（three 默认，矩阵 = Rx·Ry·Rz）。
  Blender 是 Z 向上。我们不逐个换算：所有东西挂在一个绕 X 轴转 +90° 的根节点 AINER_ROOT 下，
  根节点里面沿用 Y 向上的坐标 —— (x, y, z)ᵧ ↦ (x, -z, y)Blender。
  three 的 XYZ 欧拉（Rx·Ry·Rz）对应 Blender 的 'ZYX' 旋转模式（矩阵同为 Rx·Ry·Rz）。
  相机和灯都看向局部 -Z、上方局部 +Y，两边一样，所以机位朝向在根节点里直接按 lookAt 算。
"""
from __future__ import annotations

import math

import bmesh
import bpy
from mathutils import Matrix, Vector

ROOT_NAME = "AINER_ROOT"


def rad3(v) -> tuple[float, float, float]:
    return (math.radians(v[0]), math.radians(v[1]), math.radians(v[2]))


def hex_rgb(h: str, linear: bool = True) -> tuple[float, float, float]:
    """#rrggbb → 0–1。linear=True 按 sRGB 解码成线性（Blender 材质颜色是线性的）。"""
    h = (h or "#cccccc").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    if not linear:
        return (c[0], c[1], c[2])

    def lin(x: float) -> float:
        return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4
    return (lin(c[0]), lin(c[1]), lin(c[2]))


def empty_scene() -> bpy.types.Scene:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    return bpy.context.scene


def make_root(scene: bpy.types.Scene) -> bpy.types.Object:
    root = bpy.data.objects.new(ROOT_NAME, None)
    root.rotation_euler = (math.radians(90), 0, 0)
    scene.collection.objects.link(root)
    return root


def new_object(name: str, data, parent: bpy.types.Object | None, collection) -> bpy.types.Object:
    ob = bpy.data.objects.new(name, data)
    collection.objects.link(ob)
    if parent is not None:
        ob.parent = parent
        ob.matrix_parent_inverse = Matrix.Identity(4)
    ob.rotation_mode = "ZYX"
    return ob


def set_trs(ob: bpy.types.Object, pos, rot_deg, scale=(1, 1, 1)) -> None:
    ob.location = pos
    ob.rotation_euler = rad3(rot_deg)
    ob.scale = scale


def look_rotation(pos, look, roll_deg: float = 0.0):
    """Y 向上空间里的 lookAt：局部 -Z 指向 look、局部 +Y 尽量朝上，再绕视线滚转 roll（度）。"""
    p, t = Vector(pos), Vector(look)
    z = p - t
    if z.length < 1e-8:
        z = Vector((0, 0, 1))
    z.normalize()
    up = Vector((0, 1, 0))
    if abs(z.dot(up)) > 0.999:           # 正上正下看：换个参考上方
        up = Vector((0, 0, -1))
    x = up.cross(z)
    x.normalize()
    y = z.cross(x)
    m = Matrix((x, y, z)).transposed()
    if roll_deg:
        m = m @ Matrix.Rotation(math.radians(roll_deg), 3, "Z")
    return m.to_quaternion()


# ── 材质 ────────────────────────────────────────────────

_MATS: dict[str, bpy.types.Material] = {}


def material(color: str, glow: bool = False, opacity: float = 1.0) -> bpy.types.Material:
    key = f"{color}|{int(glow)}|{opacity:.2f}"
    m = _MATS.get(key)
    if m is not None:
        return m
    m = bpy.data.materials.new(f"ainer {key}")
    m.use_nodes = True
    nt = m.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    rgb = hex_rgb(color)
    bsdf.inputs["Base Color"].default_value = (*rgb, 1)
    bsdf.inputs["Roughness"].default_value = 0.86
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = 0.2
    if glow:
        bsdf.inputs["Emission Color"].default_value = (*rgb, 1)
        bsdf.inputs["Emission Strength"].default_value = 2.0
    if opacity < 1:
        bsdf.inputs["Alpha"].default_value = opacity
    m.diffuse_color = (*rgb, 1)          # Workbench 的「材质色」模式读这个
    _MATS[key] = m
    return m


# ── 基本体：与 ainer-studio/src/box/geom.ts 的单位几何体一一对应 ───────────

def _ring(bm, n: int, a0: float, al: float, y: float, r: float) -> list:
    closed = al >= 2 * math.pi - 1e-6
    count = n if closed else n + 1
    return [bm.verts.new((r * math.sin(a0 + al * i / n), y, r * math.cos(a0 + al * i / n))) for i in range(count)]


def _tube(bm, bottom: list, top: list, closed: bool) -> None:
    n = len(bottom)
    for i in range(n if closed else n - 1):
        j = (i + 1) % n
        bm.faces.new((bottom[i], bottom[j], top[j], top[i]))


def _cap(bm, ring: list, flip: bool) -> None:
    if len(ring) >= 3:
        bm.faces.new(list(reversed(ring)) if flip else ring)


def unit_part(bm, prim: str, segments: int | None, arc: tuple[float, float] | None, torus_ratio: float = 0.2) -> None:
    """往 bm 里加一个单位基本体（尺寸 1、中心在原点、Y 向上），由调用方再缩放、旋转、平移。"""
    seg = int(segments or 12)
    a0, al = (math.radians(arc[0]), math.radians(arc[1])) if arc else (0.0, 2 * math.pi)
    closed = al >= 2 * math.pi - 1e-6
    if prim in ("box", "plane"):
        bmesh.ops.create_cube(bm, size=1.0)
    elif prim == "sphere":
        bmesh.ops.create_uvsphere(bm, u_segments=max(5, seg), v_segments=max(4, round(seg * 0.7)), radius=0.5)
    elif prim in ("cylinder", "cone"):
        n = max(3, seg)
        bottom = _ring(bm, n, a0, al, -0.5, 0.5)
        if prim == "cylinder":
            top = _ring(bm, n, a0, al, 0.5, 0.5)
            _tube(bm, bottom, top, closed)
            if closed:
                _cap(bm, top, False)
                _cap(bm, bottom, True)
        else:
            apex = bm.verts.new((0, 0.5, 0))
            m = len(bottom)
            for i in range(m if closed else m - 1):
                bm.faces.new((bottom[i], bottom[(i + 1) % m], apex))
            if closed:
                _cap(bm, bottom, True)
    elif prim == "capsule":
        # three 的 CapsuleGeometry(0.25, 0.5)：半径 0.25、中段 0.5，总高 1
        ret = bmesh.ops.create_uvsphere(bm, u_segments=max(6, seg), v_segments=8, radius=0.25)
        for v in ret["verts"]:
            v.co.z += 0.25 if v.co.z > 1e-6 else (-0.25 if v.co.z < -1e-6 else 0)
        bmesh.ops.rotate(bm, verts=ret["verts"], cent=(0, 0, 0), matrix=Matrix.Rotation(math.radians(-90), 3, "X"))
    elif prim == "prism":
        vs = [bm.verts.new(p) for p in ((-0.5, -0.5, -0.5), (0.5, -0.5, -0.5), (0, 0.5, -0.5),
                                        (-0.5, -0.5, 0.5), (0.5, -0.5, 0.5), (0, 0.5, 0.5))]
        for f in ((0, 2, 1), (3, 4, 5), (0, 1, 4, 3), (1, 2, 5, 4), (2, 0, 3, 5)):
            bm.faces.new([vs[i] for i in f])
    elif prim == "torus":
        # 圆环在 XY 面（绕 Z），直径 1，管径按比例
        R, r = 0.5, 0.5 * torus_ratio
        nu, nv = max(8, seg), 8
        tclosed = closed
        cols = nu if tclosed else nu + 1
        grid = []
        for i in range(cols):
            u = a0 + al * i / nu if not tclosed else al * i / nu
            ring = []
            for j in range(nv):
                v = 2 * math.pi * j / nv
                ring.append(bm.verts.new(((R + r * math.cos(v)) * math.cos(u), (R + r * math.cos(v)) * math.sin(u), r * math.sin(v))))
            grid.append(ring)
        for i in range(cols if tclosed else cols - 1):
            a, b = grid[i], grid[(i + 1) % cols]
            for j in range(nv):
                k = (j + 1) % nv
                bm.faces.new((a[j], b[j], b[k], a[k]))
    else:
        bmesh.ops.create_cube(bm, size=1.0)


def part_scale(p: dict) -> tuple[float, float, float]:
    s = p["size"]
    if p["prim"] == "torus":
        return (s[0], s[0], s[0])
    return (s[0], s[1], s[2])


def parts_mesh(name: str, parts: list[dict]) -> bpy.types.Mesh:
    """一个物体的全部部件合成一个网格；每个颜色一个材质槽。"""
    bm = bmesh.new()
    slots: list[str] = []
    slot_of: dict[str, int] = {}
    for p in parts:
        before = set(bm.faces)
        tmp = bmesh.new()
        ratio = (p["size"][1] / p["size"][0]) if p["prim"] == "torus" and p["size"][0] else 0.2
        unit_part(tmp, p["prim"], p.get("segments"), tuple(p["arc"]) if p.get("arc") else None, ratio)
        sx, sy, sz = part_scale(p)
        rot = p.get("rot") or (0, 0, 0)
        m = (Matrix.Translation(Vector(p["pos"]))
             @ Matrix.Rotation(math.radians(rot[0]), 4, "X") @ Matrix.Rotation(math.radians(rot[1]), 4, "Y")
             @ Matrix.Rotation(math.radians(rot[2]), 4, "Z")
             @ Matrix.Diagonal((sx, sy, sz, 1)))
        bmesh.ops.recalc_face_normals(tmp, faces=tmp.faces)
        bmesh.ops.transform(tmp, matrix=m, verts=tmp.verts)
        key =f"{p.get('color') or '#dfe3e8'}|{int(bool(p.get('glow')))}|{float(p.get('opacity') or 1):.2f}"
        if key not in slot_of:
            slot_of[key] = len(slots)
            slots.append(key)
        tmp_mesh = bpy.data.meshes.new("tmp")
        tmp.to_mesh(tmp_mesh)
        tmp.free()
        bm.from_mesh(tmp_mesh)
        bpy.data.meshes.remove(tmp_mesh)
        for f in set(bm.faces) - before:
            f.material_index = slot_of[key]
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    for key in slots:
        color, glow, opacity = key.split("|")
        me.materials.append(material(color, glow == "1", float(opacity)))
    return me


def strip_mesh(name: str, points: list, width: float, y: float) -> bpy.types.Mesh:
    """沿折线的带子（道路、河）：与 geom.ts 的 stripGeometry 同一算法。"""
    verts, faces = [], []
    n = len(points)
    for i, p in enumerate(points):
        prev, nxt = points[max(0, i - 1)], points[min(n - 1, i + 1)]
        dx, dz = nxt[0] - prev[0], nxt[1] - prev[1]
        ll = math.hypot(dx, dz) or 1
        dx, dz = dx / ll, dz / ll
        nx, nz = -dz, dx
        verts.append((p[0] + nx * width / 2, y, p[1] + nz * width / 2))
        verts.append((p[0] - nx * width / 2, y, p[1] - nz * width / 2))
        if i < n - 1:
            k = i * 2
            faces.append((k, k + 2, k + 3, k + 1))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    return me
