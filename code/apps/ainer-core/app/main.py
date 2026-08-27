"""AinerN2D Core —— 小说 → 多语言剧本 → 视频素材清单。

它不生成像素、不生成声波、不合成视频；它生成结构与指令，
通过 Capability API 交给能力中间层执行。
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.requests import Request

from app.capability.errors import CapabilityError
from app.config import settings
from app.db import ensure_schema

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
log = logging.getLogger("ainer-core")


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_schema()
    log.info("ainer-core 启动 schema=%s port=%s", settings.db_schema, settings.port)
    yield


app = FastAPI(
    title="AinerN2D Core",
    version="2.0.0",
    description="小说 → 多语言剧本 → 视频素材清单。生成能力全部外化为 Capability API。",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(CapabilityError)
async def capability_error_handler(_: Request, exc: CapabilityError) -> JSONResponse:
    status = 502 if exc.retryable else 400
    return JSONResponse(status_code=status, content=exc.to_json())


from app.api.v2 import (  # noqa: E402
    gen_tasks, library, script, settings_api, worldview,
)

app.include_router(library.router)
app.include_router(script.router)
app.include_router(worldview.router)
app.include_router(gen_tasks.router)
app.include_router(settings_api.router)


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"ok": True, "service": "ainer-core", "version": "2.0.0"}
