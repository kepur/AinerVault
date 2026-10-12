"""纯几何：chunk 栅格化、AABB、线段与盒体相交、可达性。不依赖数据库，便于测试与 Blender 侧复用。"""
from __future__ import annotations

import math
from typing import Iterable, Sequence

Vec = Sequence[float]


def chunks_for_aabb(aabb: dict, size: float) -> list[tuple[int, int]]:
    """AABB 覆盖的 (cx, cy) 栅格（半开区间，贴边不多算一格）。"""
    lo, hi = aabb["min"], aabb["max"]
    x0, y0 = math.floor(lo[0] / size), math.floor(lo[1] / size)
    x1 = math.ceil(hi[0] / size) - 1
    y1 = math.ceil(hi[1] / size) - 1
    return [(cx, cy) for cx in range(x0, max(x0, x1) + 1) for cy in range(y0, max(y0, y1) + 1)]


def aabb_contains(aabb: dict, p: Vec, margin: float = 0.0) -> bool:
    lo, hi = aabb["min"], aabb["max"]
    return all(lo[i] - margin <= p[i] <= hi[i] + margin for i in range(min(len(p), 3)))


def aabb_dist2d(aabb: dict, p: Vec) -> float:
    lo, hi = aabb["min"], aabb["max"]
    dx = max(lo[0] - p[0], 0.0, p[0] - hi[0])
    dy = max(lo[1] - p[1], 0.0, p[1] - hi[1])
    return math.hypot(dx, dy)


def instance_aabb(xform: dict, dims: Vec) -> dict:
    """实例的轴对齐包围盒（绕 Z 旋转按 90° 取整近似；墙/柜都是正交摆放）。pos 为底面中心。"""
    pos = xform.get("pos", [0, 0, 0])
    sc = xform.get("scale", [1, 1, 1])
    rz = (xform.get("rot_deg", [0, 0, 0])[2]) % 180
    w, d, h = dims[0] * sc[0], dims[1] * sc[1], dims[2] * sc[2]
    if 45 <= rz < 135:
        w, d = d, w
    return {"min": [pos[0] - w / 2, pos[1] - d / 2, pos[2]], "max": [pos[0] + w / 2, pos[1] + d / 2, pos[2] + h]}


def circle_hits_aabb(c: Vec, r: float, aabb: dict) -> float:
    """圆（2D，人物胶囊俯视）与 AABB 的穿透深度；不相交返回 0。"""
    d = aabb_dist2d(aabb, c)
    return max(0.0, r - d) if d > 0 else r + _inside_depth(aabb, c)


def _inside_depth(aabb: dict, p: Vec) -> float:
    lo, hi = aabb["min"], aabb["max"]
    return min(p[0] - lo[0], hi[0] - p[0], p[1] - lo[1], hi[1] - p[1])


def push_out(c: Vec, r: float, aabb: dict, eps: float = 0.02) -> list[float]:
    """把圆心沿最短方向推出 AABB 外 r+eps。"""
    lo, hi = aabb["min"], aabb["max"]
    x, y = float(c[0]), float(c[1])
    if aabb_dist2d(aabb, c) > 0:
        nx = min(max(x, lo[0]), hi[0])
        ny = min(max(y, lo[1]), hi[1])
        vx, vy = x - nx, y - ny
        n = math.hypot(vx, vy) or 1.0
        return [nx + vx / n * (r + eps), ny + vy / n * (r + eps), *list(c[2:3])]
    opts = [(x - lo[0], (lo[0] - r - eps, y)), (hi[0] - x, (hi[0] + r + eps, y)),
            (y - lo[1], (x, lo[1] - r - eps)), (hi[1] - y, (x, hi[1] + r + eps))]
    _, (px, py) = min(opts, key=lambda o: o[0])
    return [px, py, *list(c[2:3])]


def segment_hits_aabb(a: Vec, b: Vec, aabb: dict, r: float = 0.0) -> bool:
    """2D 线段（膨胀 r）是否穿过 AABB —— 用于“走到地标”的可达性。"""
    lo = [aabb["min"][0] - r, aabb["min"][1] - r]
    hi = [aabb["max"][0] + r, aabb["max"][1] + r]
    t0, t1 = 0.0, 1.0
    for i in range(2):
        d = b[i] - a[i]
        if abs(d) < 1e-9:
            if a[i] < lo[i] or a[i] > hi[i]:
                return False
            continue
        u0, u1 = (lo[i] - a[i]) / d, (hi[i] - a[i]) / d
        if u0 > u1:
            u0, u1 = u1, u0
        t0, t1 = max(t0, u0), min(t1, u1)
        if t0 > t1:
            return False
    return True


def lerp_track(keys: list[dict], t_ms: float) -> tuple[list[float], float]:
    """按时间线性插值位置与朝向（keys 已按 t_ms 排序）。"""
    if not keys:
        return [0.0, 0.0, 0.0], 0.0
    if t_ms <= keys[0]["t_ms"]:
        return list(keys[0]["pos"]), float(keys[0].get("yaw_deg", 0.0))
    for k0, k1 in zip(keys, keys[1:]):
        if k0["t_ms"] <= t_ms <= k1["t_ms"]:
            span = max(1.0, k1["t_ms"] - k0["t_ms"])
            u = (t_ms - k0["t_ms"]) / span
            pos = [k0["pos"][i] + (k1["pos"][i] - k0["pos"][i]) * u for i in range(3)]
            y0, y1 = float(k0.get("yaw_deg", 0.0)), float(k1.get("yaw_deg", 0.0))
            dy = (y1 - y0 + 180) % 360 - 180
            return pos, y0 + dy * u
    return list(keys[-1]["pos"]), float(keys[-1].get("yaw_deg", 0.0))


def iter_times(start_ms: int, end_ms: int, step_ms: int) -> Iterable[int]:
    t = start_ms
    while t <= end_ms:
        yield t
        t += step_ms
