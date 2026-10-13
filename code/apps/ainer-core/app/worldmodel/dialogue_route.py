"""白模对白路由（可选，仅在 greybox 开关打开时使用）。

移植自原管线（AiComicStudio comic_engine/dialogue_sync.py + shots.py 的 dialogue_a2v）：
  1. 首帧：原管线的人脸卡近景首帧（384×256，8fps）；
  2. 配音：定稿配音按 115–130 词/分钟调速，前留白 150ms、后留白 350ms（retime_voice）；
  3. 身体：LTX-2.5 A2V（配音驱动）+ 白模骨架（pose）控制，让白模也能管对白镜头的站位/姿态；
  4. 嘴型：本地 Rhubarb 口型时段 + 参考头像的 9 种漫画嘴型贴片，按眼部跟踪位置合成（mouth_pass）。
原管线的产物（贴片、嘴型框、口型时段、调速后配音）只读复用，不改动。
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter



def ff(*a: str):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *a], check=True, capture_output=True, timeout=600)


def dur(p: str | Path) -> float:
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)]).decode())


# ------------------------------------------------------------------ 配音调速
def retime_voice(raw: Path, text: str, out: Path, lo: float = 115, hi: float = 130, lead_ms: int = 150, tail_ms: int = 350) -> dict:
    words = len(re.findall(r"[A-Za-z']+", text)) or 1
    d = dur(raw)
    wpm = words / d * 60
    target = hi if wpm > hi else lo if wpm < lo else wpm
    tempo = min(1.0, target / wpm) if wpm > hi else 1.0     # 只放慢过快的台词，不拉长慢的
    chain = []
    t = tempo
    while t < 0.5:
        chain.append("atempo=0.5")
        t /= 0.5
    chain.append(f"atempo={t:.4f}")
    ff("-i", str(raw), "-af", ",".join(chain) + f",adelay={lead_ms}:all=1,apad=pad_dur={tail_ms / 1000:.3f}", "-ar", "48000", "-ac", "1", str(out))
    return {"raw_wpm": round(wpm, 1), "tempo": round(tempo, 4), "estimated_spoken_wpm": round(wpm * tempo, 1),
            "lead_ms": lead_ms, "tail_ms": tail_ms, "duration_s": dur(out)}


# ------------------------------------------------------------------ 原管线素材（只读）
class FaceSafeShot:
    """一个对白镜头在原管线里的人脸卡首帧、配音、嘴型绑定和嘴型框。"""

    def __init__(self, preview_dir: str, store_db: str, n: int, media_root: Path):
        self.n = n
        self.media = media_root
        r = json.loads((Path(preview_dir) / "mouth-cover" / str(n) / "result.json").read_text())
        a = r["asset"]
        con = sqlite3.connect(f"file:{store_db}?mode=ro", uri=True)
        get = lambda i: json.loads(con.execute("select data from production_assets where asset=?", (i,)).fetchone()[0])  # noqa: E731
        self.frame = get(a["frame_asset_id"])
        self.body = get(a["source_video_asset_id"])
        self.rig = get(a["rig_asset_id"])["rig"]
        self.ref_face_url = get(self.rig["source_asset_id"])["url"]
        con.close()
        self.cover = a["mouth_cover_rectangle"]
        self.mouth = a["mouth_rectangle"]
        self.cues = a["mouth_cues"]
        self.voice = Path(preview_dir) / f"voice-{n:02d}.wav"
        self.dialogue = self.body.get("dialogue") or []
        self.camera, self.camera_strength = r["recipe"].get("camera", "hold"), r["recipe"].get("camera_strength", 0.08)
        self.seed = int(self.body.get("seed") or 0)

    def path(self, url: str) -> Path:
        return self.media / Path(url).name


# ------------------------------------------------------------------ 嘴型合成（移植 dialogue_sync.align）
def mouth_pass(body: Path, voice: Path, fs: FaceSafeShot, work: Path, mouth_fps: int = 8, search: int = 16) -> Path:
    work.mkdir(parents=True, exist_ok=True)
    w, h = (int(x) for x in subprocess.check_output(
        ["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(body)]).decode().split(","))
    rate = subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=r_frame_rate",
                                    "-of", "csv=p=0", str(body)]).decode().strip()
    a, b = rate.split("/")
    src_fps = float(a) / float(b)
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(body), "-map", "0:v:0", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"])
    frames = np.frombuffer(raw, np.uint8).reshape((-1, h, w, 3))
    duration = dur(voice)
    x, y, cw, ch = fs.cover
    mx, my, mw, mh = fs.mouth
    pad_x, pad_y = mx - x, my - y
    face_src = Image.open(fs.path(fs.frame["url"])).convert("RGBA")   # 首帧（原管线验收过的人脸卡近景）
    neutral = face_src.resize((w, h)).crop((x, y, x + cw, y + ch))
    patches = {}
    for key, ref in fs.rig["visemes"].items():
        p = neutral.copy()
        p.alpha_composite(Image.open(fs.path(ref["url"])).convert("RGBA").resize((mw, mh), Image.Resampling.LANCZOS), (pad_x, pad_y))
        patches[key] = p
    feather = Image.new("L", (cw, ch), 255)
    ImageDraw.Draw(feather).rectangle((0, 0, cw - 1, ch - 1), outline=70, width=2)
    feather = feather.filter(ImageFilter.GaussianBlur(1))
    base = frames[0].mean(2)
    ex0, ex1, ey0, ey1 = round(w * .36), round(w * .66), round(h * .24), round(h * .47)
    tmpl = base[ey0:ey1, ex0:ex1]
    centre = tmpl - tmpl.mean()
    tn = np.linalg.norm(centre)
    folder = work / "frames"
    folder.mkdir(exist_ok=True)
    count = math.ceil(duration * mouth_fps)
    track = []
    for i in range(count):
        t = i / mouth_fps
        rgb = frames[min(len(frames) - 1, round(t * src_fps))]
        grey = rgb.mean(2)
        best = (-2.0, 0, 0)
        for dy in range(-search // 2 * 1, search // 2 + 1, 2):
            for dx in range(-search, search + 1, 2):
                if ey0 + dy < 0 or ey1 + dy > h or ex0 + dx < 0 or ex1 + dx > w:
                    continue
                z = grey[ey0 + dy:ey1 + dy, ex0 + dx:ex1 + dx]
                z = z - z.mean()
                s = float(np.sum(centre * z) / max(1e-8, tn * np.linalg.norm(z)))
                if s > best[0]:
                    best = (s, dx, dy)
        s, dx, dy = best
        track.append(round(s, 3))
        shape = next((c["value"] for c in fs.cues if c["start"] <= min(duration - .001, t + .5 / mouth_fps) < c["end"]), "X")
        img = Image.fromarray(rgb).convert("RGBA")
        m = patches.get(shape, patches["X"]).copy()
        arr = np.array(m)
        ref = rgb[max(0, y + dy):y + dy + ch, max(0, x + dx):x + dx + cw]
        if ref.shape[0] == ch and ref.shape[1] == cw:
            border = np.concatenate((ref[0], ref[-1]), axis=0)
            sb = np.concatenate((arr[0, :, :3], arr[-1, :, :3]), axis=0)
            delta = np.clip(np.median(border, axis=0) - np.median(sb, axis=0), -35, 35)
            skin = (arr[:, :, 0].astype(int) - arr[:, :, 1] > 8) & (arr[:, :, 1].astype(int) - arr[:, :, 2] > 7) & (arr[:, :, 1] > 130)
            adj = np.clip(arr[:, :, :3].astype(float) + delta, 0, 255).astype("uint8")
            arr[:, :, :3] = np.where(skin[:, :, None], adj, arr[:, :, :3])
        m = Image.fromarray(arr)
        m.putalpha(feather)
        img.alpha_composite(m, (x + dx, y + dy))
        img.convert("RGB").save(folder / f"{i:04d}.png")
    native = work / "mouth-pass.mp4"
    ff("-framerate", str(mouth_fps), "-i", str(folder / "%04d.png"), "-i", str(voice), "-map", "0:v:0", "-map", "1:a:0",
       "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-t", f"{duration:.3f}", str(native))
    out = work / "aligned.mp4"
    n = round(duration * 24)
    vf = "fps=24"
    if fs.camera != "hold":
        z = f"1+{fs.camera_strength}*on/{max(1, n - 1)}" if fs.camera != "pull_out" else f"1+{fs.camera_strength}*(1-on/{max(1, n - 1)})"
        vf += f",zoompan=z='{z}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s={w}x{h}:fps=24"
    ff("-i", str(native), "-vf", vf, "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "copy", "-t", f"{duration:.3f}", str(out))
    (work / "mouth_track.json").write_text(json.dumps({"eye_match": track, "min": min(track) if track else None}))
    return out


# ------------------------------------------------------------------ 两道：白模预跑抽锚帧 → a2v（配音驱动，嘴由模型生成）
def anchor_a2v_input(*, prompt: str, first_frame: dict, voice_b64: str, pose_b64: str, body_ms: int, seed: int,
                     anchor_every: int = 8, head: float = 1.0, mid: float = 0.6, pose_strength: float = 1.0,
                     width: int = 384, height: int = 256, fps: int = 8) -> dict:
    """网关 video.image_to_video（LTX-2.5）的“白模控制 + 配音驱动”两道请求体。

    control + audio.mode=drive 时网关先用 IC-LoRA（pose）快档预跑白模，每 anchor_every 帧抽一个锚帧，
    正片走 a2v：首帧锚=原管线人脸卡首帧（调用方给的 first_frame 在同帧号上优先），中间锚只保站位/机位（mid），
    嘴由 a2v 生成。8fps 下 anchor_every=8 ≈ 1 秒（网关下限 8）。人脸卡尺寸/帧率/时长沿用原管线。"""
    return {"prompt": prompt, "first_frame": first_frame, "width": width, "height": height, "fps": fps,
            "duration_ms": int(body_ms), "motion": "animate",
            "audio": {"mode": "drive", "track": {"b64": voice_b64}},
            "control": {"type": "pose", "video": {"b64": pose_b64}, "strength": float(pose_strength),
                        "anchor_every": max(8, int(anchor_every)),
                        "anchor_strength_head": float(head), "anchor_strength_mid": float(mid)},
            "params": {"seed": int(seed), "stage2_steps": 2}}


def finish_a2v(raw: Path, voice: Path, out: Path, duration_s: float, fps_out: int = 24) -> Path:
    """a2v 正片 → 成片：只换帧率（重复帧，不改时间轴，不慢放），音轨换回原配音，按原镜时长截断。"""
    ff("-i", str(raw), "-i", str(voice), "-map", "0:v:0", "-map", "1:a:0", "-vf", f"fps={fps_out},scale=640:384:flags=lanczos",
       "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-af", "apad",
       "-t", f"{duration_s:.3f}", str(out))
    return out
