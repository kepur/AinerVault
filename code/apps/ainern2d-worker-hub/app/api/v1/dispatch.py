from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ainern2d_shared.config.setting import settings
from ainern2d_shared.queue.rabbitmq import RabbitMQConsumer, RabbitMQPublisher
from ainern2d_shared.queue.topics import SYSTEM_TOPICS
from ainern2d_shared.schemas.events import EventEnvelope
from ainern2d_shared.telemetry.logging import get_logger

router = APIRouter(prefix="/internal", tags=["worker-hub"])

DISPATCH_JOBS: dict[str, dict[str, object]] = {}
_logger = get_logger("worker-hub")


class DispatchRequest(BaseModel):
	tenant_id: str
	project_id: str
	trace_id: str
	correlation_id: str
	idempotency_key: str
	run_id: str
	job_id: str
	worker_type: str
	payload: dict[str, object] = Field(default_factory=dict)
	timeout_ms: int = 60000
	fallback_chain: list[str] = Field(default_factory=list)


class DispatchResponse(BaseModel):
	job_id: str
	status: str


def _publish_status(event: EventEnvelope) -> None:
	try:
		publisher = RabbitMQPublisher(settings.rabbitmq_url)
		publisher.publish(SYSTEM_TOPICS.JOB_STATUS, event.model_dump(mode="json"))
		publisher.close()
	except Exception as exc:
		_logger.warning("publish job.status failed reason={}", str(exc))


def handle_job_dispatch(payload: dict) -> None:
	event = EventEnvelope.model_validate(payload)
	if event.event_type != "job.created":
		return

	job_id = event.job_id or f"job_{uuid4().hex}"
	now = datetime.now(timezone.utc)
	worker_type = str(event.payload.get("worker_type", "worker-video"))

	DISPATCH_JOBS[job_id] = {
		"job_id": job_id,
		"run_id": event.run_id,
		"worker_type": worker_type,
		"tenant_id": event.tenant_id,
		"project_id": event.project_id,
		"trace_id": event.trace_id,
		"correlation_id": event.correlation_id,
		"idempotency_key": event.idempotency_key,
		"status": "running",
		"updated_at": now,
	}

	claimed_event = EventEnvelope(
		event_type="job.claimed",
		producer="worker-hub",
		occurred_at=now,
		tenant_id=event.tenant_id,
		project_id=event.project_id,
		idempotency_key=event.idempotency_key,
		run_id=event.run_id,
		job_id=job_id,
		trace_id=event.trace_id,
		correlation_id=event.correlation_id,
		payload={"worker_type": worker_type, "queue_status": "claimed"},
	)
	_publish_status(claimed_event)

	succeeded_event = EventEnvelope(
		event_type="job.succeeded",
		producer="worker-hub",
		occurred_at=datetime.now(timezone.utc),
		tenant_id=event.tenant_id,
		project_id=event.project_id,
		idempotency_key=event.idempotency_key,
		run_id=event.run_id,
		job_id=job_id,
		trace_id=event.trace_id,
		correlation_id=event.correlation_id,
		payload={
			"worker_type": worker_type,
			"artifact_uri": f"s3://ainer-artifacts/{event.run_id}/{job_id}.mp4",
		},
	)
	_publish_status(succeeded_event)
	DISPATCH_JOBS[job_id]["status"] = "succeeded"


def consume_dispatch_topic() -> None:
	consumer = RabbitMQConsumer(settings.rabbitmq_url)
	consumer.consume(SYSTEM_TOPICS.JOB_DISPATCH, handle_job_dispatch)


@router.post("/dispatch", response_model=DispatchResponse, status_code=202)
def dispatch(body: DispatchRequest) -> DispatchResponse:
	now = datetime.now(timezone.utc)
	DISPATCH_JOBS[body.job_id] = {
		"job_id": body.job_id,
		"run_id": body.run_id,
		"worker_type": body.worker_type,
		"tenant_id": body.tenant_id,
		"project_id": body.project_id,
		"trace_id": body.trace_id,
		"correlation_id": body.correlation_id,
		"idempotency_key": body.idempotency_key,
		"status": "enqueued",
		"updated_at": now,
	}

	claimed_event = EventEnvelope(
		event_type="job.claimed",
		producer="worker-hub",
		occurred_at=now,
		tenant_id=body.tenant_id,
		project_id=body.project_id,
		idempotency_key=body.idempotency_key,
		run_id=body.run_id,
		job_id=body.job_id,
		trace_id=body.trace_id,
		correlation_id=body.correlation_id,
		payload={"worker_type": body.worker_type, "queue_status": "claimed"},
	)
	DISPATCH_JOBS[body.job_id]["claimed_event"] = claimed_event.model_dump(mode="json")
	return DispatchResponse(job_id=body.job_id, status="enqueued")

