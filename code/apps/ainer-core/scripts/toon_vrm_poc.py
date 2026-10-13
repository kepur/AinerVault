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
LEGACY_YAW_BUG = "--legacy-yaw-bug" in argv     # reproduce the first PoC's bug (QA must FAIL on it)
QA_ONLY = "--qa-only" in argv

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


def _rgb2hsv(c):
    mx, mn = c.max(1), c.min(1); d = mx - mn
    h = np.zeros_like(mx); nz = d > 1e-6
    r, g, b = c[:, 0], c[:, 1], c[:, 2]
    i = nz & (mx == r); h[i] = ((g - b)[i] / d[i]) % 6
    i = nz & (mx == g) & (mx != r); h[i] = (b - r)[i] / d[i] + 2
    i = nz & (mx == b) & (mx != r) & (mx != g); h[i] = (r - g)[i] / d[i] + 4
    return h / 6.0, np.where(mx > 1e-6, d / np.maximum(mx, 1e-6), 0), mx


def _hsv2rgb(h, s, v):
    i = np.floor(h * 6).astype(int) % 6; f = h * 6 - np.floor(h * 6)
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    out = np.stack([np.choose(i, [v, q, p, p, t, v]), np.choose(i, [t, v, v, q, p, p]),
                    np.choose(i, [p, p, t, v, v, q])], 1)
    return out


def recolor_image(img, target, name):
    """Copy img and hue-shift it onto target (sRGB stored values), PRESERVING the texture detail:
    hue := target hue, saturation/value re-scaled relative to the texture's own reference (80th pct), so
    strand highlights, fold shading, seams and line art painted in the texture survive. (The first PoC
    remapped luminance to a flat colour, which flattened hair strands and clothing detail.)"""
    new = img.copy(); new.name = name
    px = np.empty(len(new.pixels), dtype=np.float32); new.pixels.foreach_get(px)
    px = px.reshape(-1, 4)
    m = px[:, 3] > 0.1
    h, s, v = _rgb2hsv(px[:, :3])
    th, ts, tv = (x[0] for x in _rgb2hsv(target[None, :]))
    vref = float(np.percentile(v[m], 80)) if m.any() else 1.0
    sref = float(np.percentile(s[m], 60)) if m.any() else 1.0
    rel_v = v / max(vref, 1e-3)                        # detail: relative brightness (strands, folds)
    rel_s = np.clip(s / max(sref, 0.05), 0, 1.5) if sref > 0.08 else np.ones_like(s)
    nv = np.clip(tv * rel_v ** 0.9 + np.clip(rel_v - 1.0, 0, 1) * 0.35 * max(tv, 0.25), 0, 1)   # keep highlights
    ns = np.clip(ts * (0.55 + 0.45 * rel_s) * (1 - np.clip(rel_v - 1.05, 0, 1) * 0.5), 0, 1)
    if ts < 0.15:                                       # near-neutral target (black/white): mostly desaturate
        ns = np.clip(s * 0.15 + ts, 0, 1)
    px[:, :3] = _hsv2rgb(np.full_like(h, th), ns, nv)
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
        # screen-space outline width (MToon 1.0: fraction of screen height) -> constant ~2-3 px lines at any
        # distance (world-space 2.8 mm lines vanished on far actors and were blobby on near ones)
        mx.outline_width_mode = "screenCoordinates"
        mx.outline_width_factor = 0.0012 if is_face else 0.0024
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
    # ROOT-CAUSE FIX (shot18 "walking into the wall"): the VRM add-on creates the armature with
    # rotation_mode='QUATERNION', so the take yaw keyed into rotation_euler was silently ignored and every
    # actor kept its rest facing (-Y = towards the window wall) while translating along +X (sideways slide).
    arm.rotation_mode = "XYZ" if not LEGACY_YAW_BUG else "QUATERNION"
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
    # head-local forward: eye midpoint minus head (rest), in head bone-local frame
    hf = Vector((0, -1, 0))
    if "Head" in rest:
        hb_ = arm.data.bones[rest["Head"]["bone"]]
        eyes = [arm.data.bones[hm[k]].head_local for k in ("leftEye", "rightEye") if hm.get(k) in arm.data.bones]
        w = (sum(eyes, Vector()) / len(eyes) - hb_.head_local) if eyes else Vector((0, -1, 0))
        w.z = 0
        hf = hb_.matrix_local.to_3x3().inverted() @ (w.normalized() if w.length > 1e-4 else Vector((0, -1, 0)))
    return {"arm": arm, "meshes": meshes, "rest": rest, "J": J, "hm": hm, "head_fwd_local": hf}


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


def unwrap(yaws):
    out = [float(yaws[0])]
    for y in yaws[1:]:
        d = (float(y) - out[-1] + 180.0) % 360.0 - 180.0
        out.append(out[-1] + d)
    return out


def corridor_axis(job):
    """Unit XY vector of the region's long horizontal extent (the corridor axis)."""
    reg = job["world"]["region"]["bounds_aabb"]
    dx, dy = reg["max"][0] - reg["min"][0], reg["max"][1] - reg["min"][1]
    return Vector((1, 0, 0)) if dx >= dy else Vector((0, 1, 0))


def colliders(job):
    return [(i["key"], i["aabb"]) for i in job["world"].get("instances", []) if i.get("collision")]


def _hit(p, r, boxes, z0=0.05, z1=1.6):
    for k, bb in boxes:
        if (bb["min"][0] - r <= p.x <= bb["max"][0] + r and bb["min"][1] - r <= p.y <= bb["max"][1] + r
                and bb["max"][2] > z0 and bb["min"][2] < z1):
            return k
    return None


def qa_motion(job, scene, rigs, nf, fps, out_path=None, radius=0.16, probe=0.45):
    """Automatic facing/path QA on the EVALUATED scene (what is rendered):
      forward  = head-bone-derived facing of the posed VRM (falls back to armature -Y)
      velocity = root XY displacement per frame
    Per actor while moving (speed > 0.35 m/s): cos(forward, velocity) must be >= 0.7 (no sideways / backwards
    walking) and the path must run along the corridor axis (|cos(velocity, axis)| >= 0.7 for >= 70% of
    moving frames). For every frame: body circle (r=radius) must not intersect a collider AABB, and while
    moving the point `probe` m ahead along forward must not be inside a collider ("walking into a wall")."""
    axis = corridor_axis(job); boxes = colliders(job)
    rep = {"corridor_axis": list(axis), "actors": {}, "pass": True, "fail_reasons": []}
    track = {}
    for fr in range(1, nf + 1):
        scene.frame_set(fr)
        for name, rig in rigs.items():
            arm = rig["arm"]; mw = arm.matrix_world
            hb = rig["rest"].get("Head")
            if hb:
                pb = arm.pose.bones[hb["bone"]]
                fwd = (mw.to_3x3() @ (pb.matrix.to_3x3() @ (rig["head_fwd_local"])))
            else:
                fwd = mw.to_3x3() @ Vector((0, -1, 0))
            fwd.z = 0; fwd = fwd.normalized() if fwd.length > 1e-6 else Vector((0, -1, 0))
            track.setdefault(name, []).append((mw.translation.copy(), fwd))
    for name, tr in track.items():
        moving, ok_face, ok_axis, worst, wall_hits, probe_hits = 0, 0, 0, 1.0, [], []
        for i, (p, fwd) in enumerate(tr):
            a, b = tr[max(0, i - 1)][0], tr[min(len(tr) - 1, i + 1)][0]
            v = (b - a); v.z = 0
            dt = (min(len(tr) - 1, i + 1) - max(0, i - 1)) / fps
            sp = v.length / dt if dt else 0
            k = _hit(Vector((p.x, p.y, 0)), radius, boxes)
            if k:
                wall_hits.append((i + 1, k))
            if sp > 0.35:
                moving += 1
                vd = v.normalized()
                c = fwd.dot(vd); worst = min(worst, c)
                ok_face += c >= 0.7
                ok_axis += abs(vd.dot(axis)) >= 0.7
                k2 = _hit(Vector((p.x, p.y, 0)) + fwd * probe, 0.0, boxes)
                if k2:
                    probe_hits.append((i + 1, k2))
        ar = {"moving_frames": moving, "facing_ok_frac": round(ok_face / moving, 3) if moving else None,
              "worst_cos_forward_vs_velocity": round(worst, 3) if moving else None,
              "along_axis_frac": round(ok_axis / moving, 3) if moving else None,
              "wall_overlap_frames": wall_hits[:5], "walks_into_wall_frames": probe_hits[:5],
              "end_forward": [round(x, 3) for x in tr[-1][1][:2]], "end_pos": [round(x, 3) for x in tr[-1][0][:2]]}
        bad = []
        if moving and ok_face / moving < 0.9:
            bad.append(f"{name}: forward vs path direction mismatch (ok {ok_face}/{moving}, worst cos {worst:.2f})")
        if moving and ok_axis / moving < 0.7:
            bad.append(f"{name}: path not along corridor axis ({ok_axis}/{moving})")
        if wall_hits:
            bad.append(f"{name}: body intersects collider {wall_hits[0]}")
        if probe_hits:
            bad.append(f"{name}: walking into wall {probe_hits[0]}")
        ar["pass"] = not bad; rep["actors"][name] = ar; rep["fail_reasons"] += bad
    rep["pass"] = not rep["fail_reasons"]
    if out_path:
        json.dump(rep, open(out_path, "w"), indent=1)
    print("QA_MOTION", "PASS" if rep["pass"] else "FAIL", json.dumps(rep["fail_reasons"]), flush=True)
    return rep


def main():
    ctx = build_scene()
    scene, NF = ctx["scene"], ctx["NF"]
    qa = qa_motion(ctx["job"], scene, ctx["rigs"], NF, FPS, os.path.join(OUT, "qa_motion.json"))
    if QA_ONLY:
        return
    if not qa["pass"] and "--allow-qa-fail" not in argv:
        raise SystemExit("QA_MOTION failed: " + "; ".join(qa["fail_reasons"]))
    render_frames(ctx)


def build_scene():
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
    yaws = {n: unwrap([st["yaw_deg"] for st in a["frames"]]) for n, a in job["actors"].items()}
    for f in range(N8):
        fr = 1 + f * step
        for name, rig in rigs.items():
            st = job["actors"][name]["frames"][f]; ob = rig["arm"]
            ob.location = Vector(st["pos"]) + Vector((0, 0, st.get("hips_dz", 0.0)))
            ob.rotation_euler = (0, 0, math.radians(yaws[name][f]))   # unwrapped: no 318deg Bezier spins
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
    return {"scene": scene, "rigs": rigs, "cam": cam, "job": job, "NF": NF, "t0": t0, "boxes": boxes,
            "env_objs": env_objs, "sun": so}


def render_frames(ctx, frames=None, tag="VRM"):
    scene, NF, t0 = ctx["scene"], ctx["NF"], ctx["t0"]
    build_s = time.time() - t0
    rng = frames or ([int(STILL)] if STILL else range(1, NF + 1))
    times = []
    for fr in rng:
        t = time.time(); scene.frame_set(fr)
        scene.render.filepath = os.path.join(OUT, "frames", f"{fr:04d}.png")
        bpy.ops.render.render(write_still=True)
        times.append(time.time() - t)
        print(f"{tag}_FRAME {fr}/{NF} {times[-1]:.2f}s", flush=True)
    info = {"job": JOB, "frames": len(times), "fps": FPS, "res": [W, H], "samples": SAMPLES,
            "cast": {k: v[0] for k, v in CAST.items()}, "build_s": round(build_s, 2),
            "render_total_s": round(sum(times), 2), "per_frame_avg_s": round(sum(times) / len(times), 3),
            "per_frame_first_s": round(times[0], 2),
            "per_frame_avg_excl_first_s": round(sum(times[1:]) / max(1, len(times) - 1), 3),
            "per_frame_s": [round(x, 3) for x in times], "blender": bpy.app.version_string}
    if not STILL:
        json.dump(info, open(os.path.join(OUT, "timing.json"), "w"), indent=1)
    print(f"{tag}_DONE", json.dumps({k: v for k, v in info.items() if k != "per_frame_s"}), flush=True)
    return info


if __name__ == "__main__":
    main()
