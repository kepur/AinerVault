"""Blender 无头 worker：在 Blender 自带的 Python 里跑（import bpy），不引 app.* 任何模块。

这个包本身可以被 ainer-core 导入（只为了拿到路径和纯 Python 的小工具，比如 png）；
带 bpy 的模块只在 Blender 里导入。
"""
