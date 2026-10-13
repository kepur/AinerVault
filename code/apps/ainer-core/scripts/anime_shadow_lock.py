"""Shadow lock + shadow-flicker metric for repainted anime frames (optional PoC tool).

Shadow shapes are taken from the 3D render (light AOV, thresholded = the cel terminator), not from diffusion:
  1. character mask   = near depth (3D depth pass)
  2. repaint's own shadow = pixels darker than 0.72 x local lit level (max-filter of luminance), excluding ink
     lines/eyes (< 0.25 x lit level) -> "deshade" them back towards the local lit colour
  3. re-impose the 3D shadow mask as a multiply layer with ONE fixed shadow tone (cool lavender)
So every keyframe gets identical, 3D-coherent shadow shapes; the drawn line/colour look of the repaint is kept.

    python anime_shadow_lock.py lock <repaint_frames> <src_passes_dir> <out_frames> [--tone 0.70,0.66,0.84]
    python anime_shadow_lock.py metric --frames 25:97:2 <src_passes_dir> --flow-src <3d_frames> name=<frames_dir> ...
"""
import glob, json, os, sys
import numpy as np
import cv2


def rd(p, size=None, gray=False):
    im = cv2.imread(p, cv2.IMREAD_GRAYSCALE if gray else cv2.IMREAD_COLOR)
    if size is not None and im.shape[:2] != size:
        im = cv2.resize(im, (size[1], size[0]), interpolation=cv2.INTER_AREA)
    return im.astype(np.float32) / 255


def char_mask(pdir, size, thr=0.06):
    d = rd(os.path.join(pdir, "depth.png"), size, True)
    m = (d < thr).astype(np.float32)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    return cv2.GaussianBlur(m, (0, 0), 1.2)


def shadow3d(pdir, size, thr=0.5):
    l = rd(os.path.join(pdir, "light.png"), size, True)
    return cv2.GaussianBlur((l < thr).astype(np.float32), (0, 0), 1.0)


def own_shadow(img, cm=None):
    y = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if cm is not None:                      # lit level from character pixels only (no sky/wall bleed at edges)
        y = y * (cm > 0.5)
    k = max(15, int(img.shape[1] / 48) | 1)
    lit = cv2.GaussianBlur(cv2.dilate(y, np.ones((k, k), np.uint8)), (0, 0), k / 3)
    sh = (y < 0.72 * lit) & (y > 0.25 * lit)
    return y, lit, sh


def lock(img, pdir, tone):
    size = img.shape[:2]
    cm = char_mask(pdir, size); s3 = shadow3d(pdir, size)
    y, lit, sh = own_shadow(img, cm)
    gain = np.clip(0.9 * lit / np.maximum(y, 1e-3), 1.0, 1.45)
    gain = np.where(sh, gain, 1.0).astype(np.float32)
    gain = cv2.GaussianBlur(gain, (0, 0), 0.8)
    de = np.clip(img * gain[..., None], 0, 1)
    tone_bgr = np.array(tone[::-1], np.float32)
    shaded = de * (1 - s3[..., None] * (1 - tone_bgr))
    return img * (1 - cm[..., None]) + shaded * cm[..., None]


def _flow(a, b):
    """dense flow such that a(x) ~ b(x + flow)  (Farneback on grey 3D renders)"""
    ga = cv2.cvtColor((a * 255).astype(np.uint8), cv2.COLOR_BGR2GRAY)
    gb = cv2.cvtColor((b * 255).astype(np.uint8), cv2.COLOR_BGR2GRAY)
    return cv2.calcOpticalFlowFarneback(ga, gb, None, 0.5, 4, 25, 5, 7, 1.5, 0)


def shadow_flicker(frames_dir, pdir_root, rng, flow_src):
    """Motion-compensated shadow change: previous keyframe's shadow mask is warped to the current keyframe with
    optical flow computed on the 3D renders (same for every route), then XOR inside the character mask."""
    prev, xs = None, []
    for f in rng:
        img = cv2.resize(rd(os.path.join(frames_dir, f"{f:04d}.png")), (960, 576), interpolation=cv2.INTER_AREA)
        src = cv2.resize(rd(os.path.join(flow_src, f"{f:04d}.png")), (960, 576), interpolation=cv2.INTER_AREA)
        cm = char_mask(os.path.join(pdir_root, f"f{f:04d}"), img.shape[:2]) > 0.5
        cm = cv2.erode(cm.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
        _, _, sh = own_shadow(img, cm.astype(np.float32))
        if prev is not None:
            fl = _flow(src, prev[2])
            gx, gy = np.meshgrid(np.arange(960, dtype=np.float32), np.arange(576, dtype=np.float32))
            w = lambda m: cv2.remap(m.astype(np.float32), gx + fl[..., 0], gy + fl[..., 1], cv2.INTER_NEAREST) > 0.5  # noqa: E731
            both = cm & w(prev[1])
            xs.append(float((sh ^ w(prev[0]))[both].mean()) if both.any() else 0.0)
        prev = (sh, cm, src)
    return float(np.mean(xs)), float(np.max(xs))


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[0] == "lock":
        src, pas, out = a[1:4]
        tone = [float(x) for x in (a[a.index("--tone") + 1] if "--tone" in a else "0.70,0.66,0.84").split(",")]
        os.makedirs(out, exist_ok=True)
        for p in sorted(glob.glob(os.path.join(src, "*.png"))):
            f = int(os.path.basename(p)[:4]); img = rd(p)
            res = lock(img, os.path.join(pas, f"f{f:04d}"), tone)
            cv2.imwrite(os.path.join(out, os.path.basename(p)), (res * 255 + 0.5).astype(np.uint8))
        print("LOCK_DONE", out)
    else:
        i = a.index("--frames"); f0, f1, st = map(int, a[i + 1].split(":")); del a[i:i + 2]
        pas = a[1]; flow_src = a[a.index('--flow-src') + 1] if '--flow-src' in a else None
        a = [x for x in a if x != '--flow-src' and x != flow_src]; rng = list(range(f0, f1 + 1, st)); res = {}
        for k, v in (x.split("=", 1) for x in a[2:]):
            m, mx = shadow_flicker(v, pas, rng, flow_src); res[k] = {"shadow_flicker_mean": round(m, 4), "shadow_flicker_max": round(mx, 4)}
        base = res.get("3d", {}).get("shadow_flicker_mean")
        if base:
            for k in res:
                res[k]["vs_3d"] = round(res[k]["shadow_flicker_mean"] / base, 2)
        print(json.dumps(res, indent=1))
