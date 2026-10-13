#!/bin/bash
cd /Users/mac/AinerWorkFlow/AinerHub_IDEA
O=var/world_greybox/anime_routes
while pgrep -f ltx25_infer >/dev/null; do sleep 30; done
/Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup --python code/apps/ainer-core/scripts/anime_npr_poc.py -- \
  var/world_greybox/runs/wpr_01M4SXHWJKKKH7JZZMKQTPPBP6/shot18/greybox_a5/job.json $O/routeA2_src --style modern_anime --cam closeup --secondary --range 25:97 --passes > $O/routeA2_src.log 2>&1
echo "- [x] routeA2_src rendered $(date +%T)" >> $O/STATE.md
