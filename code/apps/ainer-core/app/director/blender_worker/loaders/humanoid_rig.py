"""标准人形骨架（Mixamo 骨骼命名，Rigify/Mixamo 动作可直接重定向）+ 刚性蒙皮的胶囊体网格。

角色在骨架空间面朝 -Y、左侧 +X、Z 向上；身高 H 缩放全部比例，体型（build）缩放肩宽与躯干粗细。
网格按骨骼父子绑定（parent_type=BONE），骨骼一转网格就跟着转 —— 白模控制只需要体块正确，不需要软蒙皮。
"""
from __future__ import annotations

import math

import bmesh
import bpy
from mathutils import Euler, Matrix, Quaternion, Vector

PREFIX = "mixamorig:"
WIDTH = {"slim": 0.9, "lanky": 0.88, "average": 1.0, "stout": 1.32}


def _layout(H: float, build: str):
    k = WIDTH.get(build, 1.0)
    sx = 0.105 * H * (0.92 + 0.08 * k) * (1.08 if build == "stout" else 1.0)
    hx = 0.055 * H * k
    # name: (head, tail, parent, radius)
    J = {
        "Hips": ((0, 0, 0.53 * H), (0, 0, 0.58 * H), None, 0.10 * H * k),
        "Spine": ((0, 0, 0.58 * H), (0, 0, 0.64 * H), "Hips", 0.095 * H * k),
        "Spine1": ((0, 0, 0.64 * H), (0, 0, 0.70 * H), "Spine", 0.10 * H * k),
        "Spine2": ((0, 0, 0.70 * H), (0, 0, 0.80 * H), "Spine1", 0.105 * H * k),
        "Neck": ((0, 0, 0.80 * H), (0, 0, 0.85 * H), "Spine2", 0.03 * H),
        "Head": ((0, 0, 0.85 * H), (0, 0, 1.0 * H), "Neck", 0.062 * H),
    }
    for side, s in (("Left", 1), ("Right", -1)):
        J[f"{side}Shoulder"] = ((s * 0.02 * H, 0, 0.79 * H), (s * sx, 0, 0.79 * H), "Spine2", 0.03 * H * k)
        J[f"{side}Arm"] = ((s * sx, 0, 0.79 * H), (s * (sx + 0.01 * H), 0, 0.61 * H), f"{side}Shoulder", 0.034 * H * k)
        J[f"{side}ForeArm"] = ((s * (sx + 0.01 * H), 0, 0.61 * H), (s * (sx + 0.015 * H), 0, 0.46 * H), f"{side}Arm", 0.028 * H * k)
        J[f"{side}Hand"] = ((s * (sx + 0.015 * H), 0, 0.46 * H), (s * (sx + 0.018 * H), 0, 0.39 * H), f"{side}ForeArm", 0.024 * H)
        J[f"{side}UpLeg"] = ((s * hx, 0, 0.52 * H), (s * hx, 0, 0.285 * H), "Hips", 0.05 * H * k)
        J[f"{side}Leg"] = ((s * hx, 0, 0.285 * H), (s * hx, 0.0, 0.05 * H), f"{side}UpLeg", 0.038 * H * k)
        J[f"{side}Foot"] = ((s * hx, 0.0, 0.05 * H), (s * hx, -0.08 * H, 0.015 * H), f"{side}Leg", 0.03 * H)
    return J


def _capsule(name: str, a: Vector, b: Vector, r: float) -> bpy.types.Mesh:
    bm = bmesh.new()
    L = max(1e-3, (b - a).length)
    bmesh.ops.create_cone(bm, cap_ends=True, segments=12, radius1=r, radius2=r * 0.92, depth=L)
    for c in (Vector((0, 0, -L / 2)), Vector((0, 0, L / 2))):
        g = bmesh.ops.create_uvsphere(bm, u_segments=12, v_segments=8, radius=r)
        bmesh.ops.translate(bm, verts=g["verts"], vec=c)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return me


def build(name: str, height: float, build_kind: str, color, coll) -> dict:
    J = _layout(height, build_kind)
    arm = bpy.data.armatures.new(f"{name}_rig")
    ob = bpy.data.objects.new(name, arm)
    coll.objects.link(ob)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.mode_set(mode="EDIT")
    for bname, (h, t, parent, _r) in J.items():
        eb = arm.edit_bones.new(PREFIX + bname)
        eb.head, eb.tail = Vector(h), Vector(t)
        eb.align_roll(Vector((0, -1, 0)))
        if parent:
            eb.parent = arm.edit_bones[PREFIX + parent]
            eb.use_connect = False
    bpy.ops.object.mode_set(mode="OBJECT")
    rest = {b.name[len(PREFIX):]: b.matrix_local.to_quaternion() for b in arm.bones}
    meshes = []
    col = tuple(color) + (1.0,)
    for bname, (h, t, _p, r) in J.items():
        a, b = Vector(h), Vector(t)
        if bname == "Head":
            bm = bmesh.new()
            bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=10, radius=r)
            bmesh.ops.scale(bm, vec=(0.9, 1.0, 1.15), verts=bm.verts)
            me = bpy.data.meshes.new(f"{name}_Head")
            bm.to_mesh(me)
            bm.free()
            # 鼻尖小凸起：让白模看得出朝向
            mo = bpy.data.objects.new(f"{name}_Head", me)
            center = (a + b) / 2
        else:
            me = _capsule(f"{name}_{bname}", a, b, r)
            mo = bpy.data.objects.new(f"{name}_{bname}", me)
            center = (a + b) / 2
        coll.objects.link(mo)
        d = (b - a).normalized()
        rot = d.to_track_quat("Z", "Y") if bname != "Head" else Quaternion()
        mo.color = col
        mo.parent = ob
        mo.parent_type = "BONE"
        mo.parent_bone = PREFIX + bname
        bpy.context.view_layer.update()
        mo.matrix_world = Matrix.Translation(center) @ rot.to_matrix().to_4x4()
        meshes.append(mo)
    # 鼻子
    hj = J["Head"]
    nb = bmesh.new()
    bmesh.ops.create_cone(nb, cap_ends=True, segments=8, radius1=0.018 * height, radius2=0.004, depth=0.05 * height)
    nme = bpy.data.meshes.new(f"{name}_nose")
    nb.to_mesh(nme)
    nb.free()
    no = bpy.data.objects.new(f"{name}_nose", nme)
    coll.objects.link(no)
    no.color = col
    no.parent, no.parent_type, no.parent_bone = ob, "BONE", PREFIX + "Head"
    bpy.context.view_layer.update()
    hc = (Vector(hj[0]) + Vector(hj[1])) / 2
    no.matrix_world = Matrix.Translation(hc + Vector((0, -0.065 * height, -0.005 * height))) @ \
        Vector((0, -1, 0)).to_track_quat("Z", "Y").to_matrix().to_4x4()
    meshes.append(no)
    for pb in ob.pose.bones:
        pb.rotation_mode = "QUATERNION"
    return {"obj": ob, "rest": rest, "meshes": meshes, "height": height}


def apply_pose(rig: dict, bones: dict, hips_dz: float):
    """D（骨架静止空间的欧拉角，度，ZYX）→ 骨骼局部四元数 q = R_rest⁻¹·D·R_rest。"""
    ob = rig["obj"]
    for pb in ob.pose.bones:
        key = pb.name[len(PREFIX):]
        v = bones.get(key)
        if v:
            D = Euler((math.radians(v[0]), math.radians(v[1]), math.radians(v[2])), "XYZ").to_quaternion()
            R = rig["rest"][key]
            pb.rotation_quaternion = R.inverted() @ D @ R
        else:
            pb.rotation_quaternion = Quaternion()
    hips = ob.pose.bones[PREFIX + "Hips"]
    # 位移在骨骼局部：Hips 骨骼沿 +Z 世界朝上，局部 Y 即世界 Z
    hips.location = rig["rest"]["Hips"].inverted() @ Vector((0, 0, hips_dz))


KEYPOINTS = ["nose", "neck", "r_sh", "r_el", "r_wr", "l_sh", "l_el", "l_wr", "r_hip", "r_kn", "r_an",
             "l_hip", "l_kn", "l_an", "r_eye", "l_eye", "r_ear", "l_ear"]


def keypoints(rig: dict) -> list[Vector]:
    """OpenPose COCO-18 关键点（世界坐标），取自姿态骨骼的头尾。"""
    ob = rig["obj"]
    mw = ob.matrix_world
    P = lambda n, tail=False: mw @ (ob.pose.bones[PREFIX + n].tail if tail else ob.pose.bones[PREFIX + n].head)  # noqa: E731
    head_h, head_t = P("Head"), P("Head", True)
    hm = ob.pose.bones[PREFIX + "Head"].matrix
    fwd = (mw.to_3x3() @ hm.to_3x3() @ (rig["rest"]["Head"].inverted() @ Vector((0, -1, 0)))).normalized()
    left = (mw.to_3x3() @ hm.to_3x3() @ (rig["rest"]["Head"].inverted() @ Vector((1, 0, 0)))).normalized()
    hc = head_h.lerp(head_t, 0.45)
    H = rig["height"]
    nose = hc + fwd * 0.07 * H
    eye = hc + fwd * 0.055 * H + (head_t - head_h).normalized() * 0.02 * H
    return [nose, P("Neck"), P("RightArm"), P("RightForeArm"), P("RightHand"), P("LeftArm"), P("LeftForeArm"),
            P("LeftHand"), P("RightUpLeg"), P("RightLeg"), P("RightFoot"), P("LeftUpLeg"), P("LeftLeg"),
            P("LeftFoot"), eye - left * 0.02 * H, eye + left * 0.02 * H, hc - left * 0.06 * H, hc + left * 0.06 * H]
