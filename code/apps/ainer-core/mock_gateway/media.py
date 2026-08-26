"""零依赖的占位媒体生成：PNG 用手写编码器，WAV 用 stdlib wave。"""
from __future__ import annotations

import hashlib
import io
import math
import struct
import wave
import zlib


def _chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data)) + tag + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def _seeded_rgb(seed: str) -> tuple[int, int, int]:
    h = hashlib.sha256(seed.encode()).digest()
    # 压到中等明度，避免纯黑纯白，占位图看起来像张图
    return (60 + h[0] % 140, 60 + h[1] % 140, 60 + h[2] % 140)


def make_png(width: int, height: int, seed: str = "") -> bytes:
    """渐变 + 网格的占位图。尺寸真实，便于前端布局验证。"""
    width = max(16, min(width, 4096))
    height = max(16, min(height, 4096))
    r0, g0, b0 = _seeded_rgb(seed)
    r1, g1, b1 = _seeded_rgb(seed + "|2")

    rows = bytearray()
    for y in range(height):
        rows.append(0)  # filter type: None
        fy = y / max(height - 1, 1)
        for x in range(width):
            fx = x / max(width - 1, 1)
            t = (fx + fy) / 2
            r = int(r0 + (r1 - r0) * t)
            g = int(g0 + (g1 - g0) * t)
            b = int(b0 + (b1 - b0) * t)
            # 每 64px 画一条网格线，一眼看出这是占位图
            if x % 64 == 0 or y % 64 == 0:
                r, g, b = min(r + 45, 255), min(g + 45, 255), min(b + 45, 255)
            rows += bytes((r, g, b))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8bit truecolor
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(bytes(rows), 6))
        + _chunk(b"IEND", b"")
    )


def make_wav(duration_ms: int, sample_rate: int = 44100, freq: float = 0.0) -> bytes:
    """静音或低幅正弦的占位音频。duration_ms 精确 —— Core 要用它回填镜头时长。"""
    duration_ms = max(50, min(duration_ms, 600_000))
    n = int(sample_rate * duration_ms / 1000)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        if freq > 0:
            frames = bytearray()
            for i in range(n):
                v = int(3000 * math.sin(2 * math.pi * freq * i / sample_rate))
                frames += struct.pack("<h", v)
            w.writeframes(bytes(frames))
        else:
            w.writeframes(b"\x00\x00" * n)
    return buf.getvalue()


def estimate_tts_duration_ms(text: str, language: str, speed: float = 1.0) -> int:
    """按语种的朗读速率估时长。CJK 按字，拉丁按词。"""
    text = (text or "").strip()
    if not text:
        return 300
    if language[:2].lower() in {"zh", "ja", "ko"}:
        units = len([c for c in text if not c.isspace()])
        per_unit_ms = 210  # 约 4.8 字/秒
    else:
        units = max(len(text.split()), 1)
        per_unit_ms = 380  # 约 158 词/分
    return max(int(units * per_unit_ms / max(speed, 0.1)) + 250, 300)
