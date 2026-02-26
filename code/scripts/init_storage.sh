#!/usr/bin/env bash
# ─────────────────────────────────────────
# 初始化 MinIO 对象存储 Bucket
# ─────────────────────────────────────────
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# 加载环境变量
if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a; source "$PROJECT_ROOT/.env"; set +a
fi

S3_ENDPOINT="${S3_ENDPOINT:-http://localhost:9000}"
S3_ACCESS_KEY="${S3_ACCESS_KEY:-ainer_minio}"
S3_SECRET_KEY="${S3_SECRET_KEY:-ainer_minio_2024}"
S3_BUCKET="${S3_BUCKET:-ainer-assets}"

echo "🪣 配置 MinIO 客户端..."
docker compose exec minio mc alias set local "$S3_ENDPOINT" "$S3_ACCESS_KEY" "$S3_SECRET_KEY" 2>/dev/null || \
    mc alias set local "$S3_ENDPOINT" "$S3_ACCESS_KEY" "$S3_SECRET_KEY"

echo "📁 创建 Bucket: $S3_BUCKET"
mc mb "local/$S3_BUCKET" --ignore-existing

echo "✅ 对象存储初始化完成"
