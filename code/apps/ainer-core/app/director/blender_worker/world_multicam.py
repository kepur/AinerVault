"""World 多机位 worker：读 world_take.json（World 局部 + 整场表演逐帧骨架姿态 + 本镜相机逐帧）→
建几何与标准人形骨架 → 机位检查（相机是否在墙里、焦点人物是否入画/被挡）→ 渲 clay(分色)/depth/pose/idmask
→ 写 camera.json（逐帧相机 + 每人 2D 框/中心）、check.json、manifest.json。

    Blender -b --factory-startup --python world_multicam.py -- job.json

只读 JSON，不执行外来代码；进度行 AINER_STAGE / AINER_PROGRESS / AINER_DONE / AINER_ERROR。
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.dirname(HERE) not in sys.path:
    sys.path.insert(0, os.path.dirname(HERE))

import bpy  # noqa: E402
import numpy as np  # noqa: E402
from bpy_extras.object_utils import world_to_camera_view  # noqa: E402
from mathutils import Vector  # noqa: E402

from blender_worker import common  # noqa: E402
from blender_worker.loaders import humanoid_rig  # noqa: E402
from blender_worker.png import draw_pose, write_png  # noqa: E402
from blender_worker.renderers import depth_renderer  # noqa: E402
from blender_worker.renderers.sequence import emit, encode, frames_dir, render_sequence, set_view  # noqa: E402

GREYS = {"floor": (0.55, 0.55, 0.57), "structure": (0.72, 0.72, 0.74), "prop": (0.62, 0.5, 0.4)}


def _box(name, aabb, color, coll):
    lo, hi = Vector(aabb["min"]), Vector(aabb["max"])
    me = bpy.data.meshes.new(name)
    import bmesh
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    coll.objects.link(ob)
    ob.location = (lo + hi) / 2
    ob.scale = hi - lo
    ob.color = tuple(color) + (1.0,)
    return ob


def build_world(job, scene):
    coll = scene.collection
    boxes = []
    for i in job["world"]["instances"]:
        col = GREYS.get(i["kind"], GREYS["structure"])
        ob = _box(f"inst_{i['key']}", i["aabb"], col, coll)
        boxes.append({"key": i["key"], "obj": ob, "aabb": i["aabb"], "collision": i["collision"], "kind": i["kind"]})
        # 储物柜：按 0.42m 一格加竖向分隔，白模看得出是柜子
        if i["asset"] == "locker_bank":
            lo, hi = i["aabb"]["min"], i["aabb"]["max"]
            x = lo[0]
            while x < hi[0] - 0.05:
                _box(f"locker_seam_{i['key']}_{x:.2f}", {"min": [x, lo[1] - 0.01, 0.05], "max": [x + 0.02, lo[1], hi[2] - 0.05]},
                     (0.45, 0.45, 0.48), coll)
                x += 0.42
        if i["asset"] == "window_wall":
            lo, hi = i["aabb"]["min"], i["aabb"]["max"]
            x = lo[0]
            while x < hi[0]:
                _box(f"mullion_{x:.1f}", {"min": [x, lo[1], hi[2]], "max": [x + 0.12, hi[1], 2.8]}, (0.7, 0.7, 0.72), coll)
                x += 1.6
            _box("window_top", {"min": [lo[0], lo[1], 2.8], "max": [hi[0], hi[1], 3.0]}, (0.72, 0.72, 0.74), coll)
    r = job["world"]["region"]["bounds_aabb"]
    if job["world"]["region"].get("kind") in ("street", "outdoor", "park", "field"):
        return boxes  # 室外区域没有天花板
    _box("ceiling", {"min": [r["min"][0], r["min"][1], 2.98], "max": [r["max"][0], r["max"][1], 3.05]}, (0.8, 0.8, 0.82), coll)
    return boxes


def build_actors(job, scene):
    rigs = {}
    for name, a in job["actors"].items():
        rigs[name] = humanoid_rig.build(name, float(a.get("height_m", 1.7)), a.get("build", "average"),
                                        a.get("color", (0.7, 0.7, 0.7)), scene.collection)
    return rigs


def key_frames(job, scene, rigs, cam):
    N = job["frames"]
    for f in range(N):
        fr = f + 1
        for name, rig in rigs.items():
            st = job["actors"][name]["frames"][f]
            ob = rig["obj"]
            ob.location = Vector(st["pos"])
            ob.rotation_euler = (0.0, 0.0, math.radians(st["yaw_deg"]))
            ob.keyframe_insert("location", frame=fr)
            ob.keyframe_insert("rotation_euler", frame=fr)
            humanoid_rig.apply_pose(rig, st["bones"], st["hips_dz"])
            for pb in ob.pose.bones:
                pb.keyframe_insert("rotation_quaternion", frame=fr)
            ob.pose.bones[humanoid_rig.PREFIX + "Hips"].keyframe_insert("location", frame=fr)
        c = job["camera_frames"][f]
        cam.location = Vector(c["pos"])
        cam.rotation_euler = (Vector(c["target"]) - Vector(c["pos"])).to_track_quat("-Z", "Y").to_euler()
        cam.data.lens = float(c.get("lens_mm", 35.0))
        cam.keyframe_insert("location", frame=fr)
        cam.keyframe_insert("rotation_euler", frame=fr)
        cam.data.keyframe_insert("lens", frame=fr)
    for ob in list(bpy.data.objects):
        ad = ob.animation_data
        if ad and ad.action:
            try:
                for fc in ad.action.fcurves:
                    for k in fc.keyframe_points:
                        k.interpolation = "LINEAR"
            except AttributeError:      # Blender 5 layered actions
                pass


def walk_2d(job, scene, cam, rigs, boxes, out):
    """逐帧：骨架关键点投影 → pose 图；每人 2D 框/中心；相机是否在碰撞体内。"""
    W, H = job["resolution"]
    N = job["frames"]
    d = frames_dir(out, "pose") if "pose" in job["passes"] else None
    per = {n: [] for n in rigs}
    cams, cam_in_wall = [], []
    for f in range(1, N + 1):
        scene.frame_set(f)
        cp = cam.matrix_world.translation
        for b in boxes:
            lo, hi = b["aabb"]["min"], b["aabb"]["max"]
            if b["collision"] and all(lo[i] <= cp[i] <= hi[i] for i in range(3)):
                cam_in_wall.append({"frame": f, "box": b["key"]})
        cams.append({"pos": [round(x, 4) for x in cp], "lens_mm": round(cam.data.lens, 3),
                     "matrix_world": [[round(x, 5) for x in row] for row in cam.matrix_world]})
        drawn = []
        for n, rig in rigs.items():
            kps = humanoid_rig.keypoints(rig)
            pts = []
            for co in kps:
                v = world_to_camera_view(scene, cam, co)
                ok = v.z > 0 and -0.02 <= v.x <= 1.02 and -0.02 <= v.y <= 1.02
                pts.append((float(v.x * W), float((1 - v.y) * H), 1.0 if ok else 0.0, float(v.z)))
            drawn.append([(x, y, c) for x, y, c, _ in pts])
            vis = [(x, y) for x, y, c, _ in pts if c > 0]
            foot = [pts[10], pts[13]]
            per[n].append({"frame": f, "visible_kps": len(vis),
                           "bbox": ([round(min(x for x, _ in vis), 1), round(min(y for _, y in vis), 1),
                                     round(max(x for x, _ in vis), 1), round(max(y for _, y in vis), 1)] if vis else None),
                           "center": ([round(sum(x for x, _ in vis) / len(vis), 1), round(sum(y for _, y in vis) / len(vis), 1)]
                                      if vis else None),
                           "foot": [round((foot[0][0] + foot[1][0]) / 2, 1), round(max(foot[0][1], foot[1][1]), 1)],
                           "depth": round(min(z for *_, z in pts), 3)})
        if d:
            write_png(os.path.join(d, f"{f:04d}.png"), draw_pose(W, H, drawn))
            emit("PROGRESS", **{"pass": "pose", "frame": f, "total": N})
    return {"camera": cams, "actors": per, "camera_in_collision": cam_in_wall}


def render_clay(scene, out, N):
    scene.render.engine = "BLENDER_WORKBENCH"
    sh = scene.display.shading
    sh.light = "STUDIO"
    sh.color_type = "OBJECT"
    sh.show_cavity = True
    try:
        sh.cavity_type = "BOTH"
    except TypeError:
        pass
    sh.show_shadows = True
    sh.shadow_intensity = 0.4
    scene.display.render_aa = "8"
    scene.world.color = (0.2, 0.2, 0.21)
    scene.view_layers[0].material_override = None
    set_view(scene, "Standard")
    return render_sequence(scene, out, "clay", N)


def render_idmask(scene, out, N, rigs):
    """每人纯色、其余全黑：用于站位 QA 与遮挡统计。"""
    saved = {o.name: tuple(o.color) for o in bpy.data.objects}
    palette = {}
    for i, (n, rig) in enumerate(rigs.items()):
        c = [(1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 0), (1, 0, 1), (0, 1, 1)][i % 6]
        palette[n] = c
        for m in rig["meshes"]:
            m.color = c + (1.0,)
    actor_meshes = {m.name for r in rigs.values() for m in r["meshes"]}
    for o in bpy.data.objects:
        if o.type == "MESH" and o.name not in actor_meshes:
            o.color = (0, 0, 0, 1)
    scene.render.engine = "BLENDER_WORKBENCH"
    sh = scene.display.shading
    sh.light = "FLAT"
    sh.color_type = "OBJECT"
    sh.show_cavity = False
    sh.show_shadows = False
    scene.display.render_aa = "OFF"
    scene.world.color = (0, 0, 0)
    set_view(scene, "Standard")
    try:
        d = render_sequence(scene, out, "idmask", N)
    finally:
        for o in bpy.data.objects:
            if o.name in saved:
                o.color = saved[o.name]
    return d, {n: list(c) for n, c in palette.items()}


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    with open(argv[0], encoding="utf-8") as fh:
        job = json.load(fh)
    out = job["out_dir"]
    os.makedirs(out, exist_ok=True)
    ffmpeg = job.get("ffmpeg") or shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    W, H = job["resolution"]
    N, fps = int(job["frames"]), int(job["fps"])
    t0 = time.time()
    emit("STAGE", stage="build", frames=N)
    scene = common.empty_scene()
    scene.render.resolution_x, scene.render.resolution_y = int(W), int(H)
    scene.render.resolution_percentage = 100
    scene.render.fps = fps
    scene.frame_start, scene.frame_end = 1, N
    if scene.world is None:
        scene.world = bpy.data.worlds.new("World")
    scene.world.use_nodes = True
    boxes = build_world(job, scene)
    rigs = build_actors(job, scene)
    cd = bpy.data.cameras.new("take_cam")
    cd.sensor_fit, cd.sensor_width = "HORIZONTAL", 36.0
    cd.clip_start, cd.clip_end = 0.05, 100
    cam = bpy.data.objects.new("take_cam", cd)
    scene.collection.objects.link(cam)
    scene.camera = cam
    key_frames(job, scene, rigs, cam)
    timings = {"build": round(time.time() - t0, 2)}
    outputs = {}
    t = time.time()
    emit("STAGE", stage="walk")
    walk = walk_2d(job, scene, cam, rigs, boxes, out)
    timings["walk"] = round(time.time() - t, 2)
    if "pose" in job["passes"]:
        outputs["pose"] = encode(ffmpeg, os.path.join(out, "frames", "pose"), os.path.join(out, "pose.mp4"), fps)
    if "clay" in job["passes"]:
        t = time.time()
        emit("STAGE", stage="clay")
        outputs["clay"] = encode(ffmpeg, render_clay(scene, out, N), os.path.join(out, "clay.mp4"), fps)
        timings["clay"] = round(time.time() - t, 2)
        shutil.copy(os.path.join(out, "frames", "clay", "0001.png"), os.path.join(out, "first_frame_clay.png"))
    palette = {}
    if "idmask" in job["passes"]:
        t = time.time()
        emit("STAGE", stage="idmask")
        d, palette = render_idmask(scene, out, N, rigs)
        outputs["idmask"] = encode(ffmpeg, d, os.path.join(out, "idmask.mp4"), fps, crf=0)
        timings["idmask"] = round(time.time() - t, 2)
    if "depth" in job["passes"]:
        t = time.time()
        emit("STAGE", stage="depth")
        cps = [Vector(c["pos"]) for c in job["camera_frames"]]
        near = 0.3
        far = max(6.0, max((Vector(b["aabb"]["max"]) - cps[0]).length for b in boxes if b["kind"] != "floor") * 0.6)
        outputs["depth"] = encode(ffmpeg, depth_renderer.render(scene, out, N, near, far), os.path.join(out, "depth.mp4"), fps)
        timings["depth"] = round(time.time() - t, 2)
    # 焦点人物入画检查（关键点可见数）
    focus_miss = []
    focus = [n for n in (job.get("focus") or []) if isinstance(n, str)]
    for n in focus:
        if n not in walk["actors"]:
            continue
        bad = [s["frame"] for s in walk["actors"][n] if s["visible_kps"] < 4]
        if len(bad) > N * 0.25:
            focus_miss.append({"actor": n, "frames_missing": len(bad)})
    check = {"camera_in_collision": walk["camera_in_collision"], "focus_out_of_frame": focus_miss}
    check["ok"] = not check["camera_in_collision"] and not check["focus_out_of_frame"]
    with open(os.path.join(out, "camera.json"), "w", encoding="utf-8") as fh:
        json.dump({"resolution": [W, H], "fps": fps, "frames": N, "camera": walk["camera"], "actors": walk["actors"],
                   "idmask_palette": palette}, fh)
    with open(os.path.join(out, "check.json"), "w", encoding="utf-8") as fh:
        json.dump(check, fh, ensure_ascii=False, indent=1)
    h = hashlib.sha256(json.dumps({k: job[k] for k in ("world", "camera_frames", "actors")}, sort_keys=True).encode()).hexdigest()
    manifest = {"job_type": "world_multicam", "take": job["take"], "world_id": job["world"]["id"],
                "world_version": job["world"]["version"], "region": job["world"]["region"]["key"],
                "chunk_set": [[c["cx"], c["cy"]] for c in job["world"]["chunks"]],
                "instance_revs": {i["key"]: i.get("rev", 1) for i in job["world"]["instances"]},
                "performance": job["performance"], "rig": "mixamo_standard_humanoid",
                "fps": fps, "frames": N, "resolution": [W, H], "input_hash": h, "outputs": outputs,
                "timings": timings, "blender": bpy.app.version_string, "check_ok": check["ok"]}
    with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1)
    if job.get("save_blend"):
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out, "take.blend"), compress=True)
    emit("DONE", ok=check["ok"], outputs=outputs, timings=timings)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        emit("ERROR", message=str(exc), trace=traceback.format_exc()[-2000:])
        raise SystemExit(1)
