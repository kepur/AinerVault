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
		)


settings = Settings.from_env()

