#!/usr/bin/env bash
# 启动 Ainer 全栈本地 Docker 开发环境
# 包含: 基础设施 + 后端服务 + 前端服务
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
STUDIO_API_PORT="${STUDIO_API_PORT:-8000}"
WORKER_HUB_PORT="${WORKER_HUB_PORT:-8010}"
COMPOSER_PORT="${COMPOSER_PORT:-8020}"

wait_http_ok() {
    local url="$1"
    local name="$2"
    local max_retries="${3:-60}"
    local i=1
    while [ "$i" -le "$max_retries" ]; do
        if curl -fsS "$url" >/dev/null 2>&1; then
            return 0
        fi
        sleep 2
        i=$((i + 1))
    done
    echo "ERROR: ${name} not ready (${url})"
    return 1
}

cd "$PROJECT_ROOT"

if [ ! -f .env ]; then
    echo "[WARN] .env 不存在，从 .env.example 复制"
    cp .env.example .env
fi

set -a
source .env
set +a
STUDIO_API_PORT="${STUDIO_API_PORT:-8000}"
WORKER_HUB_PORT="${WORKER_HUB_PORT:-8010}"
COMPOSER_PORT="${COMPOSER_PORT:-8020}"

echo "[1/7] 启动基础设施 (postgres, rabbitmq, redis, minio)"
docker compose up -d postgres rabbitmq redis minio

echo "[2/7] 等待 PostgreSQL 就绪"
until docker compose exec -T postgres pg_isready -U "${POSTGRES_USER:-ainer}" >/dev/null 2>&1; do
    sleep 2
done

echo "[2/7] 等待 RabbitMQ 就绪"
until docker compose exec -T rabbitmq rabbitmq-diagnostics -q ping >/dev/null 2>&1; do
    sleep 2
done

echo "[2/7] 等待 MinIO 就绪"
until docker compose exec -T minio mc ready local >/dev/null 2>&1; do
    sleep 2
done

echo "[3/7] 构建应用镜像"
docker compose build studio-api worker-hub composer studio-web

echo "[4/7] 运行数据库迁移"
docker compose run --rm --no-deps studio-api sh -lc "cd /workspace/apps && python -m alembic -c alembic.ini stamp head"

echo "[5/7] 初始化对象存储"
bash "$SCRIPT_DIR/init_storage.sh"

echo "[6/7] 启动应用服务"
docker compose up -d studio-api worker-hub composer studio-web
# Force recreate nginx so upstream DNS points to latest container IPs.
docker compose up -d --force-recreate nginx

echo "[7/7] 执行健康检查"
wait_http_ok "http://localhost:${STUDIO_API_PORT}/healthz" "studio-api"
wait_http_ok "http://localhost:5173" "studio-web"
wait_http_ok "http://localhost:${STUDIO_API_PORT}/docs" "studio-api-docs"
wait_http_ok "http://localhost:80/nginx-health" "nginx"
wait_http_ok "http://localhost:80/api/v1/auth/me" "gateway-api"

echo "OK: 全栈开发环境已启动"
echo "Frontend:      http://localhost:5173"
echo "Studio API:    http://localhost:${STUDIO_API_PORT}"
echo "API Docs:      http://localhost:${STUDIO_API_PORT}/docs"
echo "Worker Hub:    http://localhost:${WORKER_HUB_PORT}/docs"
echo "Composer:      http://localhost:${COMPOSER_PORT}/docs"
echo "Gateway API:   http://localhost/api/v1"
echo "RabbitMQ UI:   http://localhost:15672"
echo "MinIO Console: http://localhost:9001"
