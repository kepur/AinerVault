"""生成 Unreal Python：建 Level Sequence —— 机位（CineCameraActor）逐帧变换与焦距、剪辑轨、人物位移轨、动作段。"""
from __future__ import annotations

import json
from typing import Any

TEMPLATE = '''# Ainer Director · 建序列与机位（由 ainer-core 生成，勿手改）
import json
import unreal

SEQ = json.loads({seq!r})
CAMS = json.loads({cams!r})
tools = unreal.AssetToolsHelpers.get_asset_tools()
actors_sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
seq = tools.create_asset(SEQ["name"], SEQ["root"], unreal.LevelSequence, unreal.LevelSequenceFactoryNew())
seq.set_display_rate(unreal.FrameRate(SEQ["fps"], 1))
seq.set_playback_start(0)
seq.set_playback_end(SEQ["frames"])


def fnum(i):
    return unreal.FrameNumber(i)


def key_transform(binding, keys):
    track = binding.add_track(unreal.MovieScene3DTransformTrack)
    sec = track.add_section()
    sec.set_range(0, SEQ["frames"])
    ch = sec.get_all_channels()          # 位置 xyz、旋转 roll/pitch/yaw、缩放 xyz
    for k in keys:
        loc, r = k["location"], k["rotation"]
        vals = [loc[0], loc[1], loc[2], r["Roll"], r["Pitch"], r["Yaw"]]
        if "scale" in k:
            vals += k["scale"]
        for c, v in zip(ch, vals):
            c.add_key(fnum(k["frame"]), v)


# 人物、车辆的位移
by_label = {{a.get_actor_label(): a for a in actors_sub.get_all_level_actors()}}
for oid, keys in SEQ["transforms"].items():
    actor = by_label.get("ainer_" + oid)
    if actor is not None:
        key_transform(seq.add_possessable(actor), keys)

# 机位
cam_bindings = {{}}
for cid, cam in CAMS["cameras"].items():
    actor = actors_sub.spawn_actor_from_class(unreal.CineCameraActor, unreal.Vector(0, 0, 0))
    actor.set_actor_label("ainer_cam_" + cid)
    comp = actor.get_cine_camera_component()
    fb = comp.filmback
    fb.sensor_width, fb.sensor_height = cam["filmback_mm"]
    comp.filmback = fb
    b = seq.add_possessable(actor)
    key_transform(b, cam["keys"])
    ctrack = b.add_track(unreal.MovieSceneFloatTrack)
    ctrack.set_property_name_and_path("CurrentFocalLength", "CineCameraComponent.CurrentFocalLength")
    csec = ctrack.add_section()
    csec.set_range(0, SEQ["frames"])
    for k in cam["keys"]:
        csec.get_all_channels()[0].add_key(fnum(k["frame"]), k["focal_length"])
    cam_bindings[cid] = b

# 剪辑轨
cut_track = seq.add_master_track(unreal.MovieSceneCameraCutTrack)
for c in CAMS["cuts"]:
    s = cut_track.add_section()
    s.set_range(c["start_frame"], c["end_frame"])
    b = cam_bindings.get(c["camera"])
    if b is not None:
        s.set_camera_binding_id(seq.get_binding_id(b))

# 动作段：语义动作 → 动画资产片段（资产不存在时只记日志）
for a in SEQ["animations"]:
    actor = by_label.get("ainer_" + a["actor"])
    anim = unreal.EditorAssetLibrary.load_asset(a["anim_asset"]) if a.get("anim_asset") else None
    if actor is None or anim is None:
        unreal.log_warning("动作 %s 没有对应的动画资产 %s" % (a["action"], a.get("anim_asset")))
        continue
    b = seq.add_possessable(actor.skeletal_mesh_component) if hasattr(actor, "skeletal_mesh_component") else seq.add_possessable(actor)
    t = b.add_track(unreal.MovieSceneSkeletalAnimationTrack)
    s = t.add_section()
    s.set_range(a["start_frame"], a["end_frame"])
    s.params.animation = anim

unreal.EditorAssetLibrary.save_loaded_asset(seq)
unreal.log("Ainer：序列 %s 建好（%d 帧，%d 台机位）" % (SEQ["name"], SEQ["frames"], len(cam_bindings)))
'''


def generate(sequence_plan: dict[str, Any], camera_plan: dict[str, Any]) -> str:
    return TEMPLATE.format(seq=json.dumps(sequence_plan, ensure_ascii=False), cams=json.dumps(camera_plan, ensure_ascii=False))
