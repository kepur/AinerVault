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
from blender_worker.renderers import idmask_renderer  # noqa: E402
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


#: 特写景别 → (取景高度 m, 瞄准高度 m, 焦点人物该占的画面比例)。比例是 Blender 色块实测出来的经验值：
#: 胸以上约 0.22，脸部特写约 0.30。中景以上是群戏，不在这里（要所有人入画）
FRAMING = {"ecu": (0.45, 1.55, 0.30), "cu": (0.75, 1.40, 0.22)}


def _small(res: tuple[int, int]) -> tuple[int, int]:
    return 256, max(16, round(256 * res[1] / res[0]))


def probe(job: dict, scene, cam, actors: dict, N: int, out: str) -> dict:
    """试机位：LLM 定的机位 ＋ 围着出场人物一圈的候选，每个渲两帧小色块图，按「每个人都露出来」打分。

    为什么要试：LLM 摆机位不看遮挡 —— 「固定镜头」预设是从目标人物面朝的方向拍，
    坏蛋第 1 镜的瘦男孩面朝墙被逼到墙角，机位就进了墙里，预演只拍到墙。
    """
    import math

    from mathutils import Vector

    ids = idmask_renderer.assign(actors)
    res = (int(job["resolution"][0]), int(job["resolution"][1]))
    small = _small(res)
    frames = sorted({1, max(1, N // 2)})
    scene.frame_set(1)
    pos = {aid: a["obj"].matrix_world.translation.copy() for aid, a in actors.items()}
    center = sum(pos.values(), Vector((0.0, 0.0, 0.0))) / max(1, len(pos))
    spread = 2.0 * max(((p - center).length for p in pos.values()), default=0.0)
    lens = float((job.get("probe") or {}).get("lens_mm") or 35.0)
    hfov = 2 * math.atan(36.0 / (2 * lens))
    vfov = 2 * math.atan(math.tan(hfov / 2) * res[1] / res[0])
    dist = max((spread + 1.4) / 2 / math.tan(hfov / 2), 1.9 / 2 / math.tan(vfov / 2))
    eye = center + Vector((0.0, 0.0, 1.45))
    cam_data = bpy.data.cameras.new("ainer probe")
    cam_data.lens, cam_data.sensor_fit, cam_data.sensor_width = lens, "HORIZONTAL", 36.0
    pc = bpy.data.objects.new("ainer probe", cam_data)
    scene.collection.objects.link(pc)
    cands: list[dict] = [{"name": "planner"}]
    # 景别（分镜 ecu/cu/ms）：镜头围着焦点人物（说台词的人）取景，而不是把所有人拍全
    pj = job.get("probe") or {}
    size = pj.get("shot_size") if pj.get("shot_size") in FRAMING else None
    focus = pj.get("focus") if pj.get("focus") in actors else None
    aim = eye
    if size and focus:
        view_h, aim_z, target = FRAMING[size]
        fpos = pos[focus]
        aim = Vector((fpos.x, fpos.y, aim_z))
        d0 = view_h / 2 / math.tan(vfov / 2)
        for k in (0.8, 1.0, 1.3):
            for deg in range(0, 360, 45):
                a = math.radians(deg)
                cands.append({"name": f"focus{deg}_{k}", "pos": aim + Vector((math.sin(a), -math.cos(a), 0.0)) * d0 * k})
    else:
        for k in (1.0, 0.65):
            for deg in range(0, 360, 45):
                a = math.radians(deg)
                cands.append({"name": f"orbit{deg}_{k}", "pos": eye + Vector((math.sin(a), -math.cos(a), 0.0)) * dist * k})
    tmp = os.path.join(out, "_probe.png")
    results = []
    with idmask_renderer.IdMaskView(scene):
        for c in cands:
            if "pos" in c:
                pc.location = c["pos"]
                pc.rotation_euler = (aim - c["pos"]).to_track_quat("-Z", "Y").to_euler()
                scene.camera = pc
            else:
                scene.camera = cam
            covs = [idmask_renderer.coverage(idmask_renderer.render_ids(scene, f, tmp, small), ids) for f in frames]
            per = {aid: min(cv[aid] for cv in covs) for aid in ids}
            if size and focus:
                # 焦点人物占画面的比例贴近这个景别该有的值，脸朝镜头的略加分；别人是否入画不管
                got, tgt = per.get(focus, 0.0), FRAMING[size][2]
                score = -abs(got - tgt) / tgt
                if "pos" in c:
                    to_cam = (c["pos"] - pos[focus]).normalized()
                    fwd = actors[focus]["obj"].matrix_world.to_3x3() @ Vector((0.0, -1.0, 0.0))
                    score += 0.15 * to_cam.dot(fwd.normalized())
            else:
                score = sum(min(v, 0.05) for v in per.values()) - 0.05 * sum(1 for v in per.values() if v < 0.003)
            results.append({"name": c["name"], "score": round(score, 5), "coverage": per,
                            **({"pos": list(c["pos"])} if "pos" in c else {})})
            emit("PROGRESS", **{"pass": "probe", "frame": len(results), "total": len(cands)})
    scene.camera = cam
    try:
        os.remove(tmp)
    except OSError:
        pass
    best = max(results, key=lambda r: r["score"])
    three = lambda v: [round(v[0], 3), round(v[2], 3), round(-v[1], 3)]   # noqa: E731  Blender 世界(Z 上) → 协议(Y 上)
    out_best = {"name": best["name"], "score": best["score"], "coverage": best["coverage"], "lens_mm": lens}
    if "pos" in best:
        out_best.update(position=three(best["pos"]), look_at=three(list(aim)))
    return {"planner": results[0], "best": out_best, "candidates": results, "center": three(list(center)),
            "distance": round(dist, 2)}


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
    if job.get("probe"):
        emit("STAGE", stage="probe")
        result = probe(job, scene, cam, actors, N, out)
        with open(os.path.join(out, "probe.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
        emit("DONE", probe=result["best"], planner_score=result["planner"]["score"])
        return
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

    # 人物色块：每个人真实露出多少（算遮挡），首帧每个人的轮廓（分区身份用）
    if actors:
        t = time.time()
        emit("STAGE", stage="idmask")
        ids = idmask_renderer.assign(actors)
        vis: dict[str, list[float]] = {aid: [] for aid in ids}
        sample = sorted({1, max(1, N // 2), N})
        with idmask_renderer.IdMaskView(scene):
            for f in sample:
                cov = idmask_renderer.coverage(idmask_renderer.render_ids(
                    scene, f, os.path.join(out, "_ids.png"), _small(res)), ids)
                for aid, v in cov.items():
                    vis[aid].append(v)
            first_ids = idmask_renderer.render_ids(scene, 1, os.path.join(out, "_ids.png"))
            masks = idmask_renderer.write_masks(first_ids, ids, os.path.join(out, "masks"))
        try:
            os.remove(os.path.join(out, "_ids.png"))
        except OSError:
            pass
        visibility = {"frames": sample, "actors": {aid: {"coverage": vis[aid], "index": ids[aid],
                                                         "mask": os.path.relpath(masks[aid], out) if aid in masks else None}
                                                   for aid in ids}}
        with open(os.path.join(out, "visibility.json"), "w", encoding="utf-8") as f:
            json.dump(visibility, f, ensure_ascii=False, indent=1)
        outputs["visibility"] = os.path.join(out, "visibility.json")
        timings["idmask"] = time.time() - t

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
