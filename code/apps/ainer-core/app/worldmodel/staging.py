"""首帧 ↔ 世界的配准：针孔相机投影、从已审核首帧的人物落脚点反投影到地面、为每镜拟合相机。

约定：Z 向上；相机 {pos, target, lens_mm}，36mm 传感器宽、水平适配；像素原点左上。
已审核首帧（标准卡布局）的 placement = [x, y, w, h]（像素，人物全身框）。
"""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np

SENSOR_W = 36.0


def _basis(pos: Sequence[float], target: Sequence[float]):
    f = np.asarray(target, float) - np.asarray(pos, float)
    f /= np.linalg.norm(f)
    r = np.cross(f, [0.0, 0.0, 1.0])
    if np.linalg.norm(r) < 1e-6:
        r = np.array([1.0, 0.0, 0.0])
    r /= np.linalg.norm(r)
    u = np.cross(r, f)
    return f, r, u


def project(cam: dict, pt: Sequence[float], W: int, H: int) -> tuple[float, float, float]:
    """世界点 → (px, py, depth)。depth<=0 表示在相机后面。"""
    f, r, u = _basis(cam["pos"], cam["target"])
    v = np.asarray(pt, float) - np.asarray(cam["pos"], float)
    d = float(v @ f)
    fpx = W * float(cam.get("lens_mm", 35.0)) / SENSOR_W
    if d <= 1e-6:
        return float("nan"), float("nan"), d
    return W / 2 + fpx * float(v @ r) / d, H / 2 - fpx * float(v @ u) / d, d


def unproject_floor(cam: dict, px: float, py: float, W: int, H: int) -> list[float] | None:
    """像素 → 射线与地面 z=0 的交点。"""
    f, r, u = _basis(cam["pos"], cam["target"])
    fpx = W * float(cam.get("lens_mm", 35.0)) / SENSOR_W
    ray = f + r * (px - W / 2) / fpx - u * (py - H / 2) / fpx
    if ray[2] >= -1e-6:
        return None
    t = -cam["pos"][2] / ray[2]
    p = np.asarray(cam["pos"], float) + ray * t
    return [round(float(p[0]), 3), round(float(p[1]), 3), 0.0]


def camera_from_horizon(horizon_y: float, cam_h: float, lens_mm: float, W: int, H: int,
                        yaw_deg: float = 0.0, origin=(0.0, 0.0)) -> dict:
    """由背景地平线高度（0–1）定俯仰：地平线在画面中心上方 → 相机低头。"""
    fpx = W * lens_mm / SENSOR_W
    pitch = math.atan((0.5 - horizon_y) * H / fpx)
    yaw = math.radians(yaw_deg)
    fwd = [math.cos(yaw) * math.cos(pitch), math.sin(yaw) * math.cos(pitch), -math.sin(pitch)]
    pos = [origin[0], origin[1], cam_h]
    return {"pos": pos, "target": [pos[i] + fwd[i] * 5 for i in range(3)], "lens_mm": lens_mm}


def calibrate_actors(cam: dict, placements: dict[str, Sequence[float]], W: int, H: int) -> dict[str, list[float]]:
    """已审核首帧里每个人的脚底中点 → 地面坐标（世界里的起始站位）。"""
    out = {}
    for actor, (x, y, w, h) in placements.items():
        p = unproject_floor(cam, x + w / 2, y + h, W, H)
        if p is None:
            raise ValueError(f"{actor} 的落脚点在地平线以上，无法反投影")
        out[actor] = p
    return out


def placement_error(cam: dict, actors: dict[str, tuple[Sequence[float], float]],
                    placements: dict[str, Sequence[float]], W: int, H: int) -> float:
    """投影的人物框（中心 x、头顶、脚底）与首帧 placement 的归一化误差。h 超出画面的只比可见部分。"""
    err = 0.0
    for a, (x, y, w, h) in placements.items():
        pos, height = actors[a]
        fx, fy, d = project(cam, pos, W, H)
        hx, hy, _ = project(cam, [pos[0], pos[1], height], W, H)
        if d <= 0.3 or math.isnan(fx):
            return 1e9
        err += ((fx + hx) / 2 - (x + w / 2)) ** 2 / W ** 2 * 4
        err += (hy - y) ** 2 / H ** 2
        err += (min(fy, H * 1.8) - min(y + h, H * 1.8)) ** 2 / H ** 2
    return err / max(1, len(placements))


def _screen_box(cam: dict, pos: Sequence[float], height: float, W: int, H: int, half_w: float = 0.25):
    fx, fy, d = project(cam, pos, W, H)
    hx, hy, _ = project(cam, [pos[0], pos[1], height], W, H)
    if d <= 0.05 or math.isnan(fx):
        return None, d
    fpx = (cam["lens_mm"] / 36.0) * W
    hw = fpx * half_w / d
    cx = (fx + hx) / 2
    return (cx - hw, min(hy, fy), cx + hw, max(hy, fy)), d


def occlusion_penalty(cam: dict, actors: dict[str, tuple[Sequence[float], float]],
                      others: dict[str, tuple[Sequence[float], float]], W: int, H: int,
                      min_dist: float = 0.6) -> float:
    """首帧里没有的人不能挡住首帧里的人，也不能贴着镜头（相机站在人身体里）。返回惩罚（0 = 干净）。"""
    pen = 0.0
    cp = cam["pos"]
    for _, (pos, h) in {**actors, **others}.items():
        if math.hypot(pos[0] - cp[0], pos[1] - cp[1]) < min_dist:
            return 1e9
    boxes = {a: _screen_box(cam, p, h, W, H) for a, (p, h) in actors.items()}
    for o, (p, h) in others.items():
        ob, od = _screen_box(cam, p, h, W, H)
        if ob is None:
            continue
        for a, (ab, ad) in boxes.items():
            if ab is None or od >= ad:
                continue
            ix = max(0.0, min(ab[2], ob[2]) - max(ab[0], ob[0]))
            iy = max(0.0, min(ab[3], ob[3]) - max(ab[1], ob[1]))
            area = max(1.0, (ab[2] - ab[0]) * (ab[3] - ab[1]))
            pen += 0.2 * ix * iy / area
    return pen


def fit_camera(actors: dict[str, tuple[Sequence[float], float]], placements: dict[str, Sequence[float]],
               W: int, H: int, *, lens_choices=(24, 28, 35, 45, 55), heights=(1.1, 1.3, 1.5),
               az_step_deg: int = 10, dists=(1.2, 1.6, 2.0, 2.6, 3.2, 4.0, 5.0),
               az_range: tuple[int, int] = (0, 360), others: dict | None = None,
               free_y: tuple[float, float] | None = None, valid_pos=None) -> tuple[dict, float]:
    """网格搜索：绕在场人物质心的一圈机位 × 焦距 × 高度，挑与首帧框最贴的相机。

    others：首帧里没有、但世界里此刻在场的人 —— 不许挡住首帧人物、不许贴脸（occlusion_penalty）。
    free_y：相机允许的 y 范围（走廊两墙之间），防止机位进墙。
    """
    others = others or {}

    def placement_error(cam, actors, placements, W, H):  # noqa: F811  局部：加上遮挡/空间约束
        if free_y and not (free_y[0] <= cam["pos"][1] <= free_y[1]):
            return 1e9
        if valid_pos is not None and not valid_pos(cam["pos"]):
            return 1e9
        e = _placement_error(cam, actors, placements, W, H)
        return e + occlusion_penalty(cam, actors, others, W, H) if e < 1e8 else e

    pts = np.array([p for p, _ in actors.values()], float)
    c = pts.mean(axis=0)
    best, best_e = None, float("inf")
    for lens in lens_choices:
        for ch in heights:
            for dist in dists:
                for az in range(az_range[0], az_range[1], az_step_deg):
                    a = math.radians(az)
                    pos = [c[0] + math.cos(a) * dist, c[1] + math.sin(a) * dist, ch]
                    for aim_z in (0.9, 1.2):
                        cam = {"pos": pos, "target": [c[0], c[1], aim_z], "lens_mm": lens}
                        e = placement_error(cam, actors, placements, W, H)
                        if e < best_e:
                            best, best_e = cam, e
    # 局部细化
    step = [0.2, 0.2, 0.1]
    for _ in range(40):
        improved = False
        for i in range(3):
            for s in (-1, 1):
                cand = {**best, "pos": [best["pos"][j] + (s * step[i] if j == i else 0) for j in range(3)]}
                e = placement_error(cand, actors, placements, W, H)
                if e < best_e:
                    best, best_e, improved = cand, e, True
        if not improved:
            step = [x / 2 for x in step]
            if step[0] < 0.01:
                break
    best = {"pos": [round(x, 3) for x in best["pos"]], "target": [round(float(x), 3) for x in best["target"]],
            "lens_mm": best["lens_mm"]}
    return best, round(best_e, 5)


def move_camera(cam: dict, move: dict, u: float) -> dict:
    """运镜：在 [0,1] 上插值。push_in/pull_out 沿视线前后，pan 绕相机竖轴转，truck 横移，crane 升降。"""
    kind, amt = move.get("type", "hold"), float(move.get("amount", 0.0))
    pos, tgt = np.asarray(cam["pos"], float), np.asarray(cam["target"], float)
    f, r, _ = _basis(pos, tgt)
    s = u * amt
    if kind == "push_in":
        pos = pos + f * s
    elif kind == "pull_out":
        pos = pos - f * s
    elif kind in ("pan_left", "pan_right"):
        ang = math.radians(s) * (1 if kind == "pan_left" else -1)
        v = tgt - pos
        ca, sa = math.cos(ang), math.sin(ang)
        tgt = pos + np.array([v[0] * ca - v[1] * sa, v[0] * sa + v[1] * ca, v[2]])
    elif kind in ("truck_left", "truck_right"):
        d = -r * s if kind == "truck_left" else r * s
        pos, tgt = pos + d, tgt + d
    elif kind == "crane_down":
        pos = pos - np.array([0, 0, s])
    elif kind == "crane_up":
        pos = pos + np.array([0, 0, s])
    elif kind == "zoom_in":
        return {**cam, "lens_mm": float(cam.get("lens_mm", 35)) * (1 + u * amt)}
    return {"pos": [float(x) for x in pos], "target": [float(x) for x in tgt], "lens_mm": cam.get("lens_mm", 35.0)}


_placement_error = placement_error
