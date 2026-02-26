from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ainern2d_shared.config.setting import settings
from ainern2d_shared.queue.rabbitmq import RabbitMQPublisher
from ainern2d_shared.telemetry.logging import get_logger


@dataclass
class InMemoryStore:
	runs: dict[str, dict[str, Any]] = field(default_factory=dict)
	events: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


_logger = get_logger("studio-api")
_store = InMemoryStore()


def get_store() -> InMemoryStore:
	return _store


def publish(topic: str, payload: dict[str, Any]) -> None:
	try:
		publisher = RabbitMQPublisher(settings.rabbitmq_url)
		publisher.publish(topic=topic, message=payload)
		publisher.close()
	except Exception as exc:
		_logger.warning("publish fallback topic={} reason={}", topic, str(exc))

