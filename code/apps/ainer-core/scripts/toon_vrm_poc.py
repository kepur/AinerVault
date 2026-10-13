"""Anime (VRM/MToon) PoC re-render of one world_multicam greybox take. Optional, not wired into any flow.

    Blender -b --factory-startup --python toon_vrm_poc.py -- <job.json> <out_dir> [--vrm-dir var/assets/vrm]
        [--fps 24] [--res 1280x768] [--frames N] [--samples 16] [--still F]

Needs the VRM Add-on for Blender (saturday06, Blender extension `vrm`, installed into the user_default repo).
Same world/camera as toon_render_poc.py (env cel shader reused from it), but the capsule mannequins are replaced
by VRoid VRM characters (CAST below) that are:
  * scaled to the actor's height_m (stout build widened),
  * recoloured per actor (hair/brows/tops texture pixels remapped by luminance to the target colour),
  * driven by the take: root = actor pos/yaw(+hips_dz); bones = the take's Mixamo-named per-bone deltas
    retargeted onto VRM humanoid bones (chain-accumulated armature-space deltas; arms get a rest-direction
    correction so the VRM T-pose maps onto the capsule's arms-down rest),
  * shaded with the add-on's MToon (toony 2-band, face shading shift up = clean face, parametric rim,
    world-space outlines).
Writes frames/NNNN.png and timing.json.
"""
import json, math, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bpy  # noqa: E402
import numpy as np  # noqa: E402
from mathutils import Vector, Quaternion, Euler  # noqa: E402
import toon_render_poc as tp  # noqa: E402  (also sets up blender_worker import paths)
from blender_worker.loaders import humanoid_rig  # noqa: E402
import world_multicam as wm  # noqa: E402

argv = tp.argv
JOB, OUT = argv[0], argv[1]
opt = tp.opt
FPS, W, H, SAMPLES = tp.FPS, tp.W, tp.H, tp.SAMPLES
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
VRM_DIR = opt("--vrm-dir", os.path.join(REPO, "var", "assets", "vrm"))
STILL = opt("--still", None)

# actor -> (vrm file, hair, tops or None, bottoms or None)
CAST = {
    "thomas": ("Sakurada_Fumiriya.vrm", "#1b1a26", "#1f2a52", None),   # black hair, navy sweater vest
    "tyler": ("AvatarSample_C.vrm", "#e0302c", "#2a2a30", "#202026"),  # red hair, in black
    "brad": ("HairSample_Male.vrm", "#2ec24e", "#e6e8ee", "#2a2e45"),   # green hair, stocky
    "kyle": ("HairSample_Male.vrm", "#f4d24a", "#203070", "#22263a"),   # blond, navy track jacket
}
# Mixamo (take) -> VRM humanoid, with capsule parent for chain accumulation
MAP = {"Hips": "hips", "Spine": "spine", "Spine1": "chest", "Spine2": "upperChest", "Neck": "neck", "Head": "head"}
for s, v in (("Left", "left"), ("Right", "right")):
    MAP.update({f"{s}Shoulder": f"{v}Shoulder", f"{s}Arm": f"{v}UpperArm", f"{s}ForeArm": f"{v}LowerArm",
                f"{s}Hand": f"{v}Hand", f"{s}UpLeg": f"{v}UpperLeg", f"{s}Leg": f"{v}LowerLeg", f"{s}Foot": f"{v}Foot"})
REST_FIX = {"LeftArm", "RightArm", "LeftForeArm", "RightForeArm"}   # rest-direction correction (T-pose -> arms down)


def hexrgb(h):
    h = h.lstrip("#"); return np.array([int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)], dtype=np.float32)


def recolor_image(img, target, name):
    """Copy img, remap luminance onto target colour (sRGB stored values). Returns the new image."""
    new = img.copy(); new.name = name
    px = np.empty(len(new.pixels), dtype=np.float32); new.pixels.foreach_get(px)
    px = px.reshape(-1, 4)
    lum = px[:, :3] @ np.array([0.3, 0.59, 0.11], dtype=np.float32)
    m = px[:, 3] > 0.1
    ref = float(np.percentile(lum[m], 80)) if m.any() else 1.0
    t = np.clip(lum / max(ref, 1e-3), 0, 1.6)[:, None]
    base = target[None, :] * np.minimum(t, 1.0) ** 0.8
    hi = np.clip(t - 1.0, 0, 0.6) / 0.6
    px[:, :3] = base * (1 - hi * 0.6) + hi * 0.6
    new.pixels.foreach_set(px.ravel()); new.pack()
    return new


def mtoon(mat):
    ext = getattr(mat, "vrm_addon_extension", None)
    return ext.mtoon1 if ext is not None and ext.mtoon1.enabled else None


def recolor_material(mat, target, tag, done):
    mt = mtoon(mat)
    if mt is None:
        return
    mx = mt.extensions.vrmc_materials_mtoon
    for ti in (mt.pbr_metallic_roughness.base_color_texture, mx.shade_multiply_texture):
        src = ti.index.source
        if src is None:
            continue
        key = (src.name, tag)
        if key not in done:
            done[key] = recolor_image(src, target, f"{src.name}_{tag}")
        ti.index.source = done[key]
    mt.pbr_metallic_roughness.base_color_factor = (1, 1, 1, 1)
    if any(mt.emissive_factor):   # VRoid hair "spe" highlight is emissive in the original hue -> retint
        mt.emissive_factor = tuple(float(c) * 0.35 for c in target)
    mx.shade_color_factor = (0.62, 0.58, 0.78)


def style_material(mat, is_face):
    mt = mtoon(mat)
    if mt is None:
        return
    mx = mt.extensions.vrmc_materials_mtoon
    mx.shading_toony_factor = 0.95
    mx.shading_shift_factor = 0.55 if is_face else -0.05     # face: nearly always lit = clean anime face
    mx.gi_equalization_factor = 0.9
    mx.parametric_rim_color_factor = (0.55, 0.5, 0.65)
    mx.parametric_rim_fresnel_power_factor = 4.0
    mx.parametric_rim_lift_factor = 0.05
    mx.rim_lighting_mix_factor = 0.6
    if mt.alpha_mode == "OPAQUE" or "CLOTH" in mat.name or "SKIN" in mat.name or "HAIR" in mat.name:
        mx.outline_width_mode = "worldCoordinates"
        mx.outline_width_factor = 0.0012 if is_face else 0.0028
        mx.outline_color_factor = (0.10, 0.07, 0.10)
        mx.outline_lighting_mix_factor = 0.0


def humanoid_map(arm):
    ext = arm.data.vrm_addon_extension
    out = {}
    if ext.spec_version == "0.0":
        for b in ext.vrm0.humanoid.human_bones:
            if b.node.bone_name:
                out[b.bone] = b.node.bone_name
    else:
        hb = ext.vrm1.humanoid.human_bones
        for k in MAP.values():
            p = getattr(hb, {"upperChest": "upper_chest"}.get(k, "".join("_" + c.lower() if c.isupper() else c for c in k)), None)
            if p is not None and p.node.bone_name:
                out[k] = p.node.bone_name
    return out


def load_vrm(path, actor):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.vrm(filepath=path)
    new = [o for o in bpy.data.objects if o not in before]
    arm = next(o for o in new if o.type == "ARMATURE")
    arm.name = f"vrm_{actor}"
    meshes = [o for o in new if o.type == "MESH"]
    zs = [(o.matrix_world @ Vector(c)).z for o in meshes for c in o.bound_box]
    return arm, meshes, max(zs) - min(zs)


def setup_actor(actor, a):
    fname, hair, tops, bottoms = CAST[actor]
    arm, meshes, h0 = load_vrm(os.path.join(VRM_DIR, fname), actor)
    s = float(a.get("height_m", 1.7)) / h0
    wide = {"stout": 1.12, "slim": 0.95, "lanky": 0.96}.get(a.get("build", "average"), 1.0)
    arm.scale = (s * wide, s * wide, s)
    # materials are shared between duplicate imports of the same file -> make per-actor copies first
    done = {}
    for ob in meshes:
        for slot in ob.material_slots:
            if slot.material is None:
                continue
            m = slot.material.copy(); m.name = f"{actor}_{slot.material.name}"; slot.material = m
            n = m.name.upper()
            style_material(m, is_face="FACE" in n or "_FACE_" in n or n.endswith("FACE_00_SKIN") or "FACE_00_SKIN" in n)
            if "HAIR" in n:
                recolor_material(m, hexrgb(hair), "hair", done)
            elif "FACEBROW" in n or "EYELASH" in n:
                recolor_material(m, hexrgb(hair) * 0.55, "brow", done)
            elif tops and ("TOPS" in n or "VEST" in n):
                recolor_material(m, hexrgb(tops), "tops", done)
            elif bottoms and "BOTTOMS" in n:
                recolor_material(m, hexrgb(bottoms), "bottoms", done)
    hm = humanoid_map(arm)
    # rest data
    J = humanoid_rig._layout(float(a.get("height_m", 1.7)), a.get("build", "average"))
    rest = {}
    for mx_name, vname in MAP.items():
        bn = hm.get(vname)
        if not bn or bn not in arm.data.bones:
            continue
        b = arm.data.bones[bn]
        h, t, parent, _ = J[mx_name]
        dc = (Vector(t) - Vector(h)).normalized()
        dv = (b.tail_local - b.head_local).normalized()
        C = dv.rotation_difference(dc) if mx_name in REST_FIX else Quaternion()
        rest[mx_name] = {"bone": bn, "R": b.matrix_local.to_quaternion(), "C": C, "parent": parent}
    # hand follows forearm correction
    for s_ in ("Left", "Right"):
        if f"{s_}Hand" in rest and f"{s_}ForeArm" in rest:
            rest[f"{s_}Hand"]["C"] = rest[f"{s_}ForeArm"]["C"]
    for pb in arm.pose.bones:
        pb.rotation_mode = "QUATERNION"
    return {"arm": arm, "meshes": meshes, "rest": rest, "J": J}


def pose_actor(rig, bones):
    """capsule chain delta A_b = A_parent * D_b; VRM total delta T_b = A_b * C_b; local X_b = T_parent^-1 * T_b."""
    A, T = {}, {}
    arm = rig["arm"]
    for mx_name, (_h, _t, parent, _r) in rig["J"].items():   # J is parent-before-child ordered
        v = bones.get(mx_name)
        D = Euler([math.radians(x) for x in v], "XYZ").to_quaternion() if v else Quaternion()
        A[mx_name] = (A[parent] @ D) if parent else D
        r = rig["rest"].get(mx_name)
        if r is None:
            T[mx_name] = T.get(parent, Quaternion()) if parent else Quaternion()
            continue
        T[mx_name] = A[mx_name] @ r["C"]
        Tp = T[parent] if parent else Quaternion()
        X = Tp.inverted() @ T[mx_name]
        arm.pose.bones[r["bone"]].rotation_quaternion = r["R"].inverted() @ X @ r["R"]


def env_tweaks():
    """floor tiles + locker panels on top of the toon_render_poc env materials."""
    for ob in bpy.data.objects:
        if ob.type != "MESH" or not ob.data.materials or ob.data.materials[0] is None:
            continue
        m = ob.data.materials[0]
        if m.name not in ("env_floor", "env_lockers"):
            continue
        nt = m.node_tree; N = nt.nodes
        mix = next(n for n in N if n.type == "MIX")
        tc = N.new("ShaderNodeTexCoord")
        if m.name == "env_floor":
            tex = N.new("ShaderNodeTexChecker"); tex.inputs["Scale"].default_value = 1.0
            tex.inputs["Color1"].default_value = (*tp.srgb("#e6d6b4"), 1)
            tex.inputs["Color2"].default_value = (*tp.srgb("#c9b48c"), 1)
            mp = N.new("ShaderNodeMapping"); mp.inputs["Scale"].default_value = (1.6, 1.6, 1.6)
            nt.links.new(tc.outputs["Object"], mp.inputs[0]); nt.links.new(mp.outputs[0], tex.inputs["Vector"])
        else:
            tex = N.new("ShaderNodeTexBrick")
            tex.inputs["Color1"].default_value = (*tp.srgb("#4a8ae0"), 1)
            tex.inputs["Color2"].default_value = (*tp.srgb("#3a78d0"), 1)
            tex.inputs["Mortar"].default_value = (*tp.srgb("#1d3f7a"), 1)
            tex.inputs["Scale"].default_value = 1.0; tex.inputs["Mortar Size"].default_value = 0.012
            tex.inputs["Brick Width"].default_value = 0.42; tex.inputs["Row Height"].default_value = 0.9
            tex.offset = 0.0
            nt.links.new(tc.outputs["Object"], tex.inputs["Vector"])
        nt.links.new(tex.outputs["Color"], mix.inputs[6])
        m.name += "_x"   # same material may be on several objects: patch once


def main():
    job = json.load(open(JOB, encoding="utf-8"))
    os.makedirs(os.path.join(OUT, "frames"), exist_ok=True)
    N8, fps8 = int(job["frames"]), int(job["fps"])
    step = FPS / fps8
    NF = int(opt("--frames", round((N8 - 1) * step) + 1))
    scene = tp.common.empty_scene()
    try:
        bpy.ops.preferences.addon_enable(module="bl_ext.user_default.vrm")
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"VRM add-on not installed: {e}")
    if not hasattr(bpy.ops.import_scene, "vrm"):
        raise SystemExit("VRM add-on (bl_ext.user_default.vrm) not available")
    r = scene.render
    r.resolution_x, r.resolution_y, r.resolution_percentage, r.fps = W, H, 100, FPS
    scene.frame_start, scene.frame_end = 1, NF
    if scene.world is None:
        scene.world = bpy.data.worlds.new("World")
    t0 = time.time()
    boxes = wm.build_world(job, scene)
    env_objs = [o for o in bpy.data.objects if o.type == "MESH" and o.parent is None]
    rigs = {name: setup_actor(name, a) for name, a in job["actors"].items()}
    cd = bpy.data.cameras.new("take_cam"); cd.sensor_fit, cd.sensor_width = "HORIZONTAL", 36.0
    cd.clip_start, cd.clip_end = 0.05, 100
    cam = bpy.data.objects.new("take_cam", cd); scene.collection.objects.link(cam); scene.camera = cam
    for f in range(N8):
        fr = 1 + f * step
        for name, rig in rigs.items():
            st = job["actors"][name]["frames"][f]; ob = rig["arm"]
            ob.location = Vector(st["pos"]) + Vector((0, 0, st.get("hips_dz", 0.0)))
            ob.rotation_euler = (0, 0, math.radians(st["yaw_deg"]))
            ob.keyframe_insert("location", frame=fr); ob.keyframe_insert("rotation_euler", frame=fr)
            pose_actor(rig, st["bones"])
            for r_ in rig["rest"].values():
                ob.pose.bones[r_["bone"]].keyframe_insert("rotation_quaternion", frame=fr)
        c = job["camera_frames"][f]
        cam.location = Vector(c["pos"])
        cam.rotation_euler = (Vector(c["target"]) - Vector(c["pos"])).to_track_quat("-Z", "Y").to_euler()
        cd.lens = float(c.get("lens_mm", 35.0))
        cam.keyframe_insert("location", frame=fr); cam.keyframe_insert("rotation_euler", frame=fr)
        cd.keyframe_insert("lens", frame=fr)

    # environment: same cel shader as toon_render_poc + tiles/locker panels
    tp.OUTLINE = tp.outline_mat()
    mats = {k: tp.toon_mat(f"env_{k}", v) for k, v in tp.ENV.items()}
    for ob in env_objs:
        tp.bake_scale(ob)
        n = ob.name
        key = ("lockers" if "locker" in n and "seam" not in n else "seam" if "seam" in n else
               "mullion" if "mullion" in n else "window_top" if "window_top" in n else "ceiling" if n == "ceiling" else
               "floor" if "floor" in n else "left_wall" if "left_wall" in n else "window_wall" if "window_wall" in n else
               "door" if "door" in n else None)
        if key is None:
            kind = next((b["kind"] for b in boxes if b["obj"] == ob), "structure")
            key = "prop" if kind == "prop" else "structure"
        tp.set_mat(ob, mats[key])
        if key != "seam":
            tp.add_outline(ob, 0.015)
    env_tweaks()

    # light: key sun (soft-ish, filtered shadows against acne) + flat GI; sky gradient for camera rays
    sun = bpy.data.lights.new("key", "SUN"); sun.energy = 2.6; sun.angle = math.radians(4)
    for k, v in (("shadow_filter_radius", 2.0), ("use_shadow_jitter", False), ("shadow_maximum_resolution", 0.002)):
        if hasattr(sun, k):
            setattr(sun, k, v)
    so = bpy.data.objects.new("key", sun); scene.collection.objects.link(so)
    so.rotation_euler = (math.radians(50), 0, math.radians(150))   # from camera side: lit faces/backs
    wt = scene.world.node_tree; wn = wt.nodes; wn.clear()
    wo = wn.new("ShaderNodeOutputWorld"); tc = wn.new("ShaderNodeTexCoord"); sep = wn.new("ShaderNodeSeparateXYZ")
    rp = wn.new("ShaderNodeValToRGB"); rp.color_ramp.elements[0].color = (*tp.srgb("#bfe6ff"), 1)
    rp.color_ramp.elements[1].color = (*tp.srgb("#2f7fe0"), 1)
    bgc = wn.new("ShaderNodeBackground"); bgl = wn.new("ShaderNodeBackground")
    bgl.inputs["Color"].default_value = (0.42, 0.42, 0.48, 1); bgl.inputs["Strength"].default_value = 0.8
    lp = wn.new("ShaderNodeLightPath"); ms = wn.new("ShaderNodeMixShader")
    wt.links.new(tc.outputs["Window"], sep.inputs[0]); wt.links.new(sep.outputs["Y"], rp.inputs[0])
    wt.links.new(rp.outputs["Color"], bgc.inputs["Color"])
    wt.links.new(lp.outputs["Is Camera Ray"], ms.inputs[0])
    wt.links.new(bgl.outputs[0], ms.inputs[1]); wt.links.new(bgc.outputs[0], ms.inputs[2])
    wt.links.new(ms.outputs[0], wo.inputs[0])

    scene.render.engine = "BLENDER_EEVEE"
    ee = scene.eevee
    ee.taa_render_samples = SAMPLES
    for a_, v in (("use_shadows", True), ("use_raytracing", False), ("shadow_resolution_scale", 1.0),
                  ("shadow_step_count", 6), ("shadow_ray_count", 1)):
        if hasattr(ee, a_):
            setattr(ee, a_, v)
    scene.view_settings.view_transform = "Standard"; scene.view_settings.look = "None"
    scene.render.image_settings.file_format = "PNG"
    build_s = time.time() - t0
    rng = [int(STILL)] if STILL else range(1, NF + 1)
    times = []
    for fr in rng:
        t = time.time(); scene.frame_set(fr)
        scene.render.filepath = os.path.join(OUT, "frames", f"{fr:04d}.png")
        bpy.ops.render.render(write_still=True)
        times.append(time.time() - t)
        print(f"VRM_FRAME {fr}/{NF} {times[-1]:.2f}s", flush=True)
    info = {"job": JOB, "frames": len(times), "fps": FPS, "res": [W, H], "samples": SAMPLES,
            "cast": {k: v[0] for k, v in CAST.items()}, "build_s": round(build_s, 2),
            "render_total_s": round(sum(times), 2), "per_frame_avg_s": round(sum(times) / len(times), 3),
            "per_frame_first_s": round(times[0], 2),
            "per_frame_avg_excl_first_s": round(sum(times[1:]) / max(1, len(times) - 1), 3),
            "per_frame_s": [round(x, 3) for x in times], "blender": bpy.app.version_string}
    if not STILL:
        json.dump(info, open(os.path.join(OUT, "timing.json"), "w"), indent=1)
    print("VRM_DONE", json.dumps({k: v for k, v in info.items() if k != "per_frame_s"}), flush=True)


if __name__ == "__main__":
    main()
