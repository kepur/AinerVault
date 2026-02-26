from __future__ import annotations

from typing import Any, Generator

from fastapi import Depends
from sqlalchemy.orm import Session

from ainern2d_shared.config.setting import settings
from ainern2d_shared.db.session import SessionLocal
from ainern2d_shared.db.repositories.pipeline import (
	JobRepository,
	RenderRunRepository,
	WorkflowEventRepository,
)
from ainern2d_shared.queue.rabbitmq import RabbitMQPublisher
from ainern2d_shared.telemetry.logging import get_logger


_logger = get_logger("studio-api")


def get_db() -> Generator[Session, None, None]:
	db = SessionLocal()
	try:
		yield db
	finally:
		db.close()


def get_run_repo(db: Session = Depends(get_db)) -> RenderRunRepository:
	return RenderRunRepository(db)


def get_job_repo(db: Session = Depends(get_db)) -> JobRepository:
	return JobRepository(db)


def get_event_repo(db: Session = Depends(get_db)) -> WorkflowEventRepository:
	return WorkflowEventRepository(db)


def publish(topic: str, payload: dict[str, Any]) -> None:
	try:
		publisher = RabbitMQPublisher(settings.rabbitmq_url)
		publisher.publish(topic=topic, message=payload)
		publisher.close()
	except Exception as exc:
		_logger.warning("publish fallback topic={} reason={}", topic, str(exc))


def get_db_session() -> Session:
	"""Non-generator DB session for background consumers (not FastAPI Depends)."""
	return SessionLocal()

