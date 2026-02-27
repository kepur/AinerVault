"""Worker result callback consumer – listens to WORKER_CALLBACK topic."""

from __future__ import annotations

from ainern2d_shared.config.setting import settings
from ainern2d_shared.queue.rabbitmq import RabbitMQConsumer, RabbitMQPublisher
from ainern2d_shared.queue.topics import SYSTEM_TOPICS
from ainern2d_shared.schemas.worker import WorkerResult
from ainern2d_shared.telemetry.logging import get_logger

from app.dispatcher.hub import DispatchHub

logger = get_logger(__name__)

_RETRY_TOPIC = "worker.callback.retry"


class ResultConsumer:
    """Consumes WORKER_CALLBACK events and delegates to DispatchHub."""

    def __init__(self, hub: DispatchHub) -> None:
        self._hub = hub

    def start(self) -> None:
        """Block and consume from ``SYSTEM_TOPICS.WORKER_CALLBACK``."""
        consumer = RabbitMQConsumer(settings.rabbitmq_url)
        logger.info("result consumer starting on %s", SYSTEM_TOPICS.WORKER_DETAIL)
        consumer.consume(SYSTEM_TOPICS.WORKER_DETAIL, self._handle)

    def _handle(self, payload: dict) -> None:
        try:
            result = WorkerResult.model_validate(payload)

            import asyncio
            asyncio.run(self._hub.handle_callback(result))

        except Exception:
            logger.exception("result consumer error – republishing for retry")
            self._republish(payload)

    def _republish(self, payload: dict) -> None:
        try:
            publisher = RabbitMQPublisher(settings.rabbitmq_url)
            publisher.publish(_RETRY_TOPIC, payload)
            publisher.close()
        except Exception:
            logger.exception("failed to republish to retry topic")
