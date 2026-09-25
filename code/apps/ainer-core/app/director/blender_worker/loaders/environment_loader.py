"""环境：世界背景（天光）、地面、灯光。颜色取自烘焙数据里的色板，与 3D-BOX 预览一致。"""
from __future__ import annotations

import bpy

from ..common import hex_rgb, look_rotation, material, new_object


def build_world(scene: bpy.types.Scene, env: dict) -> None:
    world = bpy.data.worlds.new("ainer world")
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    # 天光：用半球光的天空色做环境光（three 的 hemisphereLight 0.85），背景色另由 Film 之外的世界色给
    bg.inputs["Color"].default_value = (*hex_rgb(env.get("hemiSky") or env.get("bg") or "#cfdcea"), 1)
    bg.inputs["Strength"].default_value = 0.9 if env.get("sky") != "night" else 0.35
    world.color = hex_rgb(env.get("bg") or "#cfdcea")
    scene.world = world


def build_ground(env: dict, root, coll) -> bpy.types.Object:
    size = float(env.get("groundSize") or 120)
    me = bpy.data.meshes.new("ground")
    h = size / 2
    me.from_pydata([(-h, 0, -h), (h, 0, -h), (h, 0, h), (-h, 0, h)], [], [(0, 3, 2, 1)])
    me.update()
    me.materials.append(material(env.get("groundColor") or "#d9dce1"))
    return new_object("地面", me, root, coll)


def build_lights(lights: list[dict], root, coll) -> list[bpy.types.Object]:
    """sun 按方向（从光源指向地面）摆；point/spot 按位置。强度按 three 的量级换算成 Blender 的。"""
    out = []
    for lt in lights:
        kind = lt.get("kind")
        if kind == "ambient":
            continue                      # 环境光已经算在世界天光里
        color = hex_rgb(lt.get("color") or "#ffffff")
        if kind == "sun":
            data = bpy.data.lights.new(lt.get("name") or "sun", "SUN")
            data.energy = 3.0 * float(lt.get("intensity") or 1)
            data.angle = 0.05
            ob = new_object(lt.get("name") or "太阳", data, root, coll)
            d = lt.get("dir") or [-0.6, -1.4, -0.5]
            ob.rotation_mode = "QUATERNION"
            ob.rotation_quaternion = look_rotation((0, 0, 0), d)
            ob.location = (-d[0] * 50, -d[1] * 50, -d[2] * 50)
        else:
            data = bpy.data.lights.new(lt.get("name") or kind, "SPOT" if kind == "spot" else "POINT")
            data.energy = 400.0 * float(lt.get("intensity") or 1)
            if kind == "spot":
                data.spot_size = 1.2
                data.spot_blend = 0.5
            ob = new_object(lt.get("name") or kind, data, root, coll)
            at = lt.get("at") or [0, 3, 0]
            ob.location = at
            if kind == "spot":
                ob.rotation_mode = "QUATERNION"
                ob.rotation_quaternion = look_rotation(at, (at[0], 0, at[2]))
        data.color = color
        out.append(ob)
    return out
