"""Anime NPR PoC on top of toon_vrm_poc (VRM/MToon characters in the world greybox take). Optional, not wired
into any flow.

    Blender -b --factory-startup --python anime_npr_poc.py -- <job.json> <out_dir> --style classic_cel|modern_anime|<preset.json>
        [--cam take|closeup] [--res 1920x1152] [--samples 32] [--frames N] [--range A:B] [--still F[,F..]] [--passes]

"Anime Style Compiler": a JSON style preset (anime_styles/*.json, artist-facing units: px line widths, band
softness, degrees, hex colours) is compiled into concrete MToon material params, light rig, ray visibility,
view-layer passes/AOVs and a compositor node graph; the compiled result is written to <out>/style_compiled.json.

NPR techniques (own implementation, no third-party shader code copied):
  * face normal editing: per-head ellipsoid proxy (follows the head bone) -> Data Transfer custom normals onto
    the face skin, mixed by `face_normal_proxy` (the Guilty Gear / "proxy sphere normals" technique) -> clean,
    readable face shadow shapes instead of noisy per-vertex terminator.
  * clean 2-band cel shading (MToon toony factor from band_softness) + shade tint, parametric (fresnel) rim
    light, optional real back-rim sun.
  * outlines: MToon inverted hull in screen space (px -> fraction of screen height);
    inner lines: compositor edge detection on Normal + log-Depth passes (creases, overlaps, hair strands).
  * multi-pass: Combined, Depth, Normal + AOVs base (albedo texture), light (2-band light factor), line mask;
    `--passes` writes them per still frame via a compositor File Output node.
  * post: bloom (Glare), lift/gamma/gain warm grade, saturation.
"""
import json, math, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
if "--res" not in sys.argv:
    sys.argv += ["--res", "1920x1152"]
if "--samples" not in sys.argv:
    sys.argv += ["--samples", "32"]
import bpy  # noqa: E402
import bmesh  # noqa: E402
from mathutils import Vector, Matrix  # noqa: E402
import toon_vrm_poc as tv  # noqa: E402

argv, opt = tv.argv, tv.opt
JOB, OUT = tv.JOB, tv.OUT
W, H, FPS = tv.W, tv.H, tv.FPS
STYLE = opt("--style", "modern_anime")
CAM = opt("--cam", "take")
PASSES = "--passes" in argv


def hexc(h, lin=True):
    h = h.lstrip("#"); c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return [((x / 12.92) if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4) for x in c] if lin else c


# ---------------------------------------------------------------- style compiler
def compile_style(preset):
    L, S, R, Li, P = preset["lines"], preset["shading"], preset["rim"], preset["light"], preset["post"]
    return {
        "name": preset["name"],
        "mtoon": {
            "toony": round(1.0 - float(S["band_softness"]), 3),                 # MToon shadingToony
            "shift": float(S["shadow_shift"]), "face_shift": float(S["face_shadow_shift"]),
            "shade_color": hexc(S["shade_tint"]), "gi_equalization": float(S["gi_equalization"]),
            "rim_color": [float(R["strength"]) * c for c in hexc(R["color"])], "rim_power": float(R["power"]),
            "rim_lift": float(R["lift"]), "rim_mix": 0.7 if R["strength"] > 0 else 0.0,
            "outline_mode": "screenCoordinates",
            "outline_width": round(float(L["outline_px"]) / H, 6),            # fraction of screen height
            "face_outline_width": round(float(L["face_outline_px"]) / H, 6),
            "outline_color": hexc(L["color"]),
        },
        "face_normal_proxy_mix": float(S["face_normal_proxy"]),
        "light": {"key_energy": Li["key_energy"], "key_rot_deg": [90 - Li["key_elevation_deg"], 0, Li["key_azimuth_deg"]],
                  "key_angle_deg": Li["key_softness_deg"], "ambient": Li["ambient"], "back_rim_energy": Li["back_rim_energy"]},
        "compositor": {
            "inner_lines": float(L["inner_lines"]), "normal_thr": float(L["inner_normal_threshold"]),
            "depth_thr": float(L["inner_depth_threshold"]), "thick_px": int(L["inner_thickness_px"]),
            "line_color": hexc(L["color"]),
            "bloom": float(P["bloom"]), "bloom_threshold": float(P["bloom_threshold"]),
            "saturation": float(P["saturation"]), "gain": hexc(P["gain"], lin=False), "lift": hexc(P["lift"], lin=False),
            "gamma": float(P["gamma"]),
        },
        "lineart": L.get("lineart"),
        "passes": ["combined", "base(AOV)", "light(AOV)", "line", "depth", "normal"],
    }


def load_preset(s):
    p = s if s.endswith(".json") else os.path.join(HERE, "anime_styles", s + ".json")
    return json.load(open(p, encoding="utf-8"))


# ---------------------------------------------------------------- materials
def add_aovs_mtoon(mat):
    nt = mat.node_tree; N, Lk = nt.nodes, nt.links
    if "npr_aov_base" in N:
        return
    tex = N.get("Mtoon1BaseColorTexture.Image")
    a = N.new("ShaderNodeOutputAOV"); a.name = "npr_aov_base"; a.aov_name = "base"
    if tex is not None:
        Lk.new(tex.outputs["Color"], a.inputs["Color"])
    d = N.new("ShaderNodeBsdfDiffuse"); s2r = N.new("ShaderNodeShaderToRGB"); bw = N.new("ShaderNodeRGBToBW")
    nm = N.get("Normal Map")
    if nm is not None:
        Lk.new(nm.outputs["Normal"], d.inputs["Normal"])
    b = N.new("ShaderNodeOutputAOV"); b.aov_name = "light"
    Lk.new(d.outputs[0], s2r.inputs[0]); Lk.new(s2r.outputs["Color"], bw.inputs[0]); Lk.new(bw.outputs[0], b.inputs["Value"])


def add_aovs_env(mat):
    nt = mat.node_tree; N, Lk = nt.nodes, nt.links
    if "npr_aov_base" in N:
        return
    mix = next((n for n in N if n.type == "MIX"), None); ramp = next((n for n in N if n.type == "VALTORGB"), None)
    a = N.new("ShaderNodeOutputAOV"); a.name = "npr_aov_base"; a.aov_name = "base"
    if mix is not None:
        if mix.inputs[6].is_linked:
            Lk.new(mix.inputs[6].links[0].from_socket, a.inputs["Color"])
        else:
            a.inputs["Color"].default_value = mix.inputs[6].default_value
    if ramp is not None:
        b = N.new("ShaderNodeOutputAOV"); b.aov_name = "light"; bw = N.new("ShaderNodeRGBToBW")
        Lk.new(ramp.outputs["Color"], bw.inputs[0]); Lk.new(bw.outputs[0], b.inputs["Value"])


def style_mtoon(mat, cs, is_face):
    mt = tv.mtoon(mat)
    if mt is None:
        return
    m = cs["mtoon"]; mx = mt.extensions.vrmc_materials_mtoon
    mx.shading_toony_factor = m["toony"]
    mx.shading_shift_factor = m["face_shift"] if is_face else m["shift"]
    mx.gi_equalization_factor = m["gi_equalization"]
    mx.shade_color_factor = tuple(m["shade_color"])
    mx.parametric_rim_color_factor = tuple(m["rim_color"])
    mx.parametric_rim_fresnel_power_factor = m["rim_power"]
    mx.parametric_rim_lift_factor = m["rim_lift"]
    mx.rim_lighting_mix_factor = m["rim_mix"]
    n = mat.name.upper()
    if mt.alpha_mode == "OPAQUE" or any(k in n for k in ("CLOTH", "SKIN", "HAIR")):
        mx.outline_width_mode = m["outline_mode"]
        mx.outline_width_factor = m["face_outline_width"] if is_face else m["outline_width"]
        mx.outline_color_factor = tuple(m["outline_color"])
        mx.outline_lighting_mix_factor = 0.0
    add_aovs_mtoon(mat)


def face_normal_proxy(rig, mix):
    """Ellipsoid proxy parented to the head bone; Data Transfer custom normals onto face-skin vertices."""
    arm = rig["arm"]
    face = next((o for o in rig["meshes"] if any(s.material and "FACE_00_SKIN" in s.material.name.upper()
                                                 for s in o.material_slots)), None)
    hb = rig["rest"].get("Head")
    if face is None or hb is None:
        return None
    me = face.data
    idx = [i for i, s in enumerate(face.material_slots) if s.material and "FACE_00_SKIN" in s.material.name.upper()]
    vs = sorted({v for p in me.polygons if p.material_index in idx for v in p.vertices})
    mw = face.matrix_world
    co = [mw @ me.vertices[i].co for i in vs]
    lo = Vector([min(c[k] for c in co) for k in range(3)]); hi = Vector([max(c[k] for c in co) for k in range(3)])
    ctr = (lo + hi) / 2; ext = (hi - lo) / 2
    ctr.y += ext.y * 0.35                           # face points -Y: push centre back -> smooth convex front
    ctr.z -= ext.z * 0.05
    bm = bmesh.new(); bmesh.ops.create_uvsphere(bm, u_segments=48, v_segments=32, radius=1.0)
    for v in bm.verts:
        v.co = Vector((v.co.x * ext.x * 1.15, v.co.y * ext.y * 1.4, v.co.z * ext.z * 1.25))
    pm = bpy.data.meshes.new(f"{arm.name}_face_proxy"); bm.to_mesh(pm); bm.free()
    for p in pm.polygons:
        p.use_smooth = True
    px = bpy.data.objects.new(pm.name, pm); face.users_collection[0].objects.link(px)
    px.parent, px.parent_type, px.parent_bone = arm, "BONE", hb["bone"]
    bpy.context.view_layer.update()
    px.matrix_world = Matrix.Translation(ctr)
    for a in ("visible_camera", "visible_shadow", "visible_diffuse", "visible_glossy", "visible_transmission",
              "visible_volume_scatter"):
        if hasattr(px, a):
            setattr(px, a, False)
    px.display_type = "WIRE"
    vg = face.vertex_groups.new(name="npr_face_skin"); vg.add(vs, 1.0, "REPLACE")
    md = face.modifiers.new("npr_face_normals", "DATA_TRANSFER")
    md.object = px; md.use_loop_data = True; md.data_types_loops = {"CUSTOM_NORMAL"}
    md.loop_mapping = "POLYINTERP_NEAREST"; md.mix_mode = "REPLACE"; md.mix_factor = mix
    md.vertex_group = vg.name
    i = list(face.modifiers).index(md)
    target = next((k + 1 for k, m in enumerate(face.modifiers) if m.type == "ARMATURE"), 0)
    try:
        face.modifiers.move(i, target)
    except Exception:  # noqa: BLE001
        with bpy.context.temp_override(object=face):
            bpy.ops.object.modifier_move_to_index(modifier=md.name, index=target)
    return px


# ---------------------------------------------------------------- lights / camera
def _sun_euler(h, elev_deg):
    """Euler for a sun whose light travels along horizontal direction h, elev_deg above the horizon."""
    return (math.radians(90 - elev_deg), 0, math.atan2(-h.x, h.y))


def lights(ctx, cs):
    """Key azimuth is CAMERA-RELATIVE (0 = light travels along the view direction, i.e. from behind the camera),
    so whatever the camera sees (backs in the take, faces in the close-up) is lit by the key, not in shade."""
    L = cs["light"]; sun = ctx["sun"]; scene = ctx["scene"]
    scene.frame_set(max(1, ctx["NF"] // 2)); cam = ctx["cam"]
    f = cam.matrix_world.to_3x3() @ Vector((0, 0, -1)); f.z = 0; f.normalize()
    h = Matrix.Rotation(math.radians(L["key_rot_deg"][2]), 3, "Z") @ f
    # interior shell (ceiling / window header / walls) casts no key shadow: anime keeps characters consistently lit
    for o in ctx["env_objs"]:
        if any(k in o.name for k in ("ceiling", "window_top", "left_wall", "window_wall", "mullion")):
            o.visible_shadow = False
    sun.data.energy = L["key_energy"]; sun.data.angle = math.radians(L["key_angle_deg"])
    sun.rotation_euler = _sun_euler(h, 90 - L["key_rot_deg"][0])
    for n in scene.world.node_tree.nodes:
        if n.type == "BACKGROUND" and n.inputs["Strength"].default_value < 1.0 and n.inputs["Color"].default_value[2] < 0.6:
            n.inputs["Strength"].default_value = L["ambient"]
    if L["back_rim_energy"] > 0:
        d = bpy.data.lights.new("back_rim", "SUN"); d.energy = L["back_rim_energy"]; d.angle = math.radians(2)
        d.color = (1.0, 0.86, 0.72)
        o = bpy.data.objects.new("back_rim", d); scene.collection.objects.link(o)
        o.rotation_euler = _sun_euler(-h, 15)


def closeup_camera(ctx, who=("brad", "kyle"), dist=2.2, side=0.7, lens=40):
    """Front 3/4 two-shot that travels ahead of the walkers (they walk +X down the corridor)."""
    cam = ctx["cam"]; cd = cam.data; scene = ctx["scene"]
    cam.animation_data_clear(); cd.animation_data_clear()
    cd.lens = lens
    for fr in range(1, ctx["NF"] + 1):
        scene.frame_set(fr)
        heads = []
        for n in who:
            rig = ctx["rigs"][n]; pb = rig["arm"].pose.bones[rig["rest"]["Head"]["bone"]]
            heads.append(rig["arm"].matrix_world @ pb.head)
        c = sum(heads, Vector()) / len(heads)
        pos = Vector((c.x + dist, c.y + side, c.z + 0.05))
        tgt = Vector((c.x, c.y, c.z - 0.12))
        cam.location = pos; cam.rotation_euler = (tgt - pos).to_track_quat("-Z", "Y").to_euler()
        cam.keyframe_insert("location", frame=fr); cam.keyframe_insert("rotation_euler", frame=fr)
    for fc in (cam.animation_data.action.fcurves if hasattr(cam.animation_data.action, "fcurves") else []):
        for k in fc.keyframe_points:
            k.interpolation = "LINEAR"


# ---------------------------------------------------------------- compositor
def compositor(scene, cs, pass_dir=None):
    C = cs["compositor"]
    vl = scene.view_layers[0]
    vl.use_pass_z = True; vl.use_pass_normal = True
    for nm, ty in (("base", "COLOR"), ("light", "VALUE")):
        if nm not in vl.aovs:
            a = vl.aovs.add(); a.name = nm; a.type = ty
    ng = bpy.data.node_groups.new("npr_comp", "CompositorNodeTree")
    scene.compositing_node_group = ng
    N, Lk = ng.nodes, ng.links
    ng.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    rl = N.new("CompositorNodeRLayers"); rl.scene = scene
    go = N.new("NodeGroupOutput")

    def math(op, a, b=None, clamp=False):
        n = N.new("ShaderNodeMath"); n.operation = op; n.use_clamp = clamp
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                n.inputs[i].default_value = v
            else:
                Lk.new(v, n.inputs[i])
        return n.outputs[0]

    def sobel(sock):
        f = N.new("CompositorNodeFilter"); f.inputs["Type"].default_value = "Sobel"
        Lk.new(sock, f.inputs["Image"]); return f.outputs[0]

    def chans_max(col):
        sp = N.new("CompositorNodeSeparateColor"); Lk.new(col, sp.inputs[0])
        return math("MAXIMUM", math("MAXIMUM", sp.outputs[0], sp.outputs[1]), sp.outputs[2])

    # inner lines: normal discontinuities + log-depth discontinuities
    ne = chans_max(sobel(rl.outputs["Normal"]))
    nl = math("MULTIPLY", math("SUBTRACT", ne, C["normal_thr"]), 6.0, clamp=True)
    ld = math("LOGARITHM", math("MAXIMUM", rl.outputs["Depth"], 0.05), 2.718281828)
    de = chans_max(sobel(ld))
    dl = math("MULTIPLY", math("SUBTRACT", de, C["depth_thr"]), 8.0, clamp=True)
    line = math("MAXIMUM", nl, dl, clamp=True)
    if C["thick_px"] > 0:
        di = N.new("CompositorNodeDilateErode"); di.inputs["Size"].default_value = C["thick_px"]
        Lk.new(line, di.inputs["Mask"]); line = di.outputs[0]
    lf = math("MULTIPLY", line, C["inner_lines"], clamp=True)
    mixl = N.new("ShaderNodeMix"); mixl.data_type = "RGBA"; mixl.blend_type = "MIX"
    Lk.new(lf, mixl.inputs["Factor"]); Lk.new(rl.outputs["Image"], mixl.inputs[6])
    mixl.inputs[7].default_value = (*C["line_color"], 1)
    img = mixl.outputs[2]
    if C["bloom"] > 0:
        g = N.new("CompositorNodeGlare"); g.inputs["Type"].default_value = "Bloom"
        g.inputs["Quality"].default_value = "Medium"
        g.inputs["Threshold"].default_value = C["bloom_threshold"]; g.inputs["Strength"].default_value = C["bloom"]
        if "Size" in g.inputs:
            g.inputs["Size"].default_value = 0.6 if g.inputs["Size"].type == "VALUE" else g.inputs["Size"].default_value
        Lk.new(img, g.inputs["Image"]); img = g.outputs["Image"]
    cb = N.new("CompositorNodeColorBalance")
    try:
        cb.inputs["Type"].default_value = "Lift/Gamma/Gain"
    except Exception:  # noqa: BLE001
        pass
    lift_i = [s for s in cb.inputs if s.name == "Lift"]; gain_i = [s for s in cb.inputs if s.name == "Gain"]
    gam_i = [s for s in cb.inputs if s.name == "Gamma"]
    # Lift/Gamma/Gain sockets come as (colour, ...) pairs; set the colour ones
    for socks, val in ((lift_i, [1 + x for x in C["lift"]]), (gain_i, C["gain"]), (gam_i, [C["gamma"]] * 3)):
        for s_ in socks:
            if s_.type == "RGBA":
                s_.default_value = (*val, 1)
    Lk.new(img, cb.inputs["Image"]); img = cb.outputs[0]
    hs = N.new("CompositorNodeHueSat"); hs.inputs["Saturation"].default_value = C["saturation"]
    Lk.new(img, hs.inputs["Image"]); img = hs.outputs[0]
    Lk.new(img, go.inputs[0])
    if pass_dir:
        fo = N.new("CompositorNodeOutputFile"); fo.directory = pass_dir; fo.file_name = ""
        try:
            fo.format.media_type = "IMAGE"; fo.format.file_format = "PNG"
        except Exception:  # noqa: BLE001
            fo.format.file_format = "OPEN_EXR_MULTILAYER"
        dn = N.new("CompositorNodeNormalize"); Lk.new(rl.outputs["Depth"], dn.inputs[0])
        nm = N.new("ShaderNodeVectorMath"); nm.operation = "MULTIPLY_ADD"
        Lk.new(rl.outputs["Normal"], nm.inputs[0]); nm.inputs[1].default_value = (0.5, 0.5, 0.5)
        nm.inputs[2].default_value = (0.5, 0.5, 0.5)
        inv = math("SUBTRACT", 1.0, line)
        for name, sock, typ in (("combined_raw", rl.outputs["Image"], "RGBA"), ("base", rl.outputs["base"], "RGBA"),
                                ("light", rl.outputs["light"], "FLOAT"), ("line", inv, "FLOAT"),
                                ("depth", dn.outputs[0], "FLOAT"), ("normal", nm.outputs[0], "VECTOR"),
                                ("final", img, "RGBA")):
            it = fo.file_output_items.new(typ, name)
            Lk.new(sock, fo.inputs[it.name])

        def _per_frame_dir(sc, *_a):   # one sub-folder per frame: passes/fNNNN/<pass>.png
            fo.directory = os.path.join(pass_dir, f"f{sc.frame_current:04d}")
        bpy.app.handlers.frame_change_post.append(_per_frame_dir)
    return ng


def lineart(ctx, la):
    """Grease Pencil Line Art over the characters only: contour + crease + material borders + intersections.
    World-space radius => naturally thinner with depth (variable width); thickness modifier tapers stroke ends."""
    coll = bpy.data.collections.new("npr_chars"); ctx["scene"].collection.children.link(coll)
    for rig in ctx["rigs"].values():
        for ob in rig["meshes"]:
            coll.objects.link(ob)
            # face: occludes lines but draws none (its eye/mouth material borders and UV seams read as scars);
            # the MToon hull outline still draws the face silhouette
            if any(s_.material and "FACE_00_SKIN" in s_.material.name.upper() for s_ in ob.material_slots):
                ob.lineart.usage = "OCCLUSION_ONLY"
    bpy.ops.object.grease_pencil_add(type="LINEART_SCENE")
    gp = bpy.context.active_object; md = gp.modifiers[0]
    md.source_type = "COLLECTION"; md.source_collection = coll
    md.use_contour = md.use_crease = md.use_material = md.use_intersection = True
    md.use_loose = False
    md.crease_threshold = math.radians(la["crease_deg"]); md.radius = la["radius_m"]; md.opacity = la["opacity"]
    md.use_crease_on_smooth = True
    for m in gp.data.materials:
        if m and m.grease_pencil:
            m.grease_pencil.color = (0.02, 0.015, 0.02, 1)
    try:
        th = gp.modifiers.new("taper", "GREASE_PENCIL_THICKNESS")
        th.use_uniform_thickness = False
        th.thickness_factor = 1.0
        if hasattr(th, "use_custom_curve"):
            th.use_custom_curve = True
            c = th.custom_curve; c.initialize()
            pts = c.curves[0].points
            pts[0].location = (0, 1 - la["taper"]); pts[-1].location = (1, 1 - la["taper"])
            pts.new(0.5, 1.0); c.update()
    except Exception as e:  # noqa: BLE001
        print("NPR lineart taper skipped:", e)
    return gp


# ---------------------------------------------------------------- main
def main():
    os.makedirs(OUT, exist_ok=True)
    preset = load_preset(STYLE); cs = compile_style(preset)
    json.dump({"preset": preset, "compiled": cs}, open(os.path.join(OUT, "style_compiled.json"), "w"), indent=1)
    ctx = tv.build_scene()
    scene = ctx["scene"]
    qa = tv.qa_motion(ctx["job"], scene, ctx["rigs"], ctx["NF"], FPS, os.path.join(OUT, "qa_motion.json"))
    if not qa["pass"] and "--allow-qa-fail" not in argv:
        raise SystemExit("QA_MOTION failed: " + "; ".join(qa["fail_reasons"]))
    for name, rig in ctx["rigs"].items():
        seen = set()
        for ob in rig["meshes"]:
            for sl in ob.material_slots:
                m = sl.material
                if m is None or m.name in seen:
                    continue
                seen.add(m.name); n = m.name.upper()
                style_mtoon(m, cs, is_face="FACE_00_SKIN" in n)
        if cs["face_normal_proxy_mix"] > 0:
            face_normal_proxy(rig, cs["face_normal_proxy_mix"])
    for m in bpy.data.materials:
        if m.name.startswith("env_") and m.node_tree:
            add_aovs_env(m)
    if CAM == "closeup":
        closeup_camera(ctx)
    lights(ctx, cs)
    if cs.get("lineart"):
        lineart(ctx, cs["lineart"])
    ee = scene.eevee
    for a_, v in (("use_shadows", True), ("shadow_resolution_scale", 1.0), ("shadow_ray_count", 2),
                  ("shadow_step_count", 8)):
        if hasattr(ee, a_):
            setattr(ee, a_, v)
    scene.render.film_transparent = False
    stills = [int(x) for x in opt("--still", "").split(",") if x]
    compositor(scene, cs, os.path.join(OUT, "passes") if PASSES else None)
    tv.STILL = None
    if stills:
        rng = stills
    elif "--range" in argv:
        a, b = map(int, opt("--range", "1:1").split(":")); rng = list(range(a, b + 1))
    else:
        rng = list(range(1, ctx["NF"] + 1))
    info = tv.render_frames(ctx, rng, tag="NPR")
    info.update({"style": cs["name"], "cam": CAM})
    json.dump(info, open(os.path.join(OUT, "timing.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
