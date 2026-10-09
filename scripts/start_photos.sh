#!/bin/zsh
# Vision Toolbox 照片库（8765）：没在跑就起，然后打开图库页。
VT="/Users/mac/AinerWorkFlow/AinerVaultMlx/Vision_Toolbox"
LOG="/Users/mac/AinerWorkFlow/AinerHub_IDEA/var/logs"; mkdir -p "$LOG"
if ! lsof -tiTCP:8765 -sTCP:LISTEN >/dev/null 2>&1; then
  cd "$VT"; PY="../AinerVault/.venv/bin/python"; [ -x "$PY" ] || PY=".venv/bin/python"
  nohup "$PY" run_web.py >> "$LOG/photos.log" 2>&1 &!
  for i in $(seq 1 60); do lsof -tiTCP:8765 -sTCP:LISTEN >/dev/null 2>&1 && break; sleep 1; done
fi
lsof -tiTCP:8765 -sTCP:LISTEN >/dev/null 2>&1 && echo "照片库 8765 ✓" || echo "照片库没起来，看 $LOG/photos.log"
open "http://localhost:8765/#/library"
