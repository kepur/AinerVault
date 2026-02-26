from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from ainern2d_shared.config.setting import settings
from ainern2d_shared.queue.rabbitmq import RabbitMQPublisher
from ainern2d_shared.queue.topics import SYSTEM_TOPICS
from ainern2d_shared.schemas.events import EventEnvelope
from ainern2d_shared.schemas.worker import WorkerResult
from ainern2d_shared.telemetry.logging import get_logger

from app.api.v1.dispatch import DISPATCH_JOBS

router = APIRouter(prefix="/internal", tags=["worker-hub"])
_logger = get_logger("worker-hub-callback")


@router.post("/callbacks/result", status_code=202)
def worker_result_callback(result: WorkerResult) -> dict[str, object]:
	now = datetime.now(timezone.utc)
	record = DISPATCH_JOBS.get(result.job_id, {})
	status = result.status.lower()

	event_type = "job.succeeded" if status == "succeeded" else "job.failed"
	payload: dict[str, object] = {
		"worker_type": result.worker_type,
		"artifact_uri": result.artifact_uri,
		"metrics": result.metrics,
	}

	if event_type == "job.failed":
		payload.update(
			{
				"error_code": result.error_code or "WORKER-EXEC-002",
				"error_message": result.error_message or "worker execution failed",
				"retryable": bool(result.retryable),
			}
		)

	event = EventEnvelope(
		event_type=event_type,
		producer="worker-hub",
		occurred_at=now,
		tenant_id=str(record.get("tenant_id", "t_unknown")),
		project_id=str(record.get("project_id", "p_unknown")),
		idempotency_key=str(record.get("idempotency_key", f"idem_{result.job_id}")),
		run_id=result.run_id,
		job_id=result.job_id,
		trace_id=str(record.get("trace_id", f"tr_{result.job_id}")),
		correlation_id=str(record.get("correlation_id", f"cr_{result.job_id}")),
		payload=payload,
	)

	DISPATCH_JOBS[result.job_id] = {
		**record,
		"job_id": result.job_id,
		"run_id": result.run_id,
		"worker_type": result.worker_type,
		"status": status,
		"updated_at": now,
		"result_event": event.model_dump(mode="json"),
	}
	try:
		publisher = RabbitMQPublisher(settings.rabbitmq_url)
		publisher.publish(SYSTEM_TOPICS.JOB_STATUS, event.model_dump(mode="json"))
		publisher.close()
	except Exception as exc:
		_logger.warning("publish callback job.status failed reason={}", str(exc))
	return {"status": "accepted", "event_type": event_type}

