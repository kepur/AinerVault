"""对白 A/B 客观指标（独立脚本：需要 opencv + transformers(CLIP) + 本地动漫人脸检测 onnx）。

python ab_metrics.py spec.json → 打印 JSON。spec: {"ref_face": png, "voice": wav, "takes": {"codex": mp4, "greybox": mp4}, "sheet": png, "label": str}
指标：
  face_sharpness  人脸框（deepghs anime_face_detection v1.4_s）缩放到 160px 后的 Laplacian 方差，取中位数
  identity        人脸框 CLIP ViT-L/14 图像嵌入与参考人脸卡的余弦相似度均值（通用 CLIP，不是专用人脸识别模型）
  lipsync_corr    嘴部区域（人脸框下 1/3 中间一半）逐帧张开度（暗像素比例）与配音 RMS 包络的相关；lag=最佳偏移(帧, 8fps)
  motion          灰度 160×96 逐帧平均绝对差
  duration_s / voice_s
"""
import json
import subprocess
import sys

import cv2
import numpy as np

DET = "/Users/mac/.cache/huggingface/hub/models--deepghs--anime_face_detection/snapshots/784dc4c0bb692351ddcdbe6131a050b17d3025d5/face_detect_v1.4_s/model.onnx"
FPS = 8
_net = None
_clip = None


def detect(img):
    global _net
    if _net is None:
        _net = cv2.dnn.readNetFromONNX(DET)
    h, w = img.shape[:2]
    s = 640 / max(h, w)
    r = cv2.resize(img, (round(w * s), round(h * s)))
    pad = np.full((640, 640, 3), 114, np.uint8)
    pad[:r.shape[0], :r.shape[1]] = r
    _net.setInput(cv2.dnn.blobFromImage(pad, 1 / 255, (640, 640), swapRB=True))
    o = _net.forward()[0]
    o = o.T if o.shape[0] < o.shape[1] else o
    b = o[o[:, 4].argmax()]
    if b[4] < 0.3:
        return None
    cx, cy, bw, bh = (float(v) / s for v in b[:4])
    x0, y0 = max(0, int(cx - bw / 2)), max(0, int(cy - bh / 2))
    return x0, y0, min(w, int(cx + bw / 2)), min(h, int(cy + bh / 2))


def clip_embed(imgs):
    global _clip
    import torch
    from transformers import CLIPModel, CLIPProcessor
    if _clip is None:
        _clip = (CLIPModel.from_pretrained("openai/clip-vit-large-patch14").eval(), CLIPProcessor.from_pretrained("openai/clip-vit-large-patch14"))
    m, p = _clip
    with torch.no_grad():
        out = m.get_image_features(**p(images=[cv2.cvtColor(i, cv2.COLOR_BGR2RGB) for i in imgs], return_tensors="pt"))
    out = out if hasattr(out, "shape") else out.pooler_output
    return torch.nn.functional.normalize(out, dim=-1).numpy()


def frames(path):
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-i", path, "-vf", f"fps={FPS}", "-f", "image2pipe", "-vcodec", "png", "-"])
    out, i = [], 0
    sig = b"\x89PNG"
    parts = raw.split(sig)[1:]
    for p in parts:
        out.append(cv2.imdecode(np.frombuffer(sig + p, np.uint8), cv2.IMREAD_COLOR))
    return out


def envelope(audio, n):
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-i", audio, "-ac", "1", "-ar", "8000", "-f", "s16le", "-"])
    a = np.frombuffer(raw, np.int16).astype(np.float32)
    step = 8000 // FPS
    e = np.array([np.sqrt(np.mean(a[i * step:(i + 1) * step] ** 2)) if i * step < len(a) else 0 for i in range(n)])
    return e


def dur(p):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", p]).decode())


def measure(path, voice, ref_emb):
    fr = frames(path)
    boxes = [detect(f) for f in fr]
    first = next((b for b in boxes if b), None)
    sharp, crops, mouth = [], [], []
    for f, b in zip(fr, boxes):
        b = b or first
        if not b:
            mouth.append(0)
            continue
        x0, y0, x1, y1 = b
        c = f[y0:y1, x0:x1]
        g = cv2.cvtColor(cv2.resize(c, (160, 160)), cv2.COLOR_BGR2GRAY)
        sharp.append(cv2.Laplacian(g, cv2.CV_64F).var())
        crops.append(c)
        mh = g[int(160 * .66):int(160 * .92), 40:120]
        mouth.append(float(np.mean(mh < 70)))
    env = envelope(voice, len(fr))
    m = np.array(mouth)
    best = (-2, 0)
    for lag in range(-3, 4):
        a = m[max(0, lag):len(m) + min(0, lag)]
        b = env[max(0, -lag):len(env) + min(0, -lag)]
        k = min(len(a), len(b))
        if k > 4 and a[:k].std() > 1e-6 and b[:k].std() > 1e-6:
            c = float(np.corrcoef(a[:k], b[:k])[0, 1])
            if c > best[0]:
                best = (c, lag)
    k = min(len(m), len(env))
    c0 = float(np.corrcoef(m[:k], env[:k])[0, 1]) if k > 4 and m[:k].std() > 1e-6 else 0.0
    sel = crops[::max(1, len(crops) // 8)][:8]
    ident = float(np.mean(clip_embed(sel) @ ref_emb.T)) if sel else 0.0
    gs = [cv2.cvtColor(cv2.resize(f, (160, 96)), cv2.COLOR_BGR2GRAY).astype(np.float32) for f in fr]
    motion = float(np.mean([np.mean(np.abs(gs[i + 1] - gs[i])) for i in range(len(gs) - 1)])) if len(gs) > 1 else 0
    return {"face_sharpness": round(float(np.median(sharp)) if sharp else 0, 1), "face_found": round(sum(b is not None for b in boxes) / max(1, len(boxes)), 2),
            "identity": round(ident, 4), "lipsync_corr0": round(c0, 3), "lipsync_corr": round(best[0], 3), "lipsync_lag_frames": best[1],
            "motion": round(motion, 2), "duration_s": round(dur(path), 3)}, fr, boxes


def sheet(label, takes, out):
    rows = []
    for name, (fr, _) in takes.items():
        idx = [round(i * (len(fr) - 1) / 4) for i in range(5)]
        tiles = [cv2.resize(fr[i], (384, 256)) for i in idx]
        row = np.hstack(tiles)
        bar = np.full((24, row.shape[1], 3), 20, np.uint8)
        cv2.putText(bar, f"{label} | {name}", (6, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
        rows.append(np.vstack([bar, row]))
    cv2.imwrite(out, np.vstack(rows))


def main():
    spec = json.load(open(sys.argv[1]))
    ref = cv2.imread(spec["ref_face"])
    rb = detect(ref)
    ref_crop = ref[rb[1]:rb[3], rb[0]:rb[2]] if rb else ref
    ref_emb = clip_embed([ref_crop])
    res, keep = {"voice_s": round(dur(spec["voice"]), 3)}, {}
    for name, path in spec["takes"].items():
        m, fr, bx = measure(path, spec["voice"], ref_emb)
        res[name] = m
        keep[name] = (fr, bx)
    if spec.get("sheet"):
        sheet(spec.get("label", ""), keep, spec["sheet"])
    print(json.dumps(res))


if __name__ == "__main__":
    main()
