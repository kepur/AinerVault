from __future__ import annotations

from enum import Enum


class Environment(str, Enum):
	local = "local"
	dev = "dev"
	staging = "staging"
	prod = "prod"


class LogLevel(str, Enum):
	debug = "DEBUG"
	info = "INFO"
	warning = "WARNING"
	error = "ERROR"


class QueueBackend(str, Enum):
	rabbitmq = "rabbitmq"
	redis = "redis"


class StorageBackend(str, Enum):
	s3 = "s3"
	minio = "minio"

