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

    # **默认不许调付费模型。**
    #
    # 这一条是拿真金白银换来的：路由表里 image.image_to_image 的首选是
    # qwen-image-edit-max，看着和别的百炼模型没两样，一天跑下来 ¥31.5；
    # video.image_to_video 的 wan2.7-i2v 同一天 ¥48。
    # 两者都不在免费额度清单里，而系统里没有任何一处会因此拦一下 ——
    # 每一步都成功，账单第二天才看得到。
    #
    # 关掉之后，标了 billing=paid 的路由一律不发请求，直接按额度耗尽处理，
    # 于是自动换到下一条免费路由；一条免费的都没有就明确报错，
    # 让人自己决定要不要花这笔钱。未标 billing 的按付费处置 ——
    # **不确定就当它要钱**，这个方向上猜错的代价是不对称的。
    allow_paid_models: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
