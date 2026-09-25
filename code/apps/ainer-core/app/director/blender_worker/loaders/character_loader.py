"""人偶：与 3D-BOX 的 Mannequin.tsx 一模一样的层级与尺寸。

层级（每个关节一个空物体，网格挂在关节下）：
  角色 → move（动作位移、转身）→ root（躺、倒地）→ pelvis
      pelvis → lHip → lKn、rHip → rKn
      pelvis → spine → head、spine → lSh → lEl、spine → rSh → rEl
尺寸、关节位置来自烘焙数据（rig.ts 的 mannequinDims / rigLayout），这里不再自己算。
OpenPose 关键点做成挂在关节下的小空物体，渲姿态图时读它们的世界坐标。
"""
from __future__ import annotations

import math

import bmesh
import bpy
from mathutils import Matrix

from ..common import material, new_object, unit_part


def _mesh(name: str, prim: str, size, pos, color: str, rot=None, segments: int = 12):
    bm = bmesh.new()
    unit_part(bm, prim, segments, None)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    m = Matrix.Translation(pos)
    if rot:
        m = m @ Matrix.Rotation(math.radians(rot[0]), 4, "X")
    m = m @ Matrix.Diagonal((size[0], size[1], size[2], 1))
    bmesh.ops.transform(bm, matrix=m, verts=bm.verts)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(material(color))
    return me


def _limb(name: str, length: float, w: float, color: str, parent, coll):
    """three 的 capsuleGeometry(w, len-2w)：从关节往下挂，中心在 -len/2。"""
    me = _mesh(name, "capsule", (w * 4, length, w * 4), (0, -length / 2, 0), color)
    # 单位胶囊半径 0.25：横向放大 4w 得到半径 w；纵向总长 = length
    return new_object(name, me, parent, coll)


def build_mannequin(cid: str, ch: dict, parent, coll) -> dict:
    """返回 {joint 名: 空物体} ＋ 关键点空物体列表。"""
    d = ch["dims"]
    lay = ch["layout"]
    color, jcolor, ncolor = ch.get("color") or "#bcc0c8", ch.get("joint") or "#9aa0aa", ch.get("nose") or "#ffb86b"

    def joint(name: str, par, pos=(0, 0, 0)):
        ob = new_object(f"{cid}.{name}", None, par, coll)
        ob.empty_display_size = 0.05
        ob.location = pos
        return ob

    bones: dict[str, bpy.types.Object] = {}
    bones["move"] = joint("move", parent)
    bones["root"] = joint("root", bones["move"])
    bones["pelvis"] = joint("pelvis", bones["root"], (0, d["leg"], 0))
    for name in ("lHip", "rHip", "spine", "lKn", "rKn", "head", "lSh", "rSh", "lEl", "rEl"):
        spec = lay[name]
        bones[name] = joint(name, bones[spec["parent"]], tuple(spec["pos"]))

    limb = d["limb"]
    # 盆骨
    new_object(f"{cid}.pelvis_mesh", _mesh(f"{cid}.pelvis_mesh", "box", (d["hip"] * 2 + limb * 2, limb * 2.2, limb * 2.4), (0, 0, 0), jcolor),
               bones["pelvis"], coll)
    # 腿
    for hip, knee in (("lHip", "lKn"), ("rHip", "rKn")):
        _limb(f"{cid}.{hip}_mesh", d["leg"] * 0.5, limb * 1.1, color, bones[hip], coll)
        _limb(f"{cid}.{knee}_mesh", d["leg"] * 0.5, limb, color, bones[knee], coll)
        new_object(f"{cid}.{knee}_foot", _mesh(f"{cid}.{knee}_foot", "box", (limb * 1.8, 0.06, limb * 4), (0, -d["leg"] * 0.5 + 0.03, 0.05), jcolor),
                   bones[knee], coll)
    # 躯干、头、鼻尖
    new_object(f"{cid}.torso", _mesh(f"{cid}.torso", "box", (d["chest"], d["torso"], d["chest"] * 0.55), (0, d["torso"] / 2, 0), color),
               bones["spine"], coll)
    h = d["head"]
    new_object(f"{cid}.head_mesh", _mesh(f"{cid}.head_mesh", "sphere", (h * 2, h * 2, h * 2), (0, h, 0), color, segments=16),
               bones["head"], coll)
    new_object(f"{cid}.nose", _mesh(f"{cid}.nose", "cone", (h * 0.44, h * 0.5, h * 0.44), (0, h, h * 0.95), ncolor, rot=(90, 0, 0), segments=8),
               bones["head"], coll)
    # 手臂
    for sh, el in (("lSh", "lEl"), ("rSh", "rEl")):
        _limb(f"{cid}.{sh}_mesh", d["upperArm"], limb * 0.9, color, bones[sh], coll)
        _limb(f"{cid}.{el}_mesh", d["foreArm"], limb * 0.8, color, bones[el], coll)

    kps = []
    for k in ch["keypoints"]:          # 烘焙数据（我们自己算的），每个人偶都带 18 个
        e = joint(f"kp.{k['name']}", bones[k["joint"]], tuple(k["pos"]))
        e.empty_display_size = 0.02
        kps.append(e)
    return {"bones": bones, "keypoints": kps}
