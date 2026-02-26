#!/usr/bin/env bash
# ─────────────────────────────────────────
# 停止 Ainer 本地开发环境
# ─────────────────────────────────────────
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

echo "🛑 停止所有服务..."
docker compose down

# 可选：加 -v 清除数据卷
if [ "${1:-}" = "--clean" ]; then
    echo "🗑  清除数据卷..."
    docker compose down -v
    echo "✅ 已清除所有数据"
else
    echo "✅ 服务已停止 (数据保留)。加 --clean 可清除数据卷。"
fi
