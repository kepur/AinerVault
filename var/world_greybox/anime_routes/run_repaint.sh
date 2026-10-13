#!/bin/bash
cd /Users/mac/AinerWorkFlow/AinerHub_IDEA
O=var/world_greybox/anime_routes
while pgrep -f ltx25_infer >/dev/null; do sleep 30; done
PYTORCH_ENABLE_MPS_FALLBACK=1 /Users/mac/Code_Start/ml-stable-diffusion/LatentSync/venv/bin/python code/apps/ainer-core/scripts/anime_repaint_poc.py $O/routeA_src ${2:-$O/routeA} --frames ${1:-25:97:3} "${@:3}" > ${2:-$O/routeA}.log 2>&1
echo DONE >> ${2:-$O/routeA}.log
