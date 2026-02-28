from __future__ import annotations

import os
import threading

from fastapi import FastAPI

from app.api.v1.compose import consume_compose_dispatch
from app.api.v1.compose import router as compose_router
from app.api.v1.media import router as media_router

app = FastAPI(title="ainern2d-composer", version="0.1.0")
app.include_router(compose_router)
app.include_router(media_router)


@app.on_event("startup")
def startup_consumers() -> None:
    if os.getenv("AINER_ENABLE_RMQ_CONSUMERS", "1") != "1":
        return

    thread = threading.Thread(target=consume_compose_dispatch, daemon=True)
    thread.start()


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
