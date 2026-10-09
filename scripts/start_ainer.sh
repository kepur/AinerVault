#!/bin/zsh
# AinerHub 一键启动：数据库(Docker) → Core 后台 → 模型网关 + ComfyUI → Studio 前端，最后打开浏览器。
# 已经在跑的服务跳过；日志在 var/logs/。关掉这个终端窗口不会停服务，停用「停止 Ainer」。
export PATH="/usr/local/bin:/opt/homebrew/bin:$PATH"
ROOT="/Users/mac/AinerWorkFlow/AinerHub_IDEA"
GW="/Users/mac/Code_Start/ml-stable-diffusion"
LOG="$ROOT/var/logs"; mkdir -p "$LOG"
up() { lsof -tiTCP:$1 -sTCP:LISTEN >/dev/null 2>&1; }
wait_port() { for i in $(seq 1 ${2:-60}); do up $1 && return 0; sleep 1; done; return 1; }
say() { echo "[$(date +%H:%M:%S)] $*"; }

# 1. Docker + 数据库
if ! docker info >/dev/null 2>&1; then
  say "启动 Docker Desktop…"; open -a Docker
  for i in $(seq 1 90); do docker info >/dev/null 2>&1 && break; sleep 2; done
fi
docker start ainer-dev-postgres-1 >/dev/null 2>&1
for i in $(seq 1 30); do docker exec ainer-dev-postgres-1 pg_isready -U ainer >/dev/null 2>&1 && break; sleep 1; done
say "数据库 5432 ✓"
# Redis：本机装的 redis-server 占着 6379 就直接用，否则起 Docker 那个
up 6379 || docker start ainer-dev-redis-1 >/dev/null 2>&1
say "Redis 6379 ✓"

# 2. Core 后台
if up 8100; then say "Core 8100 已在运行"; else
  cd "$ROOT/code/apps/ainer-core"
  CORE_DATABASE_URL="postgresql+psycopg2://ainer:ainer_dev_2024@localhost:5432/ainer_dev" \
    nohup "$ROOT/.venv/bin/python" -m uvicorn app.main:app --port 8100 --host 127.0.0.1 >> "$LOG/core.log" 2>&1 &!
  wait_port 8100 60 && say "Core 8100 ✓" || say "Core 没起来，看 $LOG/core.log"
fi

# 3. 模型网关 + ComfyUI
if up 7999; then say "模型网关 7999 已在运行"; else
  cd "$GW" && nohup python3 ai-studio/server.py >> "$LOG/gateway.log" 2>&1 &!
  wait_port 7999 30 && say "模型网关 7999 ✓" || say "网关没起来，看 $LOG/gateway.log"
fi
if ! curl -s -m 5 localhost:7999/cap/v1/health | grep -q '"comfyui-local", "ok": true'; then
  say "启动 ComfyUI…"
  curl -s -X POST localhost:7999/api/service/start -H 'content-type: application/json' -d '{"name":"comfyui"}' >/dev/null
  for i in $(seq 1 40); do curl -s -m 5 localhost:7999/cap/v1/health | grep -q '"comfyui-local", "ok": true' && break; sleep 3; done
fi
curl -s -m 5 localhost:7999/cap/v1/health | grep -q '"comfyui-local", "ok": true' && say "ComfyUI ✓" || say "ComfyUI 还没就绪（出图会排队等它）"

# 4. Studio 前端
if up 5174; then say "Studio 5174 已在运行"; else
  cd "$ROOT/code/apps/ainer-studio" && nohup npm run dev >> "$LOG/studio.log" 2>&1 &!
  wait_port 5174 60 && say "Studio 5174 ✓" || say "Studio 没起来，看 $LOG/studio.log"
fi

open "http://localhost:5174"
say "全部就绪：Studio http://localhost:5174 ｜ 后台 http://localhost:8100/admin"
