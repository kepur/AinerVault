from __future__ import annotations

import os
import threading

from fastapi import FastAPI

from ainern2d_shared.queue.topics import SYSTEM_TOPICS

from app.api.v1.assets import router as assets_router
from app.api.v1.auth import router as auth_router
from app.api.v1.observer import router as observer_router
from app.api.v1.orchestrator import consume_orchestrator_topic
from app.api.v1.orchestrator import router as orchestrator_router
from app.api.v1.preview import router as preview_router
from app.api.v1.projects import router as projects_router
from app.api.v1.regenerate import router as regenerate_router
from app.api.v1.tasks import router as task_router
from app.api.v1.timesline import router as timeline_router

app = FastAPI(title="ainern2d-studio-api", version="0.1.0")
app.include_router(auth_router)
app.include_router(task_router)
app.include_router(orchestrator_router)
app.include_router(observer_router)
app.include_router(projects_router)
app.include_router(assets_router)
app.include_router(timeline_router)
app.include_router(regenerate_router)
app.include_router(preview_router)


@app.on_event("startup")
def startup_consumers() -> None:
	if os.getenv("AINER_ENABLE_RMQ_CONSUMERS", "1") != "1":
		return

	for topic in (
		SYSTEM_TOPICS.TASK_SUBMITTED,
		SYSTEM_TOPICS.JOB_STATUS,
		SYSTEM_TOPICS.COMPOSE_STATUS,
	):
		thread = threading.Thread(target=consume_orchestrator_topic, args=(topic,), daemon=True)
		thread.start()


@app.get("/healthz")
def healthz() -> dict[str, str]:
	return {"status": "ok"}
