"""Toon (三渲二 / cel-shaded) PoC re-render of one world_multicam greybox take. Optional, not wired into any flow.

    Blender -b --factory-startup --python toon_render_poc.py -- <job.json> <out_dir> [--lineart] [--fps 24]
        [--res 1280x768] [--frames N] [--samples 16]

Rebuilds the same scene as blender_worker/world_multicam.py (world boxes + Mixamo-named capsule rigs + camera),
retimes the 8fps take to --fps by spacing keys (Bezier in-between), and renders EEVEE with:
Diffuse -> Shader-to-RGB -> constant ColorRamp (3 bands) x per-zone palette -> Emission,
inverted-hull outlines (Solidify flip + backface-culled black material), optional Line Art,
camera-space sky gradient, Standard view transform. Writes frames/NNNN.png and timing.json.
"""
import json, math, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
BW = os.path.join(os.path.dirname(HERE), "app", "director")
sys.path.insert(0, BW)
sys.path.insert(0, os.path.join(BW, "blender_worker"))

import bpy, bmesh  # noqa: E402
from mathutils import Vector, Matrix  # noqa: E402
from blender_worker import common  # noqa: E402
from blender_worker.loaders import humanoid_rig  # noqa: E402
import world_multicam as wm  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:]
JOB, OUT = argv[0], argv[1]
def opt(k, d):
    return argv[argv.index(k) + 1] if k in argv else d
LINEART = "--lineart" in argv
FPS = int(opt("--fps", 24))
W, H = map(int, opt("--res", "1280x768").split("x"))
SAMPLES = int(opt("--samples", 16))

def srgb(h):
    return common.hex_rgb(h)

# ---- palettes -------------------------------------------------------------
ENV = {"floor": "#d9c7a4", "left_wall": "#f2e6cf", "window_wall": "#e8dcc4", "ceiling": "#fbf4e6",
       "lockers": "#3f7fd6", "seam": "#24508f", "mullion": "#f7f2e8", "window_top": "#f7f2e8", "door": "#b0703a",
       "prop": "#c98a4b", "structure": "#eadfca"}
SKIN, SKIN_SH = "#ffd9c0", None
UNIFORMS = ["#23356b", "#f4f4f8", "#b8323c", "#2f2f38", "#4c7a3d", "#e0b04a"]
PANTS = ["#2a2e45", "#3b3b4a", "#26354f", "#4a3a30"]

def toon_mat(name, hexcol, shadow="#8c7fb8", rim=False):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree; N = nt.nodes; L = nt.links
    N.clear()
    out = N.new("ShaderNodeOutputMaterial")
    dif = N.new("ShaderNodeBsdfDiffuse"); dif.inputs["Color"].default_value = (1, 1, 1, 1)
    s2r = N.new("ShaderNodeShaderToRGB")
    bw = N.new("ShaderNodeRGBToBW")
    ramp = N.new("ShaderNodeValToRGB"); cr = ramp.color_ramp
    cr.interpolation = "CONSTANT"
    sh = srgb(shadow)
    cr.elements[0].position = 0.0; cr.elements[0].color = (*[0.55 * c + 0.12 for c in sh], 1)   # deep shadow band
    cr.elements[1].position = 0.18; cr.elements[1].color = (*[0.35 * c + 0.55 for c in sh], 1)  # mid band
    e = cr.elements.new(0.55); e.color = (1, 1, 1, 1)                                              # lit band
    mix = N.new("ShaderNodeMix"); mix.data_type = "RGBA"; mix.blend_type = "MULTIPLY"
    mix.inputs["Factor"].default_value = 1.0
    mix.inputs[6].default_value = (*srgb(hexcol), 1)
    em = N.new("ShaderNodeEmission")
    L.new(dif.outputs[0], s2r.inputs[0]); L.new(s2r.outputs["Color"], bw.inputs[0])
    L.new(bw.outputs[0], ramp.inputs[0]); L.new(ramp.outputs["Color"], mix.inputs[7])
    L.new(mix.outputs[2], em.inputs["Color"]); L.new(em.outputs[0], out.inputs[0])
    return m

def outline_mat():
    m = bpy.data.materials.new("toon_outline"); m.use_nodes = True
    nt = m.node_tree; nt.nodes.clear()
    o = nt.nodes.new("ShaderNodeOutputMaterial"); e = nt.nodes.new("ShaderNodeEmission")
    e.inputs["Color"].default_value = (0.03, 0.025, 0.04, 1)
    nt.links.new(e.outputs[0], o.inputs[0])
    m.use_backface_culling = True
    return m

OUTLINE = None
def add_outline(ob, thick):
    ob.data.materials.append(OUTLINE)
    md = ob.modifiers.new("toon_hull", "SOLIDIFY")
    md.thickness = thick; md.offset = 1.0; md.use_flip_normals = True; md.use_rim = False
    md.material_offset = len(ob.data.materials) - 1

def set_mat(ob, m):
    ob.data.materials.clear(); ob.data.materials.append(m)

def bake_scale(ob):
    if ob.parent is None and tuple(ob.scale) != (1, 1, 1):
        ob.data.transform(Matrix.Diagonal((*ob.scale, 1)))
        ob.scale = (1, 1, 1)

def hair_cap(name, head_ob, r):
    me = head_ob.data.copy(); me.name = f"{name}_hair"
    bm = bmesh.new(); bm.from_mesh(me)
    bmesh.ops.scale(bm, vec=(1.12, 1.12, 1.1), verts=bm.verts)
    kill = [v for v in bm.verts if v.co.z < -0.35 * r or (v.co.y < -0.25 * r and v.co.z < 0.45 * r)]
    bmesh.ops.delete(bm, geom=kill, context="VERTS")
    bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.new(me.name, me); head_ob.users_collection[0].objects.link(ob)
    ob.parent, ob.parent_type, ob.parent_bone = head_ob.parent, "BONE", head_ob.parent_bone
    bpy.context.view_layer.update(); ob.matrix_world = head_ob.matrix_world.copy()
    return ob

def eyes(name, head_ob, r, mat):
    out = []
    for s in (-1, 1):
        bm = bmesh.new(); bmesh.ops.create_uvsphere(bm, u_segments=10, v_segments=8, radius=0.16 * r)
        bmesh.ops.scale(bm, vec=(0.8, 0.35, 1.5), verts=bm.verts)
        me = bpy.data.meshes.new(f"{name}_eye{s}"); bm.to_mesh(me); bm.free()
        ob = bpy.data.objects.new(me.name, me); head_ob.users_collection[0].objects.link(ob)
        ob.parent, ob.parent_type, ob.parent_bone = head_ob.parent, "BONE", head_ob.parent_bone
        bpy.context.view_layer.update()
        ob.matrix_world = head_ob.matrix_world @ Matrix.Translation((s * 0.36 * r, -0.86 * r, 0.12 * r))
        set_mat(ob, mat); out.append(ob)
    return out

def main():
    job = json.load(open(JOB, encoding="utf-8"))
    os.makedirs(os.path.join(OUT, "frames"), exist_ok=True)
    N8, fps8 = int(job["frames"]), int(job["fps"])
    step = FPS / fps8
    NF = int(opt("--frames", round((N8 - 1) * step) + 1))
    scene = common.empty_scene()
    r = scene.render
    r.resolution_x, r.resolution_y, r.resolution_percentage, r.fps = W, H, 100, FPS
    scene.frame_start, scene.frame_end = 1, NF
    if scene.world is None:
        scene.world = bpy.data.worlds.new("World")
    t0 = time.time()
    boxes = wm.build_world(job, scene)
    rigs = wm.build_actors(job, scene)
    cd = bpy.data.cameras.new("take_cam"); cd.sensor_fit, cd.sensor_width = "HORIZONTAL", 36.0
    cd.clip_start, cd.clip_end = 0.05, 100
    cam = bpy.data.objects.new("take_cam", cd); scene.collection.objects.link(cam); scene.camera = cam
    # keys at 8fps positions spaced by `step` on the 24fps timeline (Bezier in-betweens)
    for f in range(N8):
        fr = 1 + f * step
        for name, rig in rigs.items():
            st = job["actors"][name]["frames"][f]; ob = rig["obj"]
            ob.location = Vector(st["pos"]); ob.rotation_euler = (0, 0, math.radians(st["yaw_deg"]))
            ob.keyframe_insert("location", frame=fr); ob.keyframe_insert("rotation_euler", frame=fr)
            humanoid_rig.apply_pose(rig, st["bones"], st["hips_dz"])
            for pb in ob.pose.bones:
                pb.keyframe_insert("rotation_quaternion", frame=fr)
            ob.pose.bones[humanoid_rig.PREFIX + "Hips"].keyframe_insert("location", frame=fr)
        c = job["camera_frames"][f]
        cam.location = Vector(c["pos"])
        cam.rotation_euler = (Vector(c["target"]) - Vector(c["pos"])).to_track_quat("-Z", "Y").to_euler()
        cd.lens = float(c.get("lens_mm", 35.0))
        cam.keyframe_insert("location", frame=fr); cam.keyframe_insert("rotation_euler", frame=fr)
        cd.keyframe_insert("lens", frame=fr)

    global OUTLINE
    OUTLINE = outline_mat()
    mats = {k: toon_mat(f"env_{k}", v) for k, v in ENV.items()}
    for ob in [o for o in bpy.data.objects if o.type == "MESH" and o.parent is None]:
        bake_scale(ob)
        n = ob.name
        key = ("lockers" if "locker" in n and "seam" not in n else "seam" if "seam" in n else
               "mullion" if "mullion" in n else "window_top" if "window_top" in n else "ceiling" if n == "ceiling" else
               "floor" if "floor" in n else "left_wall" if "left_wall" in n else "window_wall" if "window_wall" in n else
               "door" if "door" in n else None)
        if key is None:
            kind = next((b["kind"] for b in boxes if b["obj"] == ob), "structure")
            key = "prop" if kind == "prop" else "structure"
        set_mat(ob, mats[key])
        if key not in ("seam",):
            add_outline(ob, 0.015)
    skin = toon_mat("skin", SKIN, shadow="#e08a8a")
    eye = toon_mat("eye", "#1d1730")
    for i, (name, rig) in enumerate(rigs.items()):
        hcol = tuple(job["actors"][name].get("color", (0.6, 0.6, 0.6)))
        # actor colour = hair hue; push saturation for anime look
        mx = max(hcol) or 1; hair = tuple(min(1, (c / mx) ** 1.6) for c in hcol)
        hair_m = toon_mat(f"{name}_hairm", "#%02x%02x%02x" % tuple(int(c * 255) for c in hair), shadow="#5a4c9a")
        cloth = toon_mat(f"{name}_cloth", UNIFORMS[i % len(UNIFORMS)])
        pants = toon_mat(f"{name}_pants", PANTS[i % len(PANTS)])
        shoe = toon_mat(f"{name}_shoe", "#3a2a22")
        for m in rig["meshes"]:
            part = m.name[len(name) + 1:]
            mat = (skin if part in ("Head", "nose", "Neck") or "Hand" in part or "ForeArm" in part else
                   shoe if "Foot" in part else pants if ("Leg" in part or part == "Hips") else cloth)
            set_mat(m, mat); add_outline(m, 0.008)
            for pg in m.data.polygons:
                pg.use_smooth = True
        head = next(m for m in rig["meshes"] if m.name.endswith("_Head"))
        hr = 0.062 * float(job["actors"][name].get("height_m", 1.7))
        hc = hair_cap(name, head, hr); set_mat(hc, hair_m)
        for pg in hc.data.polygons:
            pg.use_smooth = True
        add_outline(hc, 0.008)
        eyes(name, head, hr, eye)

    # lighting: one fixed key sun + flat sky gradient (camera rays only)
    sun = bpy.data.lights.new("key", "SUN"); sun.energy = 2.2; sun.angle = math.radians(2)
    so = bpy.data.objects.new("key", sun); scene.collection.objects.link(so)
    so.rotation_euler = (math.radians(55), math.radians(0), math.radians(75))
    wt = scene.world.node_tree; wn = wt.nodes; wn.clear()
    wo = wn.new("ShaderNodeOutputWorld"); tc = wn.new("ShaderNodeTexCoord"); sep = wn.new("ShaderNodeSeparateXYZ")
    rp = wn.new("ShaderNodeValToRGB"); rp.color_ramp.elements[0].color = (*srgb("#bfe6ff"), 1)
    rp.color_ramp.elements[1].color = (*srgb("#2f7fe0"), 1)
    bgc = wn.new("ShaderNodeBackground"); bgl = wn.new("ShaderNodeBackground")
    bgl.inputs["Color"].default_value = (0.35, 0.35, 0.4, 1); bgl.inputs["Strength"].default_value = 0.6
    lp = wn.new("ShaderNodeLightPath"); ms = wn.new("ShaderNodeMixShader")
    wt.links.new(tc.outputs["Window"], sep.inputs[0]); wt.links.new(sep.outputs["Y"], rp.inputs[0])
    wt.links.new(rp.outputs["Color"], bgc.inputs["Color"])
    wt.links.new(lp.outputs["Is Camera Ray"], ms.inputs[0])
    wt.links.new(bgl.outputs[0], ms.inputs[1]); wt.links.new(bgc.outputs[0], ms.inputs[2])
    wt.links.new(ms.outputs[0], wo.inputs[0])

    if LINEART:
        try:
            bpy.ops.object.grease_pencil_add(type="LINEART_SCENE")
        except Exception:  # noqa: BLE001
            bpy.ops.object.gpencil_add(type="LINEART_SCENE")
        la = bpy.context.active_object
        for md in la.modifiers if hasattr(la, "modifiers") else []:
            if hasattr(md, "thickness"):
                md.thickness = 3
            if hasattr(md, "use_crease"):
                md.crease_threshold = math.radians(140)

    scene.render.engine = "BLENDER_EEVEE"
    ee = scene.eevee
    ee.taa_render_samples = SAMPLES
    for a, v in (("use_shadows", True), ("use_raytracing", False)):
        if hasattr(ee, a):
            setattr(ee, a, v)
    scene.view_settings.view_transform = "Standard"; scene.view_settings.look = "None"
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"
    build_s = time.time() - t0
    times = []
    for fr in range(1, NF + 1):
        t = time.time(); scene.frame_set(fr)
        scene.render.filepath = os.path.join(OUT, "frames", f"{fr:04d}.png")
        bpy.ops.render.render(write_still=True)
        times.append(time.time() - t)
        print(f"TOON_FRAME {fr}/{NF} {times[-1]:.2f}s", flush=True)
    info = {"job": JOB, "frames": NF, "fps": FPS, "res": [W, H], "samples": SAMPLES, "lineart": LINEART,
            "build_s": round(build_s, 2), "render_total_s": round(sum(times), 2),
            "per_frame_avg_s": round(sum(times) / len(times), 3), "per_frame_first_s": round(times[0], 2),
            "per_frame_avg_excl_first_s": round(sum(times[1:]) / max(1, len(times) - 1), 3),
            "blender": bpy.app.version_string}
    json.dump(info, open(os.path.join(OUT, "timing.json"), "w"), indent=1)
    print("TOON_DONE", json.dumps(info), flush=True)

if __name__ == "__main__":
    main()
