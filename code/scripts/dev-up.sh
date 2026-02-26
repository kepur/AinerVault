#!/usr/bin/env bash
# ─────────────────────────────────────────
# 启动 Ainer 本地开发环境
# ─────────────────────────────────────────
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

# 确保 .env 存在
if [ ! -f .env ]; then
    echo "⚠️  .env 不存在，从 .env.example 复制..."
    cp .env.example .env
fi

echo "🚀 启动基础设施 (postgres, rabbitmq, redis, minio)..."
docker compose up -d postgres rabbitmq redis minio

echo "⏳ 等待基础设施就绪..."
docker compose exec postgres pg_isready -U "${POSTGRES_USER:-ainer}" --timeout=30 || true
sleep 3

echo "📦 运行数据库迁移..."
bash "$SCRIPT_DIR/migrate.sh"

echo "🪣 初始化对象存储..."
bash "$SCRIPT_DIR/init_storage.sh"

echo "🔧 启动应用服务..."
docker compose up -d studio-api worker-hub composer nginx

echo "✅ 开发环境已启动"
echo "   Studio API:    http://localhost:${STUDIO_API_PORT:-8000}/docs"
echo "   Worker Hub:    http://localhost:${WORKER_HUB_PORT:-8010}/docs"
echo "   Composer:      http://localhost:${COMPOSER_PORT:-8020}/docs"
echo "   RabbitMQ UI:   http://localhost:15672"
echo "   MinIO Console: http://localhost:9001"
