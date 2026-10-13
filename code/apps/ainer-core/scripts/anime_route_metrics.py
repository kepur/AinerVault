"""Flicker + identity metrics for anime route comparison (optional PoC tool).

    python anime_route_metrics.py --frames 25:97:3 name=<frames_dir> [name=<frames_dir> ...] > metrics.json

flicker  = mean |I_t - I_{t-1}| (0..255, grey, 640px wide) over the 8 fps keyframe sequence; reported with the
           3D source's own motion diff for reference (pure motion gives a baseline > 0).
identity = deepghs CCIP (anime character embedding, caformer-24) cosine similarity of the largest-detected face
           (deepghs anime_face_detection v1.4 YOLO) in every keyframe vs the first keyframe and vs the mean.
"""
import glob, json, sys
import numpy as np
import onnxruntime as ort
from PIL import Image

HUB = "/Users/mac/.cache/huggingface/hub"
DET = ort.InferenceSession(glob.glob(f"{HUB}/models--deepghs--anime_face_detection/snapshots/*/face_detect_v1.4_s/model.onnx")[0])
CCIP = ort.InferenceSession(glob.glob(f"{HUB}/models--deepghs--ccip_onnx/snapshots/*/ccip-caformer-24-randaug-pruned/model_feat.onnx")[0])


def faces(img, conf=0.3):
    W0, H0 = img.size; s = 640 / max(W0, H0)
    im = img.convert("RGB").resize((round(W0 * s), round(H0 * s)))
    pad = Image.new("RGB", (640, 640), (114, 114, 114)); pad.paste(im, (0, 0))
    x = np.asarray(pad, np.float32).transpose(2, 0, 1)[None] / 255
    o = DET.run(None, {"images": x})[0][0]           # (5, N) or (N, 5)
    if o.shape[0] < o.shape[1]:
        o = o.T
    o = o[o[:, 4] > conf]
    out = []
    for cx, cy, w, h, c in o[:, :5]:
        out.append((c, [(cx - w / 2) / s, (cy - h / 2) / s, (cx + w / 2) / s, (cy + h / 2) / s]))
    out.sort(key=lambda t: -(t[1][2] - t[1][0]) * (t[1][3] - t[1][1]))
    return out


def emb(img):
    x = np.asarray(img.convert("RGB").resize((384, 384), Image.BICUBIC), np.float32) / 255
    x = ((x - 0.5) / 0.5).transpose(2, 0, 1)[None]
    e = CCIP.run(None, {"input": x})[0][0]
    return e / np.linalg.norm(e)


def run(frames_dir, rng):
    imgs = [Image.open(f"{frames_dir}/{f:04d}.png") for f in rng]
    g = [np.asarray(i.convert("L").resize((640, round(640 * i.size[1] / i.size[0]))), np.float32) for i in imgs]
    fl = [float(np.abs(g[k] - g[k - 1]).mean()) for k in range(1, len(g))]
    E, miss = [], 0
    for im in imgs:
        f = faces(im)
        if not f:
            miss += 1; continue
        x0, y0, x1, y1 = f[0][1]; m = 0.25 * (x1 - x0)
        E.append(emb(im.crop((max(0, x0 - m), max(0, y0 - m), x1 + m, y1 + m))))
    E = np.array(E)
    r = {"flicker_mean": round(float(np.mean(fl)), 2), "flicker_max": round(float(np.max(fl)), 2),
         "faces_found": len(E), "faces_missed": miss}
    if len(E) > 1:
        mu = E.mean(0); mu /= np.linalg.norm(mu)
        r["ccip_vs_first_mean"] = round(float((E[1:] @ E[0]).mean()), 3)
        r["ccip_vs_first_min"] = round(float((E[1:] @ E[0]).min()), 3)
        r["ccip_vs_mean_mean"] = round(float((E @ mu).mean()), 3)
    return r


if __name__ == "__main__":
    a = sys.argv[1:]
    i = a.index("--frames"); f0, f1, st = map(int, a[i + 1].split(":")); del a[i:i + 2]
    rng = list(range(f0, f1 + 1, st))
    print(json.dumps({k: run(v, rng) for k, v in (x.split("=", 1) for x in a)}, indent=1))
