"""坐标换算：Ainer（Y 向上、米、右手系、yaw 0 面向 +Z）→ Unreal（Z 向上、厘米、左手系、X 向前）。

推导：人面朝 +Z 时，他的右手在 -X（math.rightOf）；UE 里人面朝 +X 时右手在 +Y。
所以  UE.X = 我们的 Z（前）、UE.Y = -我们的 X（右）、UE.Z = 我们的 Y（上），再 ×100 变厘米。
这个映射的行列式是 -1 —— 正好把右手系翻成左手系。
朝向：我们的前方 (sin yaw, 0, cos yaw) 映射成 UE 的 (cos yaw, -sin yaw, 0)，所以 UE.Yaw = -yaw。
"""
from __future__ import annotations

import math

CM = 100.0


def location(p, scale: float = CM) -> list[float]:
    x, y, z = p
    return [round(z * scale, 3), round(-x * scale, 3), round(y * scale, 3)]


def yaw(deg: float) -> float:
    return round(-deg, 4)


def rotator(rot_deg) -> dict[str, float]:
    """物体欧拉角（我们只用 yaw）→ UE Rotator。俯仰、滚转按轴映射：绕我们 X 轴 → 绕 UE -Y 轴（Pitch），绕 Z → 绕 X（Roll）。"""
    rx, ry, rz = rot_deg
    return {"Pitch": round(-rx, 4), "Yaw": yaw(ry), "Roll": round(rz, 4)}


def look_rotator(pos, look, roll: float = 0.0) -> dict[str, float]:
    """机位：从 pos 看向 look → UE Rotator（Pitch 抬头为正，Yaw 绕 Z，Roll 绕视线）。"""
    a, b = location(pos, 1.0), location(look, 1.0)
    dx, dy, dz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    yaw_ = math.degrees(math.atan2(dy, dx))
    pitch = math.degrees(math.atan2(dz, math.hypot(dx, dy)))
    return {"Pitch": round(pitch, 4), "Yaw": round(yaw_, 4), "Roll": round(-roll, 4)}


def scale3(s) -> list[float]:
    """缩放按轴对应：UE(X,Y,Z) = 我们的 (Z, X, Y)（缩放不带符号）。"""
    return [round(s[2], 4), round(s[0], 4), round(s[1], 4)]
