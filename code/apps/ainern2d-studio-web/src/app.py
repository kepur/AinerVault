"""
Ainer Studio Web — 前端静态文件服务 (开发用)
生产环境由 Nginx 直接托管前端构建产物。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="ainern2d-studio-web", version="0.1.0")

STATIC_DIR = Path(__file__).resolve().parents[1] / "dist"
if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "studio-web"}
