#!/bin/zsh
# AinerHub 一键停止：Studio、Core、ComfyUI、模型网关。数据库容器留着（停它用 docker stop ainer-dev-postgres-1）。
export PATH="/usr/local/bin:/opt/homebrew/bin:$PATH"
stop() { local p=$(lsof -tiTCP:$1 -sTCP:LISTEN 2>/dev/null); [ -n "$p" ] && kill $p && echo "已停 $2 ($1)" || echo "$2 ($1) 本来就没在跑"; }
stop 5174 Studio
stop 8100 Core
curl -s -m 5 -X POST localhost:7999/api/service/stop -H 'content-type: application/json' -d '{"name":"comfyui"}' >/dev/null && echo "已停 ComfyUI"
stop 7999 模型网关
