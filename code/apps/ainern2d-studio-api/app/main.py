from __future__ import annotations

from fastapi import FastAPI

from app.api.v1.observer import router as observer_router
from app.api.v1.orchestrator import router as orchestrator_router
from app.api.v1.tasks import router as task_router

app = FastAPI(title="ainern2d-studio-api", version="0.1.0")
app.include_router(task_router)
app.include_router(orchestrator_router)
app.include_router(observer_router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
	return {"status": "ok"}

