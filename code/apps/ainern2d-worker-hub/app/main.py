from __future__ import annotations

from fastapi import FastAPI

from app.api.v1.callbacks import router as callback_router
from app.api.v1.dispatch import router as dispatch_router
from app.api.v1.telemetry import router as telemetry_router

app = FastAPI(title="ainern2d-worker-hub", version="0.1.0")
app.include_router(dispatch_router)
app.include_router(callback_router)
app.include_router(telemetry_router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
	return {"status": "ok"}

