#!/usr/bin/env bash
# ─────────────────────────────────────────
# 执行 Alembic 数据库迁移
# ─────────────────────────────────────────
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
SHARED_DIR="$PROJECT_ROOT/shared"

cd "$SHARED_DIR"

# 加载环境变量
if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a; source "$PROJECT_ROOT/.env"; set +a
fi

echo "📦 执行数据库迁移 (Alembic upgrade head)..."
python -m alembic upgrade head

echo "✅ 数据库迁移完成"
echo "   当前版本:"
python -m alembic current
