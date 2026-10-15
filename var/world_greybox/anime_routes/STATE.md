# anime_routes state (checkpoint)
- [x] route B render (routeB/frames 25-97, inked_key + Line Art), routeB_closeup.mp4
- [x] route A sources (routeA_src: modern_anime closeup keyframes 25:97:3 + passes/fNNNN)
- [x] route A repaint (screen repA, routeA/frames, log routeA.log) — resume: run_repaint.sh 25:97:3 var/world_greybox/anime_routes/routeA --cn-scale 0.8 (skips nothing; rerun only missing frames manually)
- [x] encode routeA_closeup.mp4 (hold x3), side_by_side.mp4, face stills, metrics.json, README, commit

## A2 (shadow-stable + motion) — started 17:40
- [ ] routeA2_src: modern_anime closeup + --secondary, all frames 25-97 with passes (screen a2src)
- [ ] routeA2 repaint at 12 fps keys (25:97:2), flow-warped init + shadow lock (screen a2rep)
- [ ] variants: twos hold / RIFE 24 / threes; metrics; side_by_side; README; commit
- [ ] A/B test a2t_base vs a2t_warp keys 25:37:2 (screen a2rep)
- [x] routeA2_src rendered 17:42:40
- [x] repaint var/world_greybox/anime_routes/a2t_base 25:37:2 --strength 0.62 --cn-scale 0.8 done 17:53:05
- [x] repaint var/world_greybox/anime_routes/a2t_warp 25:37:2 --strength 0.5 --cn-scale 0.9 --prev-warp 0.5 done 17:59:17
- A/B result: prev-warp feedback accumulates texture (shadow 1.81x vs base 1.72x, CCIP 0.80 vs 0.88) -> dropped. Full A2: strength 0.55 cn 0.9 no warp, 25:97:2 (screen a2full)
- [x] repaint var/world_greybox/anime_routes/routeA2 25:97:2 --strength 0.55 --cn-scale 0.9 --skip-existing done 18:35:48
- [x] A2 post: lock, variants, metrics, side_by_side_A2 18:38:16
- [x] A2 post: lock, variants, metrics, side_by_side_A2 18:47:13
- shadow vs3d (step6 common keys): routeA 1.25, A2 raw 1.03, A2+lock 1.25 -> use raw. Rebuilding variants from raw (screen a2var)
- [x] close-up A2 final = raw (no lock), variants twos/threes/rife24 rebuilt, side_by_side_A2.mp4 rebuilt 19:04:42
