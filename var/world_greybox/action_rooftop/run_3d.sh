#!/bin/bash
cd /Users/mac/AinerWorkFlow/AinerHub_IDEA
O=var/world_greybox/action_rooftop
while screen -ls | grep -q a2rep; do sleep 15; done
while pgrep -f ltx25_infer >/dev/null; do sleep 30; done
/Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup --python code/apps/ainer-core/scripts/action_rooftop_poc.py -- $O/modern --style modern_anime --passes > $O/modern.log 2>&1
echo "- [x] action 3D modern_anime 120f + passes $(date +%T)" >> $O/STATE.md
