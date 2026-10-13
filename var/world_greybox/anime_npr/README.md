# Anime NPR PoC (VRM + style compiler) — chapter01 shot18

Optional experiment; not wired into any flow (default pipeline unchanged). Builds on `../toon_vrm_poc`.

Story (AiComicStudio `var/chapter-01/plan.json`, shot 18): *"Tyler and Brad Miller turn and leave laughing,
leaving Thomas Ashford curled up in the corner…"* → the three bullies walk away from camera down the corridor
(+X, toward its depth/exit) while the camera pulls out; Thomas stays at the lockers.

## Fix 1 — wrong walking direction (root cause)
The VRM add-on creates armatures with `rotation_mode='QUATERNION'`. `toon_vrm_poc.py` keyed the take yaw into
`rotation_euler`, which Blender ignores in quaternion mode, so every actor kept its rest facing (−Y, toward the
window wall) while its root translated along +X: the walkers slid sideways "into the wall". (Not a ±Y forward
mismatch: VRM 0.x imports facing −Y, same as the capsule rigs — verified from eye/toe bone positions.)
Fix: `arm.rotation_mode = 'XYZ'` + yaw unwrapping (take yaws jump −228°→90°; unwrapped so Bezier keys do not spin 318°).
`--legacy-yaw-bug` reproduces the old behaviour.

## QA check (automatic, both scripts; `--qa-only` to run without rendering)
`qa_motion()` evaluates the rendered scene per 24 fps frame: forward = head-bone facing of the posed VRM
(eye-midpoint direction), velocity = root XY motion, corridor axis = long horizontal axis of the region AABB,
colliders = `collision:true` world instances. Fails (render aborted unless `--allow-qa-fail`) if, for a moving
actor (>0.35 m/s), cos(forward, velocity) < 0.7 on >10% of frames, the path is not along the corridor axis on
≥70% of moving frames, the body circle (r 0.16 m) intersects a collider, or the point 0.45 m ahead is inside a
collider. Result `qa_motion.json`. Legacy bug: **FAIL** (brad 0/80, kyle 0/84, tyler 0/80 frames facing their
path; worst cos ≈ 0); fixed: **PASS** (100%).

## Fix 2 — character quality
* Recolour is now a hue shift that keeps the texture's relative saturation/value (strands, folds, seams, painted
  lines survive) instead of the luminance→flat-colour remap.
* MToon outlines in screen space (px → fraction of screen height) instead of 2.8 mm world space.
* 1920×1152, 32 TAA samples (was 1280×768/16); shadow rays 2/steps 8.
* Face/eyes come from the untouched VRoid textures (MToon EEVEE output node is active; eye highlight renders).
* Take camera is behind the walkers (as the story requires) → extra front-¾ two-shot close-up (`--cam closeup`).

## Anime Style Compiler
`code/apps/ainer-core/scripts/anime_npr_poc.py --style <preset>`; presets in `code/apps/ainer-core/scripts/anime_styles/`.
Preset (artist units: px, band softness, degrees, hex) → `compile_style()` → MToon params (toony, shift, face
shift, shade tint, rim, outline mode/width/colour), face-normal proxy mix, light rig, compositor params; written to
`<out>/style_compiled.json`.
* `classic_cel`: 3.6 px dark lines + strong inner lines (dilated), toony 0.97, hard key shadow (0.5°), no rim/bloom.
* `modern_anime`: 1.8 px warm-brown lines, light inner lines, toony 0.78, soft key (3°), fresnel rim + warm back-rim sun, bloom 0.35, warm gain.

NPR techniques (own implementation):
* face normal editing — per-head ellipsoid proxy parented to the head bone, Data Transfer custom normals onto the face-skin vertex group (proxy-sphere / Guilty-Gear-style normals);
* 2-band cel (MToon toony), rim (parametric fresnel + optional back sun);
* inner lines — compositor Sobel on Normal pass + log-Depth pass, thresholded, optional dilate, mixed with line colour;
* passes — Combined, Depth, Normal, AOV `base` (albedo texture), AOV `light` (2-band light factor), `line` mask; `--passes` writes them via compositor File Output (`passes_<style>_f<N>/passes/*.png`);
* post — Glare bloom, lift/gamma/gain, saturation (Blender 5.x compositor node group).

## Researched references and licences (no third-party code/assets were copied or added)
| Project | Licence | Use here |
|---|---|---|
| VRM Add-on for Blender 4.10.2 (saturday06) | MIT OR GPL-3.0 | already installed; MToon |
| VRoid sample models (var/assets/vrm) | CC0 / VRoid sample terms | unchanged |
| EmuMan/npr-face-shader | GPL-3.0 | reference (GP-guided face shadow) |
| yeczrtu/QuickSDFBlender | GPL-3.0-or-later | reference (SDF face threshold maps; Windows-only) |
| kents00/NprEevee | GPL-3.0 | reference |
| festivities (StellarToon, miHoYo, Demon Slayer shaders) | GPL-3.0 (redistribute with source link) | reference; Goo Engine-targeted |
| Lightning Boy Shader 2.1 | proprietary EULA (paid, no redistribution, Blender ≤3.4) | not usable |

## Run
    B=/Applications/Blender.app/Contents/MacOS/Blender
    caffeinate -i $B -b --factory-startup --python code/apps/ainer-core/scripts/anime_npr_poc.py -- <job.json> <out> \
       --style classic_cel|modern_anime [--cam closeup] [--range 25:97] [--still N --passes]
    # QA only: ... toon_vrm_poc.py -- <job.json> <out> --qa-only [--legacy-yaw-bug]
