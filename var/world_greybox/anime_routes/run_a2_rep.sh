#!/bin/bash
# usage: run_a2_rep.sh <frames f0:f1:st> <out> [repaint args...]   (resumable: --skip-existing)
cd /Users/mac/AinerWorkFlow/AinerHub_IDEA
O=var/world_greybox/anime_routes
while screen -ls | grep -q a2src; do sleep 10; done
while pgrep -f ltx25_infer >/dev/null; do sleep 30; done
PYTORCH_ENABLE_MPS_FALLBACK=1 /Users/mac/Code_Start/ml-stable-diffusion/LatentSync/venv/bin/python code/apps/ainer-core/scripts/anime_repaint_poc.py \
  $O/routeA2_src $2 --frames $1 --skip-existing "${@:3}" >> $2.log 2>&1
echo "- [x] repaint $2 $1 ${*:3} done $(date +%T)" >> $O/STATE.md
