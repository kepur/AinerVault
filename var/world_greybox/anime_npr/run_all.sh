#!/bin/zsh
cd /Users/mac/AinerWorkFlow/AinerHub_IDEA
B=/Applications/Blender.app/Contents/MacOS/Blender
J=var/world_greybox/runs/wpr_01M4SXHWJKKKH7JZZMKQTPPBP6/shot18/greybox_a5/job.json
O=var/world_greybox/anime_npr
S=code/apps/ainer-core/scripts/anime_npr_poc.py
for st in classic_cel modern_anime; do
  while pgrep -f ltx25_infer >/dev/null; do sleep 30; done
  $B -b --factory-startup --python $S -- $J $O/shot18_$st --style $st > $O/shot18_$st.log 2>&1
  while pgrep -f ltx25_infer >/dev/null; do sleep 30; done
  $B -b --factory-startup --python $S -- $J $O/closeup_$st --style $st --cam closeup --range 25:97 > $O/closeup_$st.log 2>&1
  for f in 1 97; do $B -b --factory-startup --python $S -- $J $O/passes_${st}_f$f --style $st --still $f --passes > /dev/null 2>&1; done
done
echo ALL_DONE
