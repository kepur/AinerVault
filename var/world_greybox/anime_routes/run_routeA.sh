#!/bin/bash
cd /Users/mac/AinerWorkFlow/AinerHub_IDEA
O=var/world_greybox/anime_routes
while screen -ls | grep -q routeB; do sleep 10; done
while pgrep -f ltx25_infer >/dev/null; do sleep 30; done
F=$(seq -s, 25 3 97)
/Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup --python code/apps/ainer-core/scripts/anime_npr_poc.py -- \
  var/world_greybox/runs/wpr_01M4SXHWJKKKH7JZZMKQTPPBP6/shot18/greybox_a5/job.json $O/routeA_src --style modern_anime --cam closeup --still $F --passes > $O/routeA_src.log 2>&1
while pgrep -f ltx25_infer >/dev/null; do sleep 30; done
PYTORCH_ENABLE_MPS_FALLBACK=1 /Users/mac/Code_Start/ml-stable-diffusion/LatentSync/venv/bin/python code/apps/ainer-core/scripts/anime_repaint_poc.py $O/routeA_src $O/routeA --frames ${1:-25:97:3} > $O/routeA.log 2>&1
echo DONE >> $O/routeA.log
