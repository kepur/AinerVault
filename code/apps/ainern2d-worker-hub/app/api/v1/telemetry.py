from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.dispatch import DISPATCH_JOBS

router = APIRouter(prefix="/internal", tags=["worker-hub"])


@router.get("/telemetry/queue")
def queue_metrics() -> dict[str, int]:
	queued = sum(1 for item in DISPATCH_JOBS.values() if item.get("status") == "enqueued")
	running = sum(1 for item in DISPATCH_JOBS.values() if item.get("status") == "running")
	succeeded = sum(1 for item in DISPATCH_JOBS.values() if item.get("status") == "succeeded")
	failed = sum(1 for item in DISPATCH_JOBS.values() if item.get("status") == "failed")
	return {
		"queued": queued,
		"running": running,
		"succeeded": succeeded,
		"failed": failed,
		"total": len(DISPATCH_JOBS),
	}

