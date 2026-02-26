from __future__ import annotations

import os

from pydantic import BaseModel, Field


class Settings(BaseModel):
    app_name: str = Field(default="AinerHub")
    environment: str = Field(default="local")

    database_url: str = Field(default="postgresql+psycopg2://postgres:postgres@localhost:5432/ainervault")
    redis_url: str = Field(default="redis://localhost:6379/0")
    rabbitmq_url: str = Field(default="amqp://guest:guest@localhost:5672/")

    storage_backend: str = Field(default="minio")
    s3_endpoint: str = Field(default="http://localhost:9000")
    s3_access_key: str = Field(default="minioadmin")
    s3_secret_key: str = Field(default="minioadmin")
    s3_bucket: str = Field(default="ainer-artifacts")

    log_level: str = Field(default="INFO")

    # ── LLM Provider Keys ─────────────────────────────────────────────
    openai_api_key: str = Field(default="")
    openai_base_url: str = Field(default="https://api.openai.com/v1")

    deepseek_api_key: str = Field(default="")
    deepseek_base_url: str = Field(default="https://api.deepseek.com/v1")

    qwen_api_key: str = Field(default="")         # DashScope API key
    qwen_base_url: str = Field(default="https://dashscope.aliyuncs.com/compatible-mode/v1")

    volcengine_api_key: str = Field(default="")   # Volcengine / Huosan ARK key
    volcengine_base_url: str = Field(default="https://ark.cn-beijing.volces.com/api/v3")

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            app_name=os.getenv("AINER_APP_NAME", "AinerHub"),
            environment=os.getenv("AINER_ENV", "local"),
            database_url=os.getenv("DATABASE_URL", "postgresql+psycopg2://postgres:postgres@localhost:5432/ainervault"),
            redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            rabbitmq_url=os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/"),
            storage_backend=os.getenv("STORAGE_BACKEND", "minio"),
            s3_endpoint=os.getenv("S3_ENDPOINT", "http://localhost:9000"),
            s3_access_key=os.getenv("S3_ACCESS_KEY", "minioadmin"),
            s3_secret_key=os.getenv("S3_SECRET_KEY", "minioadmin"),
            s3_bucket=os.getenv("S3_BUCKET", "ainer-artifacts"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
            qwen_api_key=os.getenv("DASHSCOPE_API_KEY", ""),
            qwen_base_url=os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            volcengine_api_key=os.getenv("ARK_API_KEY", ""),
            volcengine_base_url=os.getenv("VOLCENGINE_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
        )


settings = Settings.from_env()
