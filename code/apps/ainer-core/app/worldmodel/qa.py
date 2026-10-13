"""逐镜 QA 闸门（可自动判定的部分）。所有判定都给出数值依据；它们是代理指标，不替代人工观看。

  positions  首帧与已审核首帧的结构相关；运动能量落在白模给出的人物框里（站位/走位与表演一致）
  camera     计划有运镜时，首尾帧之间要测得缩放或平移
  motion     帧差均值与非重复帧比例（拒绝“静帧”）
  audio      有音轨、时长与画面对齐、不是静音；对白镜台词时长装得下
  mood       剧本情绪 → 提示词/声音/音乐的规则检查
"""
from __future__ import annotations

import json
import math
import subprocess
from typing import Any

import numpy as np

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"
SMALL = (160, 96)

TH = {"motion_diff": 1.0, "nondup": 0.5, "cam_scale": 0.02, "cam_shift": 0.015, "audio_rms_db": -45.0,
      "audio_slack_s": 0.25, "first_corr": 0.55, "energy_inside": 0.45,
      "identity": 0.6}

MOOD_WORDS = {
    "menace": ["menacing", "tense", "threatening"], "fear": ["fear", "trembl", "frighten", "tense"],
    "violence": ["sudden", "violent", "impact", "harsh", "tense"], "anger": ["angry", "aggressive", "harsh"],
    "pain": ["pain", "tear", "hurt"], "mockery": ["mock", "sneer", "laugh"], "contempt": ["contempt", "sneer", "scorn"],
    "despair": ["despair", "trembl", "broken", "lonely"], "loneliness": ["lonely", "empty", "alone"],
}


def probe(path: str) -> dict[str, Any]:
    out = subprocess.run([FFPROBE, "-v", "error", "-show_entries",
                          "format=duration:stream=codec_type,width,height,r_frame_rate,nb_frames,duration",
                          "-of", "json", path], capture_output=True, text=True, timeout=60, check=True).stdout
    d = json.loads(out)
    v = next((s for s in d["streams"] if s["codec_type"] == "video"), {})
    a = next((s for s in d["streams"] if s["codec_type"] == "audio"), None)
    num, den = (v.get("r_frame_rate") or "0/1").split("/")
    return {"duration_s": float(d["format"].get("duration") or 0), "width": v.get("width"), "height": v.get("height"),
            "fps": float(num) / float(den or 1), "has_audio": a is not None,
            "audio_duration_s": float(a.get("duration") or 0) if a else 0.0}


def frames_gray(path: str, size=SMALL, fps: float | None = None) -> np.ndarray:
    vf = f"scale={size[0]}:{size[1]}:flags=area,format=gray"
    if fps:
        vf = f"fps={fps}," + vf
    raw = subprocess.run([FFMPEG, "-v", "error", "-i", path, "-vf", vf, "-f", "rawvideo", "-"],
                         capture_output=True, timeout=120, check=True).stdout
    n = len(raw) // (size[0] * size[1])
    return np.frombuffer(raw[: n * size[0] * size[1]], np.uint8).reshape(n, size[1], size[0]).astype(np.float32)


def image_gray(path: str, size=SMALL) -> np.ndarray:
    return frames_gray(path, size)[0]


def motion_stats(fr: np.ndarray) -> dict[str, float]:
    if len(fr) < 2:
        return {"mean_diff": 0.0, "nondup": 0.0}
    d = np.abs(np.diff(fr, axis=0)).mean(axis=(1, 2))
    return {"mean_diff": round(float(d.mean()), 3), "nondup": round(float((d > 0.3).mean()), 3)}


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    a = a - a.mean()
    b = b - b.mean()
    den = math.sqrt(float((a * a).sum() * (b * b).sum())) or 1.0
    return float((a * b).sum() / den)


def _zoom(img: np.ndarray, s: float) -> np.ndarray:
    """中心缩放 s（>1 放大）后回到原尺寸（最近邻，够用）。"""
    h, w = img.shape
    ys = np.clip(((np.arange(h) - h / 2) / s + h / 2).astype(int), 0, h - 1)
    xs = np.clip(((np.arange(w) - w / 2) / s + w / 2).astype(int), 0, w - 1)
    return img[np.ix_(ys, xs)]


def _shift(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    """相位相关：b 相对 a 的整体平移（像素）。"""
    A, B = np.fft.fft2(a - a.mean()), np.fft.fft2(b - b.mean())
    R = A * np.conj(B)
    R /= np.abs(R) + 1e-9
    r = np.abs(np.fft.ifft2(R))
    y, x = np.unravel_index(np.argmax(r), r.shape)
    h, w = a.shape
    return (float(x - w if x > w / 2 else x), float(y - h if y > h / 2 else y))


def _pair_motion(a: np.ndarray, b: np.ndarray) -> tuple[float, float, float, float]:
    best, bs = -2.0, 1.0
    for sc in np.arange(0.70, 1.4501, 0.005):
        c = _corr(_zoom(a, sc)[10:-10, 16:-16], b[10:-10, 16:-16])
        if c > best:
            best, bs = c, float(sc)
    dx, dy = _shift(_zoom(a, bs), b)
    return bs, dx, dy, best


def camera_motion(fr: np.ndarray) -> dict[str, float]:
    """首帧对中帧、首帧对尾帧：最佳中心缩放 + 相位相关平移，取偏离最大的一对。"""
    if len(fr) < 2:
        return {"scale": 1.0, "shift_x": 0.0, "shift_y": 0.0}
    h, w = fr.shape[1:]
    best = (1.0, 0.0, 0.0, 0.0)
    worst_c = 1.0
    for j in (len(fr) // 2, len(fr) - 1):
        s, dx, dy, c = _pair_motion(fr[0], fr[j])
        worst_c = min(worst_c, c)
        if abs(s - 1) + math.hypot(dx / w, dy / h) >= abs(best[0] - 1) + math.hypot(best[1] / w, best[2] / h):
            best = (s, dx, dy, c)
    return {"scale": round(best[0], 4), "shift_x": round(best[1] / w, 4), "shift_y": round(best[2] / h, 4),
            "match_corr": round(best[3], 3), "min_match_corr": round(worst_c, 3)}


HUES = {  # 本章人物的标志色：Tyler 红发、Brad 绿发、Kyle 金发（也会吃到窗光，只当下限用）
    "red": lambda r, g, b: (r > 150) & (r > g * 1.6) & (r > b * 1.8),
    "green": lambda r, g, b: (g > 140) & (g > r * 1.4) & (g > b * 1.2),
    "blond": lambda r, g, b: (r > 200) & (g > 170) & (b < 140) & (r - b > 80),
}


def identity_colors(path: str, min_presence: float = 0.0015) -> dict[str, Any]:
    """人物身份保持（代理）：首帧里明显存在的标志色，在后半段每帧都不能掉到 60% 以下（人物融化/消失会掉）。"""
    raw = subprocess.run([FFMPEG, "-v", "error", "-i", path, "-vf", f"scale={SMALL[0]}:{SMALL[1]}", "-pix_fmt", "rgb24",
                          "-f", "rawvideo", "-"], capture_output=True, timeout=120).stdout
    fr = np.frombuffer(raw, np.uint8).reshape(-1, SMALL[1], SMALL[0], 3).astype(np.float32)
    if len(fr) < 4:
        return {"ok": True, "ratios": {}}
    ref = fr[1]  # 第 0 帧就是给定首帧，比生成帧更锐，用第 1 帧作基准
    out = {}
    for k, fn in HUES.items():
        base = float(fn(ref[..., 0], ref[..., 1], ref[..., 2]).mean())
        if base < min_presence:
            continue
        later = [float(fn(f[..., 0], f[..., 1], f[..., 2]).mean()) / base for f in fr[len(fr) // 2:]]
        out[k] = round(min(later), 3)
    return {"ok": all(v >= TH["identity"] for v in out.values()), "ratios": out}


def audio_rms_db(path: str) -> float:
    raw = subprocess.run([FFMPEG, "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                         capture_output=True, timeout=120).stdout
    if not raw:
        return -120.0
    x = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
    return round(20 * math.log10(math.sqrt(float((x * x).mean())) + 1e-9), 2)


def energy_inside(fr: np.ndarray, boxes: list[list[float]], W: int, H: int, pad: float = 0.15) -> float:
    """帧差能量落在白模人物框（像素，原分辨率）内的比例。"""
    if len(fr) < 2 or not boxes:
        return 0.0
    e = np.abs(np.diff(fr, axis=0)).sum(axis=0)
    h, w = e.shape
    m = np.zeros_like(e, dtype=bool)
    for x0, y0, x1, y1 in boxes:
        bw, bh = (x1 - x0) * pad, (y1 - y0) * pad
        xa, xb = int(max(0, (x0 - bw) / W * w)), int(min(w, math.ceil((x1 + bw) / W * w)))
        ya, yb = int(max(0, (y0 - bh) / H * h)), int(min(h, math.ceil((y1 + bh) / H * h)))
        m[ya:yb, xa:xb] = True
    tot = float(e.sum()) or 1.0
    return round(float(e[m].sum()) / tot, 3)


def mood_check(mood: str | None, prompt: str, audio_db: float, music_cue: str | None) -> dict[str, Any]:
    words = MOOD_WORDS.get(mood or "", [])
    hit = [w for w in words if w in prompt.lower()]
    ok = (not words or bool(hit)) and audio_db > TH["audio_rms_db"] and bool(music_cue)
    return {"ok": ok, "mood": mood, "prompt_terms": hit, "music_cue": music_cue, "audio_db": audio_db}


def _cam_vec(c: dict) -> tuple[float, float, float]:
    return (c["scale"] - 1.0, c["shift_x"], c["shift_y"])


def camera_gate(cm: dict, planned: str, *, textured: bool = True, reference: dict | None = None) -> dict[str, Any]:
    """运镜闸门。

    旧版有运算优先级 bug：``textured and in_range and A or B`` —— 只要平移量够就过，缩放撞边界（画面崩）也算过
    （第一章镜 3：scale=1.45 撞上限、shift_x=-0.075 照样判过）。现在：
      1) 缩放撞搜索边界 = 没测到一致的几何变换 → 不算运镜；
      2) 有白模（clay）实测运镜时，生成片的运镜向量要与白模同向（余弦 > 0.3）；
      3) 没有白模时按计划类型判：推 → 放大，拉 → 缩小，摇/移 → 水平位移，升降 → 竖直位移或缩放。
    """
    out = {**cm, "planned": planned}
    if planned == "hold":
        return {**out, "ok": True, "why": "hold"}
    in_range = 0.705 < cm["scale"] < 1.445
    mag = math.hypot(cm["scale"] - 1, math.hypot(cm["shift_x"], cm["shift_y"]))
    if not textured or not in_range:
        return {**out, "ok": False, "why": "zoom search hit its bound or frame untextured: no consistent camera transform"}
    if mag < min(TH["cam_scale"], TH["cam_shift"]):
        return {**out, "ok": False, "why": "no measurable camera move"}
    ref_ok = reference is not None and 0.705 < reference.get("scale", 1) < 1.445 and \
        math.hypot(reference["scale"] - 1, math.hypot(reference["shift_x"], reference["shift_y"])) >= 0.01
    if ref_ok:
        a, b = _cam_vec(cm), _cam_vec(reference)
        na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
        cos = sum(x * y for x, y in zip(a, b)) / (na * nb + 1e-9)
        out["reference"] = {"scale": reference["scale"], "shift_x": reference["shift_x"], "shift_y": reference["shift_y"],
                            "cosine": round(cos, 3)}
        return {**out, "ok": cos > 0.3, "why": f"direction vs greybox clay cosine={cos:.2f}"}
    if planned in ("push_in", "zoom_in"):
        ok = cm["scale"] - 1 >= TH["cam_scale"]
    elif planned == "pull_out":
        ok = 1 - cm["scale"] >= TH["cam_scale"]
    elif planned.startswith(("pan", "truck")):
        ok = abs(cm["shift_x"]) >= TH["cam_shift"]
    else:
        ok = abs(cm["shift_y"]) >= TH["cam_shift"] or abs(cm["scale"] - 1) >= TH["cam_scale"]
    return {**out, "ok": ok, "why": f"planned-type rule for {planned}"}


def gate_shot(video: str, *, kind: str, planned_move: str, duration_s: float, mood: str | None, prompt: str,
              first_frame: str | None = None, greybox: dict | None = None, voice_s: float | None = None,
              music_cue: str | None = None, check_first: bool = True,
              reference_camera: dict | None = None) -> dict[str, Any]:
    """一镜全部闸门。greybox：Blender camera.json（每人逐帧 bbox）。"""
    info = probe(video)
    fr = frames_gray(video)
    res: dict[str, Any] = {"probe": info}
    m = motion_stats(fr)
    res["motion"] = {**m, "ok": m["mean_diff"] >= TH["motion_diff"] and m["nondup"] >= TH["nondup"]}
    cm = camera_motion(fr)
    res["camera"] = camera_gate(cm, planned_move, textured=float(fr.std()) >= 2.0, reference=reference_camera)
    adb = audio_rms_db(video) if info["has_audio"] else -120.0
    a_ok = info["has_audio"] and abs(info["audio_duration_s"] - info["duration_s"]) <= TH["audio_slack_s"] \
        and adb > TH["audio_rms_db"] and duration_s - 0.15 <= info["duration_s"] <= duration_s + 8.0 / max(1.0, info["fps"] or 8) + 0.1  # LTX 帧数取 8k+1，成片按目标时长裁
    if voice_s is not None:
        a_ok = a_ok and voice_s <= info["duration_s"] + 0.1
    res["audio"] = {"ok": a_ok, "rms_db": adb, "audio_s": info["audio_duration_s"], "video_s": info["duration_s"],
                    "target_s": duration_s, "voice_s": voice_s}
    pos: dict[str, Any] = {"ok": True}
    if first_frame and check_first:
        c = _corr(image_gray(first_frame), fr[0])
        pos["first_frame_corr"] = round(c, 3)
        pos["ok"] = c >= TH["first_corr"]
    ident = identity_colors(video)
    pos["identity"] = ident["ratios"]
    pos["ok"] = pos["ok"] and ident["ok"]
    if greybox and kind == "action":
        W, H = greybox["resolution"]
        boxes = [s["bbox"] for per in greybox["actors"].values() for s in per if s.get("bbox")]
        # 只用本镜画面里出现的人：每人取全程并集框
        union = []
        for per in greybox["actors"].values():
            bb = [s["bbox"] for s in per if s.get("bbox") and s["visible_kps"] >= 6]
            if bb:
                union.append([min(b[0] for b in bb), min(b[1] for b in bb), max(b[2] for b in bb), max(b[3] for b in bb)])
        ei = energy_inside(fr, union or boxes, W, H)
        pos["motion_energy_in_staging"] = ei
        pos["ok"] = pos["ok"] and ei >= TH["energy_inside"]
    res["positions"] = pos
    res["mood"] = mood_check(mood, prompt, adb, music_cue)
    res["pass"] = all(res[k]["ok"] for k in ("motion", "camera", "audio", "positions", "mood"))
    res["failed"] = [k for k in ("positions", "camera", "motion", "audio", "mood") if not res[k]["ok"]]
    return res
