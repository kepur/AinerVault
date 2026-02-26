from __future__ import annotations

import os
import threading

from fastapi import FastAPI

from app.api.v1.callbacks import router as callback_router
from app.api.v1.dispatch import consume_dispatch_topic
from app.api.v1.dispatch import router as dispatch_router
from app.api.v1.telemetry import router as telemetry_router

app = FastAPI(title="ainern2d-worker-hub", version="0.1.0")
app.include_router(dispatch_router)
app.include_router(callback_router)
app.include_router(telemetry_router)


@app.on_event("startup")
def startup_consumers() -> None:
	if os.getenv("AINER_ENABLE_RMQ_CONSUMERS", "1") != "1":
		return

	thread = threading.Thread(target=consume_dispatch_topic, daemon=True)
	thread.start()


@app.get("/healthz")
def healthz() -> dict[str, str]:
	return {"status": "ok"}

