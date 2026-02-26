#!/usr/bin/env bash
# ─────────────────────────────────────────
# 初始化 RAG 知识库种子数据
# ─────────────────────────────────────────
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# 加载环境变量
if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a; source "$PROJECT_ROOT/.env"; set +a
fi

echo "🌱 初始化 RAG 知识库种子数据..."

python - << 'EOPY'
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))

from ainern2d_shared.db.session import SessionLocal
from ainern2d_shared.ainer_db_models.rag_models import RagCollection, KbVersion
from uuid import uuid4

db = SessionLocal()
try:
    existing = db.query(RagCollection).filter_by(name="default").first()
    if existing:
        print("ℹ️  默认知识库已存在，跳过")
        sys.exit(0)

    collection = RagCollection(
        id=f"col_{uuid4().hex[:16]}",
        tenant_id="default",
        project_id="default",
        name="default",
        description="默认知识库集合",
    )
    db.add(collection)
    db.flush()

    version = KbVersion(
        id=f"kbv_{uuid4().hex[:16]}",
        tenant_id="default",
        project_id="default",
        collection_id=collection.id,
        version_name="v1.0",
        status="draft",
    )
    db.add(version)
    db.commit()
    print(f"✅ 创建默认知识库: collection={collection.id}, version={version.id}")
except Exception as e:
    db.rollback()
    print(f"❌ 种子数据初始化失败: {e}")
    sys.exit(1)
finally:
    db.close()
EOPY

echo "✅ RAG 种子数据初始化完成"
