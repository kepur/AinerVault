"""运行配置。所有值可用环境变量覆盖，前缀 CORE_。"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CORE_", env_file=".env", extra="ignore")

    # ── 数据库 ────────────────────────────────────────────────
    # v2 的表全部建在独立 schema，与 v1 的 public 物理隔离
    database_url: str = "postgresql+psycopg2://ainer:ainer_dev_2024@localhost:15432/ainer_dev"
    db_schema: str = "core"
    db_echo: bool = False

    # ── 服务 ─────────────────────────────────────────────────
    port: int = 8100
    log_level: str = "INFO"
    cors_origins: list[str] = ["*"]

    # ── 能力中间层回调 ─────────────────────────────────────────
    # 中间层回调本服务时使用的公网地址
    public_base_url: str = "http://localhost:8100"
    callback_secret: str = "whsec_dev_change_me"

    # 能力目录缓存时长
    capabilities_cache_ttl_sec: int = 600
    # 轮询兜底：submitted_at + estimated_ms * factor 之后主动查询
    poll_fallback_factor: float = 3.0
    poll_fallback_min_sec: int = 30

    redis_url: str = "redis://localhost:16379/1"

    # ── 产物存储 ──────────────────────────────────────────────
    # 同步方言（直连供应商）返回的是字节而不是 URL，Core 得自己落盘。
    # 走中间层时用不到这一项 —— 那边把产物存好只回 URL
    media_dir: str = "var/media"

    # ── 成本闸门 ──────────────────────────────────────────────
    # 单次批量生成预估成本超过此值需前端二次确认（由 API 返回 requires_confirm）
    cost_confirm_threshold: float = 1.0


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
