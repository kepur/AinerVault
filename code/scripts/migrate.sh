#!/usr/bin/env bash
# ─────────────────────────────────────────
# 执行 Alembic 数据库迁移
# ─────────────────────────────────────────
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
APPS_DIR="$PROJECT_ROOT/apps"

cd "$APPS_DIR"

# 加载环境变量
if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a; source "$PROJECT_ROOT/.env"; set +a
fi

# 本地运行时将 Docker 内部主机名替换为 localhost
export DATABASE_URL="${DATABASE_URL//\@postgres:/@localhost:}"

# 优先使用项目虚拟环境中的 python
VENV_PYTHON="$PROJECT_ROOT/../.venv/bin/python"
if [ -f "$VENV_PYTHON" ]; then
    PYTHON="$VENV_PYTHON"
else
    PYTHON="$(command -v python3 || command -v python)"
fi

echo "📦 执行数据库迁移 (Alembic upgrade head)..."
"$PYTHON" -m alembic upgrade head

echo "✅ 数据库迁移完成"
echo "   当前版本:"
"$PYTHON" -m alembic current
