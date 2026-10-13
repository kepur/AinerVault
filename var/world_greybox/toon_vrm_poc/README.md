# Anime (VRM / MToon) PoC — chapter01 shot18

Optional experiment; not wired into any pipeline flow (default flow unchanged). Follow-up of `../toon_poc` (capsule mannequins → VRoid anime characters).

Source take: `var/world_greybox/runs/wpr_01M4SXHWJKKKH7JZZMKQTPPBP6/shot18/greybox_a5/job.json` (4 actors, corridor, camera `pull_out`, 4.125 s). Camera keys are exactly the take's.

## Setup (one-off)
1. VRM Add-on for Blender v4.10.2 (saturday06, MIT OR GPL-3.0) as a Blender extension:
   `Blender -b --factory-startup --command extension install-file -r user_default -e VRM_Addon_for_Blender-Extension-4_10_2.zip`
   (works headless; the script enables `bl_ext.user_default.vrm`).
2. Models in `var/assets/vrm/` (not committed; licences in `var/assets/vrm/LICENSES.md`):
   thomas = Sakurada_Fumiriya (CC0), brad + kyle = HairSample_Male (CC0), tyler = AvatarSample_C (VRoid sample terms: commercial/alteration OK, no credit).

## Run (Blender 5.2.2)
    B=/Applications/Blender.app/Contents/MacOS/Blender
    caffeinate -i $B -b --factory-startup --python code/apps/ainer-core/scripts/toon_vrm_poc.py -- \
        <job.json> var/world_greybox/toon_vrm_poc/render_vrm [--vrm-dir var/assets/vrm] [--fps 24] [--res 1280x768] [--samples 16] [--still N]
    ffmpeg -framerate 24 -i render_vrm/frames/%04d.png -i <run>/parts/18.mp4 -map 0:v -map 1:a -vf eq=saturation=1.15 \
        -c:v libx264 -crf 16 -pix_fmt yuv420p -c:a aac -shortest shot18_vrm.mp4

## What it does
- World/env: rebuilt with `world_multicam.build_world`; env cel shader reused from `toon_render_poc.py` (now import-safe) + checker floor tiles and brick-texture locker panels.
- Characters: VRM imported per actor (duplicates get per-actor material/texture copies), scaled to `height_m` (stout ×1.12 wide). Recolour = hair/brows/tops/bottoms texture pixels remapped by luminance to the actor colour (green Brad, red Tyler, blond Kyle, black-haired Thomas in navy vest); VRoid hair emissive highlight retinted.
- Motion: root = take pos/yaw (+hips_dz) on the armature object; bones = take's Mixamo-named per-bone deltas retargeted to VRM humanoid bones: capsule chain delta A_b = A_parent·D_b, VRM target T_b = A_b·C_b, local = T_parent⁻¹·T_b (in bone rest frame). C_b = rest-direction correction for upper/lower arms (+hand follows) → VRM T-pose becomes the capsule's arms-down rest. 8 fps keys spaced on 24 fps, Bezier in-betweens.
- Shading: add-on MToon on EEVEE: toony 0.95 (2 bands), shade colour lavender, face shading shift +0.55 (face stays lit, no blotchy face shadows), parametric rim, world-space outlines 2.8 mm (face 1.2 mm). Sun with 4° angle + shadow filter (no acne seen). Saturation +15 % at encode.

## Timing (M2 Max, 1280×768, 16 TAA)
- Build (4 VRM imports + recolour + keys): ~32 s. Render 97 frames: 130 s → **1.34 s/frame** (per-frame list in `render_vrm/timing.json`).
- ≈ 1 min @24 fps (1440 frames): ~32 min render + ~0.5 min build/encode.

## Outputs
`shot18_vrm.mp4` (with shot18 audio), `shot18_side_by_side.mp4` (prev toon | VRM anime | final), `stills/vrm_f{1,49,97}.png`, `stills/side_by_side_t2s.png`.

## Known issues
- brad & kyle share the same base model (only hair/clothes colours differ); need a 4th distinct male VRM (VRoid Studio export).
- Take motion is coarse (8 fps keys, simple swing walk) → slight foot sliding; no finger curl, no spring bones (hair/clothes static), no blinks/lip sync.
- Characters mostly seen from the side/back in this shot, so faces barely visible.
- Environment still greybox (flat walls, no props textures); lighting is a single sun.
