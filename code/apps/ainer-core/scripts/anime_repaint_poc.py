"""Route A PoC: 3D render passes -> local anime SDXL repaint (Animagine XL 3.1 + xinsir ControlNet-Union promax).
Optional, not wired into any flow. Runs with any python that has torch(MPS)+diffusers>=0.32 (no installs here;
e.g. the LatentSync venv). Inputs = anime_npr_poc.py output with --passes (passes/fNNNN/{line,depth,...}.png) and
frames/NNNN.png (the 3D render used as img2img init).

    python anime_repaint_poc.py <npr_out_dir> <out_dir> --frames 25:97:3 [--strength 0.62] [--steps 28] [--seed 1234]
        [--res 1280x768] [--ref-blend 0.0]

Identity/temporal: fixed seed (same initial noise every keyframe), same prompt, ControlNet line+depth from the 3D
passes pin geometry; --ref-blend mixes a fraction of the PREVIOUS repainted keyframe into the init image (colour /
design memory). 8 fps keyframes (every 3rd 24 fps frame) are held x3 at encode time (anime "on threes").
"""
import argparse, glob, json, os, time
import numpy as np
import torch
from PIL import Image, ImageOps
from diffusers import (ControlNetUnionModel, StableDiffusionXLControlNetUnionImg2ImgPipeline,
                       DPMSolverMultistepScheduler)
from huggingface_hub import snapshot_download

ap = argparse.ArgumentParser()
ap.add_argument("src"); ap.add_argument("out")
ap.add_argument("--frames", default="25:97:3"); ap.add_argument("--strength", type=float, default=0.62)
ap.add_argument("--steps", type=int, default=28); ap.add_argument("--seed", type=int, default=1234)
ap.add_argument("--res", default="1280x768"); ap.add_argument("--ref-blend", type=float, default=0.0)
ap.add_argument("--cfg", type=float, default=7.0)
ap.add_argument("--prev-warp", type=float, default=0.0,
                help="blend weight of the previous repainted keyframe, optical-flow warped (Farneback on the 3D renders)")
ap.add_argument("--skip-existing", action="store_true")
ap.add_argument("--cn-scale", type=float, default=0.7)
ap.add_argument("--prompt", default=None, help="override positive prompt (default: close-up prompt)")
a = ap.parse_args()
W, H = map(int, a.res.split("x"))
os.makedirs(os.path.join(a.out, "frames"), exist_ok=True)

PROMPT = ("masterpiece, best quality, very aesthetic, anime screenshot, 2boys, blond hair, blue eyes, navy hoodie, green hair, "
          "white hoodie, school hallway, bold black lineart, thick outlines, flat color, cel shading, hard shadow, "
          "sharp focus, vivid colors, detailed eyes")
NEG = ("lowres, worst quality, low quality, blurry, hazy, washed out, faded, pastel, 3d, render, photorealistic, "
       "gradient, bad anatomy, deformed face, extra fingers, text, watermark, 1girl, female")
if a.prompt:
    PROMPT = a.prompt

dev = "mps" if torch.backends.mps.is_available() else "cpu"
base = snapshot_download("cagliostrolab/animagine-xl-3.1", local_files_only=True)
if True:   # promax ships as config_promax.json + diffusion_pytorch_model_promax.safetensors
    d = snapshot_download("xinsir/controlnet-union-sdxl-1.0", allow_patterns=["config_promax.json", "*promax.safetensors"])
    tmp = os.path.join(a.out, "_cn"); os.makedirs(tmp, exist_ok=True)
    for s_, d_ in (("config_promax.json", "config.json"), ("diffusion_pytorch_model_promax.safetensors",
                                                            "diffusion_pytorch_model.safetensors")):
        t = os.path.join(tmp, d_)
        if not os.path.exists(t):
            os.symlink(os.path.realpath(os.path.join(d, s_)), t)
    cn = ControlNetUnionModel.from_pretrained(tmp, torch_dtype=torch.float16)
pipe = StableDiffusionXLControlNetUnionImg2ImgPipeline.from_pretrained(base, controlnet=cn, torch_dtype=torch.float16)
pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config, use_karras_sigmas=True,
                                                         algorithm_type="dpmsolver++")
pipe.vae.to(torch.float32); pipe.vae.config.force_upcast = True
pipe.to(dev)
pipe.set_progress_bar_config(disable=True)

f0, f1, st = map(int, a.frames.split(":"))
times, prev, log = [], None, []
for fr in range(f0, f1 + 1, st):
    t = time.time()
    outp = os.path.join(a.out, "frames", f"{fr:04d}.png")
    init = Image.open(os.path.join(a.src, "frames", f"{fr:04d}.png")).convert("RGB").resize((W, H), Image.LANCZOS)
    init3d = init.copy()
    if a.skip_existing and os.path.exists(outp):          # resume: reuse finished keyframes
        prev, init_3d_prev = Image.open(outp).convert("RGB"), init3d
        continue
    pdir = os.path.join(a.src, "passes", f"f{fr:04d}")
    line = ImageOps.invert(Image.open(os.path.join(pdir, "line.png")).convert("L")).convert("RGB").resize((W, H))
    depth = ImageOps.invert(Image.open(os.path.join(pdir, "depth.png")).convert("L")).convert("RGB").resize((W, H))
    if prev is not None and a.ref_blend > 0:
        init = Image.blend(init, prev, a.ref_blend)
    if prev is not None and a.prev_warp > 0:
        import cv2
        g1 = cv2.cvtColor(np.asarray(init_3d_prev), cv2.COLOR_RGB2GRAY)
        g2 = cv2.cvtColor(np.asarray(init), cv2.COLOR_RGB2GRAY)
        fl = cv2.calcOpticalFlowFarneback(g2, g1, None, 0.5, 4, 31, 5, 7, 1.5, 0)   # cur -> prev
        gx, gy = np.meshgrid(np.arange(W, dtype=np.float32), np.arange(H, dtype=np.float32))
        warped = cv2.remap(np.asarray(prev), gx + fl[..., 0], gy + fl[..., 1], cv2.INTER_LINEAR,
                           borderMode=cv2.BORDER_REPLICATE)
        init = Image.blend(init, Image.fromarray(warped), a.prev_warp)
    g = torch.Generator("cpu").manual_seed(a.seed)
    # union control_mode: 1 = depth, 3 = canny/lineart
    img = pipe(prompt=PROMPT, negative_prompt=NEG, image=init, control_image=[depth, line], control_mode=[1, 3],
               controlnet_conditioning_scale=a.cn_scale, strength=a.strength,
               num_inference_steps=a.steps, guidance_scale=a.cfg, width=W, height=H, generator=g).images[0]
    img.save(outp)
    prev, init_3d_prev = img, init3d
    times.append(time.time() - t)
    print(f"REPAINT {fr} {times[-1]:.1f}s", flush=True)
json.dump({"frames": a.frames, "res": [W, H], "strength": a.strength, "steps": a.steps, "seed": a.seed, "cfg": a.cfg,
           "ref_blend": a.ref_blend, "prev_warp": a.prev_warp, "cn_scale": a.cn_scale,
           "model": "cagliostrolab/animagine-xl-3.1", "controlnet": "xinsir/controlnet-union-sdxl-1.0 (promax)",
           "per_frame_s": [round(x, 1) for x in times], "avg_s": round(sum(times[1:]) / max(1, len(times) - 1), 1) if times else None,
           "first_s": round(times[0], 1) if times else None, "device": dev, "prompt": PROMPT, "negative": NEG},
          open(os.path.join(a.out, "timing.json"), "w"), indent=1)
