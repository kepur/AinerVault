"""Anime ACTION reference shot PoC (optional, not wired into any flow): rooftop parkour + fight, ~5 s.

    Blender -b --factory-startup --python action_rooftop_poc.py -- <out_dir> [--style modern_anime] [--res 1920x1152]
        [--samples 32] [--range A:B] [--still F,..] [--passes]

Set: two rooftops with an alley gap and a tall side building (wall-run surface), water tank, AC boxes, rails.
Cast: kyle (blond, hero) and tyler (red) VRMs from toon_vrm_poc (CC0/VRoid sample models), styled with
anime_npr_poc (MToon + face proxy normals + compositor lines/bloom/grade).
Motion: hand-keyed (no mocap): run cycle -> anticipation crouch -> leap -> horizontal wall-run -> kick-off flip ->
land (squash) -> punch / duck -> spinning kick -> IMPACT -> knock-back. Anime timing: holds and fast transitions,
smear frames (stretch along velocity), radial speed lines parented to the camera, impact flash (post).
Camera: low-angle tracking, whip pans, push-in + shake at impact.
"""
import math, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
_a = sys.argv[sys.argv.index("--") + 1:]
sys.argv[sys.argv.index("--") + 1:] = ["<no-job>"] + _a        # toon_vrm_poc expects <job> <out>
import bpy  # noqa: E402
from mathutils import Vector, Euler, Matrix  # noqa: E402
import anime_npr_poc as npr  # noqa: E402
tv, tp = npr.tv, npr.tv.tp
OUT, argv, opt = npr.OUT, npr.argv, npr.opt
FPS, NF = 24, 120

# ---------------------------------------------------------------- set
SET = {  # name: (center, size, colour key)
    "roof1": ((-3.0, 0.0, 3.0), (10.0, 6.0, 6.0), "structure"),
    "roof2": ((10.0, 0.0, 3.75), (10.0, 7.0, 7.5), "left_wall"),
    "tower": ((3.5, 4.5, 6.0), (3.4, 3.0, 12.0), "window_wall"),
    "alley": ((3.5, 0.0, -0.05), (30.0, 20.0, 0.1), "floor"),
    "far_block": ((4.0, 14.0, 5.0), (30.0, 4.0, 10.0), "ceiling"),
    "tank": ((12.5, 2.2, 8.5), (1.6, 1.6, 2.0), "door"),
    "ac1": ((-4.5, -1.8, 6.35), (1.2, 0.8, 0.7), "prop"),
    "ac2": ((-1.0, 2.0, 6.3), (0.9, 0.9, 0.6), "prop"),
    "rail1": ((-3.0, -3.0, 7.0), (10.0, 0.06, 0.08), "mullion"),
    "rail2": ((10.0, -3.5, 8.5), (10.0, 0.06, 0.08), "mullion"),
    "stripe": ((3.5, 2.98, 7.0), (3.4, 0.04, 0.25), "lockers"),
}


def build_set(scene):
    tp.OUTLINE = tp.outline_mat()
    mats = {k: tp.toon_mat(f"env_{k}", v) for k, v in tp.ENV.items()}
    objs = []
    for n, (c, s, k) in SET.items():
        me = bpy.data.meshes.new(n)
        import bmesh
        bm = bmesh.new(); bmesh.ops.create_cube(bm, size=1.0)
        for v in bm.verts:
            v.co = Vector((v.co.x * s[0], v.co.y * s[1], v.co.z * s[2]))
        bm.to_mesh(me); bm.free()
        ob = bpy.data.objects.new(n, me); scene.collection.objects.link(ob); ob.location = c
        tp.set_mat(ob, mats[k]); tp.add_outline(ob, 0.03)
        objs.append(ob)
    return objs


# ---------------------------------------------------------------- poses (Mixamo-named armature-space deltas, deg)
# conventions (character faces -Y): +X on UpLeg = leg back, -X = leg forward; +X on Leg = knee bend;
# -X on Arm = arm forward/up; -X on ForeArm = elbow bend; +X on Spine = lean forward; Z = twist.
def P(**kw):
    out = {}
    for k, v in kw.items():
        out[k] = list(v) if isinstance(v, (list, tuple)) else [v, 0, 0]
    return out


def run_pose(ph, k=1.0, lean=14):
    s, c = math.sin(ph), math.cos(ph)
    return P(Spine=(lean * k, 0, 8 * s * k), Spine1=(4 * k, 0, 6 * s * k), Neck=(-lean * 0.6 * k, 0, -8 * s * k),
             Head=(-4, 0, -4 * s),
             LeftUpLeg=(-50 * s * k, 0, 0), RightUpLeg=(50 * s * k, 0, 0),
             LeftLeg=((60 + 40 * max(0, -c)) * k if s < 0 else 25 * k, 0, 0),
             RightLeg=((60 + 40 * max(0, c)) * k if s > 0 else 25 * k, 0, 0),
             LeftArm=(55 * s * k, -12, 0), RightArm=(-55 * s * k, 12, 0),
             LeftForeArm=(-85 * k, 0, 0), RightForeArm=(-85 * k, 0, 0))


CROUCH = P(Spine=(35, 0, 0), Spine1=(10, 0, 0), Neck=(-30, 0, 0), LeftUpLeg=(-95, 0, 0), RightUpLeg=(-70, 0, 0),
           LeftLeg=(120, 0, 0), RightLeg=(130, 0, 0), LeftFoot=(-20, 0, 0), RightFoot=(-30, 0, 0),
           LeftArm=(40, -25, 0), RightArm=(45, 25, 0), LeftForeArm=(-60, 0, 0), RightForeArm=(-60, 0, 0))
LEAP = P(Spine=(-10, 0, 0), Neck=(5, 0, 0), LeftUpLeg=(-70, 0, 0), RightUpLeg=(30, 0, 0), LeftLeg=(90, 0, 0),
         RightLeg=(40, 0, 0), LeftArm=(-150, -15, 0), RightArm=(40, 30, 0), LeftForeArm=(-20, 0, 0),
         RightForeArm=(-50, 0, 0))
TUCK = P(Spine=(50, 0, 0), Spine1=(20, 0, 0), Neck=(-10, 0, 0), LeftUpLeg=(-120, 0, 0), RightUpLeg=(-120, 0, 0),
         LeftLeg=(140, 0, 0), RightLeg=(140, 0, 0), LeftArm=(-60, -20, 0), RightArm=(-60, 20, 0),
         LeftForeArm=(-110, 0, 0), RightForeArm=(-110, 0, 0))
HERO_LAND = P(Spine=(30, 0, 10), Neck=(-35, 0, 0), LeftUpLeg=(-100, -10, 0), RightUpLeg=(10, 0, 0),
              LeftLeg=(110, 0, 0), RightLeg=(120, 0, 0), RightFoot=(40, 0, 0), LeftArm=(30, -60, 0),
              RightArm=(70, 10, 0), LeftForeArm=(-30, 0, 0), RightForeArm=(-10, 0, 0))
GUARD = P(Spine=(8, 0, -25), Neck=(-8, 0, 20), LeftUpLeg=(-25, 0, 0), RightUpLeg=(15, 0, 0), LeftLeg=(30, 0, 0),
          RightLeg=(25, 0, 0), LeftArm=(-75, -10, 30), RightArm=(-55, 10, -30), LeftForeArm=(-120, 0, 0),
          RightForeArm=(-130, 0, 0))
PUNCH_WIND = P(Spine=(10, 0, 35), Neck=(-10, 0, -30), LeftUpLeg=(-30, 0, 0), RightUpLeg=(20, 0, 0),
               LeftLeg=(35, 0, 0), RightLeg=(20, 0, 0), LeftArm=(-80, -10, 0), RightArm=(30, 30, 0),
               LeftForeArm=(-110, 0, 0), RightForeArm=(-140, 0, 0))
PUNCH = P(Spine=(15, 0, -40), Neck=(-15, 0, 35), LeftUpLeg=(-45, 0, 0), RightUpLeg=(30, 0, 0), LeftLeg=(30, 0, 0),
          RightLeg=(10, 0, 0), LeftArm=(-30, -20, 0), RightArm=(-92, 0, 0), LeftForeArm=(-120, 0, 0),
          RightForeArm=(-5, 0, 0))
DUCK = P(Spine=(45, 0, 15), Neck=(-40, 0, 0), LeftUpLeg=(-80, -15, 0), RightUpLeg=(-30, 15, 0), LeftLeg=(110, 0, 0),
         RightLeg=(100, 0, 0), LeftArm=(-70, -10, 30), RightArm=(-60, 10, -30), LeftForeArm=(-120, 0, 0),
         RightForeArm=(-130, 0, 0))
KICK = P(Spine=(-25, -30, 0), Neck=(20, 0, 0), RightUpLeg=(-10, -80, 0), RightLeg=(5, 0, 0), LeftUpLeg=(-10, 0, 0),
         LeftLeg=(20, 0, 0), LeftArm=(20, -70, 0), RightArm=(-20, 60, 0), LeftForeArm=(-40, 0, 0),
         RightForeArm=(-40, 0, 0))
HIT = P(Spine=(-35, 0, 20), Spine1=(-15, 0, 0), Neck=(30, 0, -20), Head=(15, 0, 0), LeftUpLeg=(-30, 0, 0),
        RightUpLeg=(-50, 0, 0), LeftLeg=(30, 0, 0), RightLeg=(50, 0, 0), LeftArm=(-120, -40, 0),
        RightArm=(-100, 50, 0), LeftForeArm=(-20, 0, 0), RightForeArm=(-30, 0, 0))
STAND = P(LeftArm=(0, -8, 0), RightArm=(0, 8, 0), LeftForeArm=(-15, 0, 0), RightForeArm=(-15, 0, 0))


def mix(a, b, t):
    keys = set(a) | set(b); z = [0, 0, 0]
    return {k: [x * (1 - t) + y * t for x, y in zip(a.get(k, z), b.get(k, z))] for k in keys}


def ease(t):
    return t * t * (3 - 2 * t)


# ---------------------------------------------------------------- choreography: per-frame (pos, yaw, roll, pitch, pose, smear)
def hero(fr):
    """kyle: run on roof1 (+X), leap to the tower wall (y=3), wall-run, kick-off flip onto roof2, fight."""
    Z1, Z2 = 6.0, 7.5
    if fr <= 18:                                      # run, accelerating
        t = (fr - 1) / 17; x = -6.0 + 7.0 * (t * 0.6 + 0.4 * t * t)
        return (x, -0.3, Z1 + 0.04 * abs(math.sin(fr * 0.9))), -90, 0, 0, run_pose(fr * 0.9, 1.0), 0
    if fr <= 22:                                      # anticipation: crouch at the edge (hold-ish)
        t = ease((fr - 18) / 4)
        return (1.0 + 0.2 * t, -0.3, Z1 - 0.25 * t), -90, 0, 0, mix(run_pose(16.2), CROUCH, t), 0
    if fr <= 34:                                      # leap toward the wall, rolling onto it
        t = (fr - 22) / 12
        x = 1.2 + 1.6 * t; y = -0.3 + 2.75 * ease(t); z = Z1 + 0.25 + 1.3 * math.sin(math.pi * t * 0.8)
        return (x, y, z), -90, 75 * ease(t), 0, mix(LEAP, run_pose(0, 0.7, 5), ease(t)), (1 if fr in (23, 24) else 0)
    if fr <= 54:                                      # wall-run along the tower side, slightly rising
        t = (fr - 34) / 20
        return (2.8 + 2.3 * t, 2.45, Z1 + 1.25 + 0.5 * t), -90, 75, 0, run_pose(fr * 1.1, 1.0, 5), 0
    if fr <= 70:                                      # kick off + forward flip, land on roof2
        t = (fr - 54) / 16
        x = 5.1 + 1.6 * t; y = 2.45 - 2.2 * ease(t); z = Z1 + 1.75 + 1.4 * math.sin(math.pi * t) - (Z1 + 1.75 - Z2) * t
        pose = mix(LEAP, TUCK, min(1, t * 2.5)) if t < 0.75 else mix(TUCK, HERO_LAND, (t - 0.75) * 4)
        return (x, y, z), -90, 75 * (1 - ease(min(1, t * 2))), -360 * ease(t), pose, (1 if fr in (55, 56) else 0)
    if fr <= 78:                                      # superhero landing hold (squash), then rise
        t = ease((fr - 70) / 8)
        return (6.7, 0.25, Z2 - 0.35 * (1 - t)), -90, 0, 0, mix(HERO_LAND, GUARD, t), 0
    if fr <= 86:
        return (6.7, 0.25, Z2), -90, 0, 0, GUARD, 0
    if fr <= 90:                                      # duck under the punch
        t = ease((fr - 86) / 4)
        return (6.7 - 0.1 * t, 0.25, Z2 - 0.3 * t), -90, 0, 0, mix(GUARD, DUCK, t), 0
    if fr <= 96:                                      # spinning roundhouse (fast), impact at 96
        t = (fr - 90) / 6
        return (6.75 + 0.35 * t, 0.25, Z2 - 0.3 * (1 - t)), -90 - 360 * ease(t) + 0, 0, 0, \
            mix(DUCK, KICK, min(1, t * 1.6)), (1 if fr in (93, 94) else 0)
    t = ease(min(1, (fr - 96) / 18))                  # follow-through, settle back to guard
    return (7.1, 0.25, Z2), -90, 0, 0, mix(KICK, GUARD, t), 0


def rival(fr):
    """tyler: waits on roof2, charges, punches (miss), eats the kick, knocked back."""
    Z2 = 7.5
    if fr <= 74:
        return (9.4, 0.3, Z2), 90, 0, 0, mix(STAND, GUARD, 0.5 + 0.5 * ease(min(1, max(0, (fr - 60) / 14)))), 0
    if fr <= 84:                                      # charge
        t = (fr - 74) / 10
        return (9.4 - 1.3 * ease(t), 0.3, Z2), 90, 0, 0, run_pose(fr * 1.0, 0.8, 18), 0
    if fr <= 87:                                      # wind-up (anticipation)
        return (8.1, 0.3, Z2), 90, 0, 0, mix(GUARD, PUNCH_WIND, ease((fr - 84) / 3)), 0
    if fr <= 92:                                      # punch (fast) + hold
        t = min(1, (fr - 87) / 2)
        return (8.1 - 0.3 * t, 0.3, Z2), 90, 0, 0, mix(PUNCH_WIND, PUNCH, t), (1 if fr == 88 else 0)
    if fr <= 96:
        return (7.8, 0.3, Z2), 90, 0, 0, mix(PUNCH, GUARD, ease((fr - 92) / 4) * 0.5), 0
    t = min(1, (fr - 96) / 20); k = 1 - (1 - t) ** 3   # knock-back slide, decelerating
    return (7.8 + 2.6 * k, 0.3 + 0.4 * k, Z2 + 0.25 * math.sin(math.pi * min(1, t * 2.5))), 90 - 25 * k, \
        0, -18 * (1 - t), HIT, (1 if fr in (97, 98) else 0)


# ---------------------------------------------------------------- camera (pos, target, lens) per frame + shake
def camera(fr, A, B):
    a = Vector(A); b = Vector(B)
    if fr <= 22:      # low-angle side tracking of the run
        return a + Vector((-1.8, -3.4, 0.45)), a + Vector((0.9, 0, 0.9)), 24
    if fr <= 34:      # whip pan up toward the wall
        t = ease((fr - 22) / 12)
        p0 = Vector((-0.6, -3.7, 6.5)); p1 = Vector((6.6, -0.2, 7.3))
        return p0.lerp(p1, t), a + Vector((0.6, 0, 0.6)), 26 - 4 * t
    if fr <= 54:      # ahead of the runner looking back along the wall: the 75deg wall-roll reads clearly
        return Vector((a.x + 3.6, 0.2, a.z + 0.2)), a + Vector((0, 0.2, 0.5)), 24
    if fr <= 72:      # wide low angle from roof2 for the flip
        t = ease((fr - 54) / 18)
        return Vector((9.2, -3.2, 7.9)).lerp(Vector((9.0, -2.6, 8.1)), t), a + Vector((0, 0, 0.6)), 22
    m = (a + b) / 2
    if fr <= 89:      # fight two-shot, low
        return m + Vector((-0.6, -3.6, 0.2)), m + Vector((0, 0, 1.05)), 30
    if fr <= 92:      # whip pan / push in on the kick
        t = ease((fr - 89) / 3)
        return (m + Vector((-0.6, -3.6, 0.2))).lerp(m + Vector((-0.7, -3.0, 0.1)), t), m + Vector((0.3, 0, 1.1)), 30 + 6 * t
    sh = Vector((0, 0, 0))
    if 96 <= fr <= 104:   # impact shake, decaying
        k = (105 - fr) / 9
        sh = Vector((0.06 * math.sin(fr * 7.1), 0.05 * math.sin(fr * 5.3), 0.06 * math.cos(fr * 6.7))) * k
    t = ease(min(1, max(0, (fr - 98) / 22)))
    return (m + Vector((-0.7, -3.0, 0.1))).lerp(m + Vector((-0.4, -4.4, 0.3)), t) + sh, m + Vector((0.4, 0, 1.0)), 36 - 10 * t


def speed_lines(cam):
    import bmesh
    import random
    r = random.Random(3)
    bm = bmesh.new()
    for i in range(46):
        ang = r.random() * 2 * math.pi; r0 = 0.30 + r.random() * 0.12; r1 = r0 + 0.25 + r.random() * 0.35
        w = 0.0025 + r.random() * 0.004
        d = Vector((math.cos(ang), math.sin(ang), 0)); n = Vector((-d.y, d.x, 0))
        vs = [bm.verts.new(p) for p in (d * r0, d * r1 + n * w, d * r1 - n * w)]
        bm.faces.new(vs)
    me = bpy.data.meshes.new("speed_lines"); bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.new("speed_lines", me); bpy.context.scene.collection.objects.link(ob)
    ob.parent = cam; ob.location = (0, 0, -0.5)
    m = bpy.data.materials.new("speed_line_mat"); m.use_nodes = True
    N = m.node_tree.nodes; N.clear(); o = N.new("ShaderNodeOutputMaterial"); e = N.new("ShaderNodeEmission")
    e.inputs["Color"].default_value = (1, 1, 1, 1); e.inputs["Strength"].default_value = 1.2
    m.node_tree.links.new(e.outputs[0], o.inputs[0]); ob.data.materials.append(m)
    for a in ("visible_shadow",):
        setattr(ob, a, False)
    return ob


def main():
    os.makedirs(os.path.join(OUT, "frames"), exist_ok=True)
    preset = npr.load_preset(npr.STYLE); cs = npr.compile_style(preset)
    scene = tp.common.empty_scene()
    bpy.ops.preferences.addon_enable(module="bl_ext.user_default.vrm")
    r = scene.render; r.resolution_x, r.resolution_y, r.resolution_percentage, r.fps = npr.W, npr.H, 100, FPS
    scene.frame_start, scene.frame_end = 1, NF
    if scene.world is None:
        scene.world = bpy.data.worlds.new("World")
    import time
    t0 = time.time()
    build_set(scene)
    rigs = {"kyle": tv.setup_actor("kyle", {"height_m": 1.75}), "tyler": tv.setup_actor("tyler", {"height_m": 1.8, "build": "lanky"})}
    cd = bpy.data.cameras.new("cam"); cd.sensor_fit, cd.sensor_width = "HORIZONTAL", 36.0; cd.clip_start = 0.05
    cam = bpy.data.objects.new("cam", cd); scene.collection.objects.link(cam); scene.camera = cam
    sl = speed_lines(cam)
    for fr in range(1, NF + 1):
        st = {}
        for name, fn in (("kyle", hero), ("tyler", rival)):
            (pos, yaw, roll, pitch, pose, smear) = fn(fr)
            rig = rigs[name]; arm = rig["arm"]
            # yaw: VRM faces -Y at rest; yaw -90 => faces +X.  roll = lean onto the wall (about forward axis),
            # pitch = flip (about the character's right axis)
            R = (Matrix.Rotation(math.radians(yaw), 3, "Z") @ Matrix.Rotation(math.radians(roll), 3, "Y")
                 @ Matrix.Rotation(math.radians(pitch), 3, "X"))
            hip = Vector((0, 0, 0.9))
            arm.location = Vector(pos) + hip - R @ hip                   # rotate about the hips, not the feet
            arm.rotation_euler = R.to_euler("XYZ")
            s0 = rig.setdefault("s0", arm.scale.copy())
            sc = (1.0, 1.0 + 0.28 * smear, 1.0 - 0.08 * smear)       # smear: stretch along forward (-Y local)
            arm.scale = (s0.x * sc[0], s0.y * sc[1], s0.z * sc[2])
            arm.keyframe_insert("location", frame=fr); arm.keyframe_insert("rotation_euler", frame=fr)
            arm.keyframe_insert("scale", frame=fr)
            tv.pose_actor(rig, pose)
            for r_ in rig["rest"].values():
                arm.pose.bones[r_["bone"]].keyframe_insert("rotation_quaternion", frame=fr)
            st[name] = pos
        p, t, lens = camera(fr, st["kyle"], st["tyler"])
        cam.location = p; cam.rotation_euler = (t - p).to_track_quat("-Z", "Y").to_euler(); cd.lens = lens
        cam.keyframe_insert("location", frame=fr); cam.keyframe_insert("rotation_euler", frame=fr)
        cd.keyframe_insert("lens", frame=fr)
        fast = (23 <= fr <= 34) or (55 <= fr <= 68) or (91 <= fr <= 100)
        sl.hide_render = not fast; sl.keyframe_insert("hide_render", frame=fr)
    # constant interpolation for holds feel: keys every frame already; keep Bezier off (per-frame keys)
    for name, rig in rigs.items():
        seen = set()
        for ob in rig["meshes"]:
            for s_ in ob.material_slots:
                if s_.material and s_.material.name not in seen:
                    seen.add(s_.material.name); npr.style_mtoon(s_.material, cs, "FACE_00_SKIN" in s_.material.name.upper())
        npr.face_normal_proxy(rig, cs["face_normal_proxy_mix"])
    for m in bpy.data.materials:
        if m.name.startswith("env_") and m.node_tree:
            npr.add_aovs_env(m)
    sun = bpy.data.lights.new("key", "SUN"); sun.energy = cs["light"]["key_energy"]; sun.angle = math.radians(2)
    so = bpy.data.objects.new("key", sun); scene.collection.objects.link(so)
    so.rotation_euler = (math.radians(40), 0, math.radians(-35))        # late-afternoon key from camera side-left
    if cs["light"]["back_rim_energy"] > 0:
        d = bpy.data.lights.new("rim", "SUN"); d.energy = cs["light"]["back_rim_energy"]; d.color = (1, 0.82, 0.66)
        o = bpy.data.objects.new("rim", d); scene.collection.objects.link(o); o.rotation_euler = (math.radians(70), 0, math.radians(150))
    wt = scene.world.node_tree; wn = wt.nodes; wn.clear()
    wo = wn.new("ShaderNodeOutputWorld"); tc = wn.new("ShaderNodeTexCoord"); sep = wn.new("ShaderNodeSeparateXYZ")
    rp = wn.new("ShaderNodeValToRGB"); rp.color_ramp.elements[0].color = (*tp.srgb("#ffd6a0"), 1)
    rp.color_ramp.elements[1].color = (*tp.srgb("#3a6fd8"), 1)
    bgc = wn.new("ShaderNodeBackground"); bgl = wn.new("ShaderNodeBackground")
    bgl.inputs["Color"].default_value = (0.45, 0.42, 0.48, 1); bgl.inputs["Strength"].default_value = cs["light"]["ambient"]
    lp = wn.new("ShaderNodeLightPath"); ms = wn.new("ShaderNodeMixShader")
    wt.links.new(tc.outputs["Window"], sep.inputs[0]); wt.links.new(sep.outputs["Y"], rp.inputs[0])
    wt.links.new(rp.outputs["Color"], bgc.inputs["Color"]); wt.links.new(lp.outputs["Is Camera Ray"], ms.inputs[0])
    wt.links.new(bgl.outputs[0], ms.inputs[1]); wt.links.new(bgc.outputs[0], ms.inputs[2]); wt.links.new(ms.outputs[0], wo.inputs[0])
    scene.render.engine = "BLENDER_EEVEE"; scene.eevee.taa_render_samples = npr.tv.SAMPLES
    scene.view_settings.view_transform = "Standard"; scene.render.image_settings.file_format = "PNG"
    npr.compositor(scene, cs, os.path.join(OUT, "passes") if npr.PASSES else None)
    stills = [int(x) for x in opt("--still", "").split(",") if x]
    if stills:
        rng = stills
    elif "--range" in argv:
        a, b = map(int, opt("--range", "1:1").split(":")); rng = list(range(a, b + 1))
    else:
        rng = list(range(1, NF + 1))
    ctx = {"scene": scene, "NF": NF, "t0": t0}
    tv.STILL = None
    info = tv.render_frames(ctx, rng, tag="ACT")
    import json
    info.update({"style": cs["name"], "shot": "action_rooftop", "motion": "hand-keyed procedural"})
    json.dump(info, open(os.path.join(OUT, "timing.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
