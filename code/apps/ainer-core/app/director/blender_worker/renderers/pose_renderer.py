"""骨架图（OpenPose COCO-18）＋逐帧采样。

一趟逐帧走完整段：读每个人偶关键点空物体的世界坐标，用渲染机位投到画面上（Blender 自己的投影，
与渲出来的画面严格对齐），画成 OpenPose 骨架图；顺带记下机位矩阵、人物位置，给 camera.json / motion.json。
"""
from __future__ import annotations

import os

import bpy
from bpy_extras.object_utils import world_to_camera_view

from ..png import draw_pose, write_png
from .sequence import emit, frames_dir


def to_yup(v) -> list[float]:
    """Blender 世界（Z 向上）→ 场景坐标（Y 向上）：(x, y, z) ↦ (x, z, -y)。"""
    return [round(v[0], 4), round(v[2], 4), round(-v[1], 4)]


def walk(scene, cam, actors: dict[str, dict], frames: int, res: tuple[int, int], out_dir: str | None) -> dict:
    W, H = res
    d = frames_dir(out_dir, "pose") if out_dir else None
    cams, people = [], {aid: [] for aid in actors}
    for f in range(1, frames + 1):
        scene.frame_set(f)
        mw = cam.matrix_world
        cams.append({"matrix_world": [list(map(lambda x: round(x, 5), row)) for row in mw],
                     "lens_mm": round(cam.data.lens, 3)})
        drawn = []
        for aid, a in actors.items():
            kps2, kps3 = [], []
            for e in a["keypoints"]:
                co = e.matrix_world.translation
                v = world_to_camera_view(scene, cam, co)
                ok = v.z > 0 and -0.02 <= v.x <= 1.02 and -0.02 <= v.y <= 1.02
                kps2.append((float(v.x * W), float((1 - v.y) * H), 1.0 if ok else 0.0))
                kps3.append(to_yup(co))
            root = a["bones"]["root"].matrix_world.translation
            people[aid].append({"root": to_yup(root), "keypoints_2d": [[round(x, 1), round(y, 1), c] for x, y, c in kps2],
                                "keypoints_3d": kps3})
            drawn.append(kps2)
        if d:
            write_png(os.path.join(d, f"{f:04d}.png"), draw_pose(W, H, drawn))
            emit("PROGRESS", **{"pass": "pose", "frame": f, "total": frames})
    return {"camera": cams, "actors": people}


def depth_range(scene, cam, objs: dict, actors: dict, frames: int, ground_size: float) -> tuple[float, float]:
    """深度图的 near / far，整段镜头固定（逐帧归一化会闪）。

    near 跟着主体走：人物（没有人就用物体）到机位距离的 5 分位 ×0.7 —— 主体落在亮部，
    比主体更近的（脚下的地面、擦过镜头的前景）截成纯白。near 取死 0.3 米的话，
    5 米外的人只剩 5% 的亮度，整张图几乎全黑（实测）。
    far 取物体距离的 90 分位 ×1.6：远处的墙、地面渐黑。
    """
    near_d, far_d = [], []
    step = max(1, frames // 24)
    for f in range(1, frames + 1, step):
        scene.frame_set(f)
        c = cam.matrix_world.translation
        for a in actors.values():
            near_d.append((a["bones"]["pelvis"].matrix_world.translation - c).length)
        for ob in objs.values():
            if ob.parent is not None and ob.parent.name == "AINER_ROOT":
                far_d.append((ob.matrix_world.translation - c).length)
    near_d = sorted(near_d or far_d)
    far_d = sorted(far_d or near_d)
    if not far_d:
        return 1.0, 60.0
    near = max(0.3, near_d[int(len(near_d) * 0.05)] * 0.7)
    far = max(near * 4, 8.0, min(far_d[min(len(far_d) - 1, int(len(far_d) * 0.9))] * 1.6, ground_size, 400.0))
    return near, far
