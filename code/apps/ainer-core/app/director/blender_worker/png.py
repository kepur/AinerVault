"""画骨架图、写 PNG：只用 numpy 和标准库。

Blender 自带的 Python 没有 PIL；骨架图（OpenPose 画法）在这里用 numpy 画，
ainer-core 那边的测试也能直接用（不 import bpy）。
"""
from __future__ import annotations

import struct
import zlib

import numpy as np

# OpenPose COCO-18：肢体连线（0 起的下标）与配色 —— 与 controlnet_aux 的 draw_bodypose 一致，
# 视频模型的姿态控制是拿这种图训练的，颜色、粗细都不能自己发明。
LIMBS = [(1, 2), (1, 5), (2, 3), (3, 4), (5, 6), (6, 7), (1, 8), (8, 9), (9, 10), (1, 11), (11, 12), (12, 13),
         (1, 0), (0, 14), (14, 16), (0, 15), (15, 17)]
COLORS = [(255, 0, 0), (255, 85, 0), (255, 170, 0), (255, 255, 0), (170, 255, 0), (85, 255, 0), (0, 255, 0),
          (0, 255, 85), (0, 255, 170), (0, 255, 255), (0, 170, 255), (0, 85, 255), (0, 0, 255), (85, 0, 255),
          (170, 0, 255), (255, 0, 255), (255, 0, 170), (255, 0, 85)]


def write_png(path: str, rgb: np.ndarray) -> None:
    """H×W×3 uint8 → PNG（无滤波、zlib 1 级：骨架图大片纯黑，压得很小也很快）。"""
    h, w, _ = rgb.shape
    raw = np.empty((h, w * 3 + 1), dtype=np.uint8)
    raw[:, 0] = 0
    raw[:, 1:] = rgb.reshape(h, w * 3)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)))
        f.write(chunk(b"IDAT", zlib.compress(raw.tobytes(), 1)))
        f.write(chunk(b"IEND", b""))


def _segment(img: np.ndarray, a: tuple[float, float], b: tuple[float, float], width: float, color) -> None:
    """粗线段：只在线段外包框里算点到线段的距离。"""
    h, w, _ = img.shape
    r = width / 2
    x0, x1 = int(max(0, min(a[0], b[0]) - r - 1)), int(min(w - 1, max(a[0], b[0]) + r + 1))
    y0, y1 = int(max(0, min(a[1], b[1]) - r - 1)), int(min(h - 1, max(a[1], b[1]) + r + 1))
    if x1 < x0 or y1 < y0:
        return
    ys, xs = np.mgrid[y0:y1 + 1, x0:x1 + 1]
    dx, dy = b[0] - a[0], b[1] - a[1]
    ll = dx * dx + dy * dy
    t = np.clip(((xs - a[0]) * dx + (ys - a[1]) * dy) / ll, 0, 1) if ll > 1e-9 else np.zeros_like(xs, dtype=float)
    d2 = (xs - (a[0] + t * dx)) ** 2 + (ys - (a[1] + t * dy)) ** 2
    img[y0:y1 + 1, x0:x1 + 1][d2 <= r * r] = color


def _disc(img: np.ndarray, c: tuple[float, float], radius: float, color) -> None:
    _segment(img, c, c, radius * 2, color)


def draw_pose(width: int, height: int, people: list[list[tuple[float, float, float]]]) -> np.ndarray:
    """people：每人 18 个 (x 像素, y 像素, 置信度)。置信度 0 的点不画，连着它的肢体也不画。"""
    img = np.zeros((height, width, 3), dtype=np.uint8)
    stick = max(2.0, width / 256)        # 1024 宽 → 4 像素，与 OpenPose 默认一致
    for kps in people:
        for i, (p, q) in enumerate(LIMBS):
            if kps[p][2] <= 0 or kps[q][2] <= 0:
                continue
            col = tuple(int(c * 0.6) for c in COLORS[i])
            _segment(img, kps[p][:2], kps[q][:2], stick * 2, col)
        for i, k in enumerate(kps):
            if k[2] > 0:
                _disc(img, k[:2], stick, COLORS[i])
    return img
