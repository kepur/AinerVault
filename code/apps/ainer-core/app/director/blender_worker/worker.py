"""Blender 无头 worker：读 job.json → 建场景 → 渲控制素材 → 写 manifest.json。

由 ainer-core 的 BlenderAdapter 起：
    Blender -b --factory-startup --python worker.py -- job.json

只读 job.json 和它指向的烘焙数据（scene_resolved.json），不执行任何外来代码 —— LLM 从来不写 bpy。
进度逐行打到 stdout：AINER_STAGE / AINER_PROGRESS / AINER_DONE / AINER_ERROR + JSON。

job.json：
  job_id, scene_id, out_dir, baked_path, resolution [w, h], passes [preview, clay, depth, pose, canny],
  ffmpeg, media_root, preview_samples, save_blend
产出（out_dir 下）：
  preview.mp4 clay.mp4 depth.mp4 pose.mp4 canny.mp4 first_frame.png
  camera.json motion.json scene.blend manifest.json frames/<pass>/0001.png…
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.dirname(HERE) not in sys.path:
    sys.path.insert(0, os.path.dirname(HERE))

import bpy  # noqa: E402

from blender_worker import common  # noqa: E402
from blender_worker.exporters import camera_exporter, manifest_exporter, motion_exporter  # noqa: E402
from blender_worker.loaders import environment_loader  # noqa: E402
from blender_worker.motion import action_mapper, trajectory_tools  # noqa: E402
from blender_worker.renderers import canny_renderer, clay_renderer, depth_renderer, pose_renderer, preview_renderer  # noqa: E402
from blender_worker.renderers.sequence import emit, encode  # noqa: E402
from blender_worker.scene_builders import actor_builder, camera_builder, prop_builder  # noqa: E402

ALL_PASSES = ["preview", "clay", "depth", "pose", "canny"]


def build(job: dict, baked: dict):
    W, H = job["resolution"]
    N = baked["frames"]
    scene = common.empty_scene()
    scene.render.resolution_x, scene.render.resolution_y = int(W), int(H)
    scene.render.resolution_percentage = 100
    scene.render.fps = int(baked["fps"])
    scene.frame_start, scene.frame_end = 1, N
    coll = scene.collection
    root = common.make_root(scene)
    environment_loader.build_world(scene, baked["env"])
    environment_loader.build_ground(baked["env"], root, coll)
    environment_loader.build_lights(baked["lights"], root, coll)
    ab = actor_builder.ActorBuilder(coll)
    objs = prop_builder.build_all(baked, root, coll, job.get("media_root"), on_character=ab)
    for oid, data in (baked.get("anim") or {}).items():
        if oid in objs:
            trajectory_tools.key_transforms(objs[oid], data, N)
    for aid, data in (baked.get("rigs") or {}).items():
        if aid in ab.actors:
            action_mapper.apply_rig(ab.actors[aid], baked["rigChannels"], data, N)
    cam, others = camera_builder.build(baked, root, coll)
    trajectory_tools.key_camera(cam, baked["camera"]["frames"], N)
    for cid, c in (baked.get("cameras") or {}).items():
        trajectory_tools.key_camera(others[cid], c["frames"], N)
    scene.camera = cam
    return scene, cam, objs, ab.actors


def main() -> None:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if not argv:
        raise SystemExit("用法：Blender -b --python worker.py -- job.json")
    with open(argv[0], encoding="utf-8") as f:
        job = json.load(f)
    with open(job["baked_path"], encoding="utf-8") as f:
        baked = json.load(f)
    out = job["out_dir"]
    os.makedirs(out, exist_ok=True)
    passes = [p for p in (job.get("passes") or ALL_PASSES) if p in ALL_PASSES]
    res = (int(job["resolution"][0]), int(job["resolution"][1]))
    N, fps = baked["frames"], int(baked["fps"])
    ffmpeg = job.get("ffmpeg") or shutil.which("ffmpeg") or "ffmpeg"
    job["blender_version"] = bpy.app.version_string
    timings: dict[str, float] = {}
    outputs: dict[str, str] = {}

    t = time.time()
    emit("STAGE", stage="build", frames=N)
    scene, cam, objs, actors = build(job, baked)
    if job.get("save_blend", True):
        outputs["blend"] = os.path.join(out, "scene.blend")
        bpy.ops.wm.save_as_mainfile(filepath=outputs["blend"], compress=True)
    timings["build"] = time.time() - t

    t = time.time()
    emit("STAGE", stage="walk")
    walk = pose_renderer.walk(scene, cam, actors, N, res, out if "pose" in passes else None)
    near, far = pose_renderer.depth_range(scene, cam, objs, actors, N, float(baked["env"].get("groundSize") or 120))
    timings["pose"] = time.time() - t

    if "preview" in passes:
        t = time.time()
        emit("STAGE", stage="preview")
        preview_renderer.render(scene, out, N, int(job.get("preview_samples") or 16))
        timings["preview"] = time.time() - t
    if "clay" in passes:
        t = time.time()
        emit("STAGE", stage="clay")
        clay_renderer.render(scene, out, N)
        timings["clay"] = time.time() - t
    if "depth" in passes:
        t = time.time()
        emit("STAGE", stage="depth", near=round(near, 2), far=round(far, 2))
        depth_renderer.render(scene, out, N, near, far)
        timings["depth"] = time.time() - t
    if "canny" in passes:
        src = "preview" if "preview" in passes else ("clay" if "clay" in passes else None)
        if src:
            t = time.time()
            emit("STAGE", stage="canny")
            canny_renderer.render(ffmpeg, out, src, N)
            timings["canny"] = time.time() - t

    t = time.time()
    emit("STAGE", stage="encode")
    for p in passes:
        d = os.path.join(out, "frames", p)
        if os.path.isdir(d) and os.listdir(d):
            outputs[p] = encode(ffmpeg, d, os.path.join(out, f"{p}.mp4"), fps, crf=12 if p == "depth" else 16)
    first = next((os.path.join(out, "frames", p, "0001.png") for p in ("preview", "clay") if p in passes), None)
    if first and os.path.exists(first):
        outputs["first_frame"] = os.path.join(out, "first_frame.png")
        shutil.copyfile(first, outputs["first_frame"])
    timings["encode"] = time.time() - t

    outputs["camera_json"] = camera_exporter.write(os.path.join(out, "camera.json"), baked, walk, res)
    outputs["motion_json"] = motion_exporter.write(os.path.join(out, "motion.json"), baked, actors, walk, res)
    outputs["scene_resolved"] = job["baked_path"]
    job["depth_range"] = [round(near, 3), round(far, 3)]
    manifest = manifest_exporter.write(out, job, baked, outputs, timings)
    emit("DONE", manifest=manifest, timings={k: round(v, 1) for k, v in timings.items()})


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:          # noqa: BLE001 —— 报给 ainer-core，由它决定重试还是失败
        emit("ERROR", message=f"{type(exc).__name__}: {exc}", trace=traceback.format_exc()[-3000:])
        sys.exit(2)
