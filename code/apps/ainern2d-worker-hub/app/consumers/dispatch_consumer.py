"""Dispatch queue consumer – listens to JOB_DISPATCH and routes to DispatchHub."""

from __future__ import annotations

from ainern2d_shared.ainer_db_models.pipeline_models import Job
from ainern2d_shared.config.setting import settings
from ainern2d_shared.db.session import SessionLocal
from ainern2d_shared.db.repositories.pipeline import JobRepository
from ainern2d_shared.queue.rabbitmq import RabbitMQConsumer, RabbitMQPublisher
from ainern2d_shared.queue.topics import SYSTEM_TOPICS
from ainern2d_shared.schemas.events import EventEnvelope
from ainern2d_shared.telemetry.logging import get_logger

from app.dispatcher.hub import DispatchHub

logger = get_logger(__name__)

_DLQ_TOPIC = "job.dispatch.dlq"


class DispatchConsumer:
    """Consumes JOB_DISPATCH events and delegates to DispatchHub."""

    def __init__(self, hub: DispatchHub) -> None:
        self._hub = hub

    def start(self) -> None:
        """Block and consume from ``SYSTEM_TOPICS.JOB_DISPATCH``."""
        consumer = RabbitMQConsumer(settings.rabbitmq_url)
        logger.info("dispatch consumer starting on %s", SYSTEM_TOPICS.JOB_DISPATCH)
        consumer.consume(SYSTEM_TOPICS.JOB_DISPATCH, self._handle)

    def _handle(self, payload: dict) -> None:
        try:
            envelope = EventEnvelope.model_validate(payload)
            job_id = envelope.job_id
            if not job_id:
                logger.warning("dispatch event missing job_id – skipped")
                return

            db = SessionLocal()
            try:
                job_repo = JobRepository(db)
                job = job_repo.get(job_id)
                if job is None:
                    logger.error("job %s not found in DB", job_id)
                    return

                import asyncio
                asyncio.get_event_loop().run_until_complete(self._hub.dispatch(job))
            finally:
                db.close()

        except Exception:
            logger.exception("dispatch consumer error – sending to DLQ")
            self._publish_dlq(payload)

    def _publish_dlq(self, payload: dict) -> None:
        try:
            publisher = RabbitMQPublisher(settings.rabbitmq_url)
            publisher.publish(_DLQ_TOPIC, payload)
            publisher.close()
        except Exception:
            logger.exception("failed to publish to DLQ")