from __future__ import annotations

from fastapi import FastAPI

from app.api.v1.compose import router as compose_router

app = FastAPI(title="ainern2d-composer", version="0.1.0")
app.include_router(compose_router)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
