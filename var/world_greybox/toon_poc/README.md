# Toon (三渲二) PoC — chapter01 shot18

Optional experiment; not wired into any pipeline flow.

Source: `var/world_greybox/runs/wpr_01M4SXHWJKKKH7JZZMKQTPPBP6/shot18/greybox_a5/job.json`
(world_multicam take: school corridor, 4 actors walking away, camera `pull_out`, 4.125 s).

Run (Blender 5.2.2, ~20 s / ~85 s):

    B=/Applications/Blender.app/Contents/MacOS/Blender
    caffeinate -i $B -b --factory-startup --python code/apps/ainer-core/scripts/toon_render_poc.py -- \
        <job.json> var/world_greybox/toon_poc/render_toon [--lineart] [--fps 24] [--res 1280x768] [--samples 16]
    ffmpeg -framerate 24 -i render_toon/frames/%04d.png -i <run>/parts/18.mp4 -map 0:v -map 1:a \
        -c:v libx264 -crf 16 -pix_fmt yuv420p -c:a aac -shortest shot18_toon.mp4

## Settings
- Scene rebuilt with `blender_worker/world_multicam.py` build_world/build_actors (same boxes, Mixamo-named capsule rigs, camera_frames).
- Retime: 8 fps take keys placed every 3 frames on a 24 fps timeline, Bezier in-betweens → 97 frames.
- Shader: white Diffuse → Shader to RGB → RGB→BW → ColorRamp CONSTANT (0 / 0.18 / 0.55: deep shadow, mid, lit; shadow bands tinted lavender, skin bands pinkish) → Multiply with zone colour → Emission.
- Zones per actor: hair = actor hue (saturated, hair-cap mesh from head sphere), skin = head/neck/forearms/hands/nose, shirt = per-actor uniform colour, pants, shoes, 2 dark eye ellipsoids.
- Environment palette: blue lockers, cream walls/ceiling, beige floor, wood door/props.
- Outlines: Solidify (flip normals, offset 1, thickness 8 mm actors / 15 mm env, material offset) + backface-culled near-black emission.
- Line Art variant: scene Line Art grease pencil (`--lineart`) on top of hull outlines.
- Light: one fixed Sun 2.2, angle 2°; world = flat grey for lighting, camera-ray sky gradient (window-space Y).
- EEVEE 16 TAA samples, Standard view transform, Look None, 1280x768 (shot aspect 5:3).

## Timing (M2 Max)
- Toon: 0.21 s/frame avg (97 frames = 20 s; first-ever run ~4.5 s shader compile).
- Toon + Line Art: 0.87 s/frame (85 s).
- ≈ 1 min @24 fps (1440 frames): ~5 min toon, ~21 min with Line Art (+ build/encode seconds).

## Outputs
`shot18_toon.mp4`, `shot18_lineart.mp4` (with shot18 audio), `shot18_side_by_side.mp4` (clay | final / toon | lineart), `stills/`, `render_*/timing.json`.

## Limitations / next steps
- Characters are capsule mannequins → reads as "toon figures", not anime characters. Next: VRoid/VRM models (VRM add-on for Blender) retargeted to the Mixamo skeleton; MToon-like shader.
- No faces / expressions; next: face normal editing (sphere-projected normals) for clean anime face shading, shape keys, Rhubarb lip sync from dialogue audio.
- Environment is blocky greybox; needs real assets/textures or painted backgrounds.
- Sun shadows can show slight acne; tune shadow settings/light angle per shot.
