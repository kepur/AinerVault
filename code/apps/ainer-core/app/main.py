"""AinerN2D Core —— 小说 → 多语言剧本 → 视频素材清单。

它不生成像素、不生成声波、不合成视频；它生成结构与指令，
通过 Capability API 交给能力中间层执行。
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
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
    import asyncio

    from app.workers.poller import run_forever

    ensure_schema()
    log.info("ainer-core 启动 schema=%s port=%s", settings.db_schema, settings.port)
    poller = None
    if settings.poll_loop_sec > 0:
        poller = asyncio.create_task(run_forever(settings.poll_loop_sec))
        log.info("后台轮询已启动，每 %ds 一轮", settings.poll_loop_sec)
    from app.pipelines import canvas_run
    if (n := canvas_run.resume()):
        log.info("画布一键出片：%d 个工作流没跑完，接着跑", n)
    try:
        yield
    finally:
        if poller is not None:
            poller.cancel()


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
    asset_pack, audio, blocking, canvas, canvas_gen, canvas_run, console, quick_film, culture, gen_tasks, handoff, library,
    characters, char_sheet, director, presets, production, prose, scene3d, script, settings_api, shared_stages, shots, stage, studio, translation, worldview,
    world,
    world_pipeline,
)

app.include_router(console.router)
app.include_router(blocking.router)
app.include_router(studio.router)
app.include_router(canvas.router)
app.include_router(canvas_gen.router)
app.include_router(canvas_run.router)
app.include_router(quick_film.router)
app.include_router(stage.router)
app.include_router(scene3d.router)
app.include_router(director.router)
app.include_router(presets.router)
app.include_router(characters.router)
app.include_router(production.router)
app.include_router(shared_stages.router)
app.include_router(world.router)
app.include_router(world_pipeline.router)
app.include_router(char_sheet.router)
app.include_router(library.router)
app.include_router(script.router)
app.include_router(worldview.router)
app.include_router(translation.router)
app.include_router(prose.router)
app.include_router(culture.router)
app.include_router(asset_pack.router)
app.include_router(shots.router)
app.include_router(audio.router)
app.include_router(handoff.router)
app.include_router(gen_tasks.router)
app.include_router(settings_api.router)


# ── 后台 ──────────────────────────────────────────────────────────────────────
_STATIC = Path(__file__).parent / "static"


@app.get("/media/{name}", include_in_schema=False)
def media_file(name: str) -> FileResponse:
    """同步方言落盘的产物。文件名是内容的 sha256，不接受路径分隔符。"""
    from fastapi import HTTPException

    from app.capability.mediastore import media_root

    if "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(status_code=400, detail="bad name")
    path = media_root() / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(path)


#: 画布前端（code/apps/ainer-studio）构建产物。和 /admin 一样读盘即生效，
#: 重新 npm run build 之后刷新页面就是新版本，不用重启服务
_STUDIO = Path(__file__).resolve().parents[2] / "ainer-studio" / "dist"


@app.get("/studio", include_in_schema=False)
@app.get("/studio/{path:path}", include_in_schema=False)
def studio_page(path: str = "") -> FileResponse:
    if path:
        target = (_STUDIO / path).resolve()
        if target.is_file() and _STUDIO.resolve() in target.parents:
            return FileResponse(target)
    index = _STUDIO / "index.html"
    if not index.exists():
        raise HTTPException(
            status_code=404,
            detail="画布前端还没构建：cd code/apps/ainer-studio && npm install && npm run build")
    return FileResponse(index)


@app.get("/admin", include_in_schema=False)
def admin_page() -> FileResponse:
    """单文件后台。零构建、零依赖，改完刷新即生效。"""
    return FileResponse(_STATIC / "admin.html")


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("/admin")


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"ok": True, "service": "ainer-core", "version": "2.0.0"}
