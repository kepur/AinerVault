# Anime routes A/B — shot18 front-3/4 close-up (frames 25–97, 3 s)
Optional PoC; default flow unchanged. Style target: crisp variable-width ink, flat colours + one hard shadow, glossy eyes, strand hair (key-art look; reference used for style only).

## Route A — 3D control + AI repaint
`code/apps/ainer-core/scripts/anime_repaint_poc.py` (run with the existing LatentSync venv: torch MPS + diffusers 0.32.2, nothing installed).
Inputs: `anime_npr_poc.py --style modern_anime --cam closeup --passes` at the 8 fps keyframes 25:97:3 → `routeA_src/` (frames + passes/fNNNN/{line,depth,normal,base,light}).
Model: Animagine XL 3.1 (already in HF cache; Fair AI Public License 1.0-SD) + xinsir/controlnet-union-sdxl-1.0 promax (downloaded, 2.5 GB, Apache-2.0); control = depth (mode 1) + 3D line pass (mode 3), scale 0.8; img2img strength 0.62, 28 steps DPM++ 2M Karras, cfg 7, fixed seed 1234, 1280×768. Keyframes held ×3 (anime "on threes").
No IP-Adapter/openpose installed (not used). ComfyUI was not running and has no SDXL anime/ControlNet models, so diffusers was used directly.

## Route B — pure 3D
`anime_npr_poc.py --style inked_key --cam closeup` : Grease Pencil Line Art on the characters (contour/crease/material/intersection, world-space radius → thinner with depth, tapered), face set to occlusion-only (no scar lines), MToon toony 1.0 one hard shade tone, face proxy normals 100 %, saturation 1.3, no bloom.
Models: unchanged VRoid samples (CC0 / VRoid sample terms). No clearly better free *male* anime model was downloadable without login (VRoid Hub needs login; Unity-chan/Miraikomachi are female and carry use restrictions/logo requirements) → not swapped.

## Metrics (keyframes 25:97:3, `metrics.json`; tool `anime_route_metrics.py`)
| | flicker mean/max (0-255) | CCIP vs first mean/min | CCIP vs mean | s/frame |
|---|---|---|---|---|
| current modern_anime | 16.0 / 20.9 | 0.77 / 0.60 | 0.90 | 2.8 (24 fps) |
| A repaint | 18.3 / 23.4 | 0.76 / 0.54 | 0.86 | 56.6 per keyframe (+~3 s 3D) |
| B inked_key | 20.4 / 25.7 | 0.68 / 0.57 | 0.90 | 8.2 (24 fps) |
Flicker includes real motion (camera/characters move), so the 3D route's value is the baseline. CCIP uses the largest detected face; Kyle/Brad swap as "largest" in some frames, which lowers vs-first scores for all routes.
1 min estimate: A at 8 fps = 480 keyframes × 57 s ≈ 7.6 h (+3D passes ~25 min); B = 1440 × 8.2 s ≈ 3.3 h (+1 min build).

## Assessment vs target (honest)
- A: looks most like a drawn anime screenshot (flat fills, drawn eyes with highlights), but lines are thin/soft, not crisp variable-width ink; colour fringes on hoodie edges; small design drift between keyframes (eye colour of side characters, hair tips); 20× slower.
- B: perfectly stable identity and geometry, crisp hair-strand ink lines, hard shadow — but still reads as 3D (texture gradients on clothes, model face design is generic VRoid); far from key-art level.
- Neither reaches the reference. Biggest remaining gap is character design/faces (models), and true ink line quality.

Outputs: `routeA_closeup.mp4`, `routeB_closeup.mp4`, `side_by_side.mp4` (modern | A | B), `stills/{modern,routeA,routeB}_face_f{25,61,97}.png`, `stills/side_by_side_face_f61.png`, `routeA/timing.json`, `routeB/timing.json`.

## Route A2 — temporally stabilised repaint + motion fluidity (close-up)

Source: `routeA2_src/` = modern_anime close-up re-rendered with `--secondary` (hip/chest counter-rotation, vertical bob,
breathing, small head turns, blinks via `Fcl_EYE_Close`), passes for every frame.
Repaint: `anime_repaint_poc.py routeA2_src routeA2 --frames 25:97:2 --strength 0.55 --cn-scale 0.9` (12 fps keys, seed 1234).

What was tried for shadow flicker (keys 25:37:2 A/B, then full run):
| config | shadow flicker vs 3D (motion-comp.) | CCIP vs first |
|---|---|---|
| strength 0.62 / cn 0.8 (old Route A settings) | 1.72x | 0.88 |
| strength 0.5 / cn 0.9 + flow-warped prev key init 0.5 | 1.81x (feedback accumulates texture) — dropped | 0.80 |
| **strength 0.55 / cn 0.9, no warp (A2)** | 1.47x on the A/B keys | — |
| A2 + 3D shadow lock (post) | 1.38x on A/B keys, but 1.25x vs 1.03x over the full shot — not used | — |

Same keyframes over the full shot (25:97:6, shared by both runs): **old routeA 1.25x → A2 1.03x of 3D shadow flicker**
(effectively the 3D's own shading change). Over all A2 keys (25:97:2): A2 1.37x, overall flicker 13.6 vs 3D 12.5, CCIP 0.77 vs 3D 0.80.
Fix = lower denoise + stronger depth/lineart control; optical-flow init and post shadow-lock did not help. Luminance deflicker (ffmpeg `deflicker`) on all A2 encodes.
Time: 55.6 s/key avg (some contention), 37 keys ≈ 34 min for 3 s. 1 min @ 12 fps keys ≈ 720 keys ≈ 8–11 h on this Mac.

Timing variants (`anime_timing_variants.sh`): `routeA2_closeup_threes.mp4` (8 fps hold, nearest key on 3-grid),
`routeA2_closeup_twos.mp4` (12 fps hold), `routeA2_closeup_rife24.mp4` (RIFE 4.25 MLX x2) = `routeA2_closeup.mp4`.
`side_by_side_A2.mp4`: modern_anime 3D | routeA old | A2 threes / A2 twos | A2 RIFE24.
Verdict: RIFE 24 is the most fluid for this slow walk; in-between frames show no visible morphing (stills/rife_consec_48_51.png) because the keys are already consistent. Twos is the safe anime look; threes looks choppy at this camera speed.
Remaining: small eye-colour drift on a few keys (blue→violet), hoodie string colour varies.
Stills: stills/a2raw_consec_49_55.png, stills/face_cmp_0061.png (3D | routeA | A2), stills/sbs_A2_t15.png.
