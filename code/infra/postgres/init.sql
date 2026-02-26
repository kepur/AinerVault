-- ─────────────────────────────────────────────
-- Ainer PostgreSQL 初始化脚本
-- 由 docker-entrypoint-initdb.d 自动执行
-- ─────────────────────────────────────────────

-- 启用 pgvector 扩展 (向量检索)
CREATE EXTENSION IF NOT EXISTS vector;

-- 启用 uuid-ossp (UUID 生成)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 启用 pg_trgm (模糊搜索)
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 创建应用 Schema (可选，默认 public)
-- CREATE SCHEMA IF NOT EXISTS ainer;

-- 设置默认时区为 UTC
ALTER DATABASE ainer_dev SET timezone TO 'UTC';
