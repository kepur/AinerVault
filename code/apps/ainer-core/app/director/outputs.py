"""产物管理：任务目录里的文件 → director_outputs；视频和图片另存进媒体库成资产（稳定的 /media 地址）。"""
from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.capability.mediastore import store_bytes
from app.director import config
from app.ids import new_id
from app.models import Asset, AssetKind, AssetSource, DirectorJob, DirectorOutput

#: 进媒体库的：视频模型、前端播放器要拿 URL 的那些
MEDIA_KINDS = {"preview", "clay", "depth", "pose", "canny", "first_frame", "final", "styled_first_frame"}


def register(db: Session, job: DirectorJob, files: dict[str, str], *, novel_id: str | None = None,
             meta: dict[str, Any] | None = None) -> list[DirectorOutput]:
    """files：kind → 任务目录里的相对路径（或绝对路径）。同一 kind 重登记会覆盖旧的。"""
    root = config.job_dir(job.id)
    old = {o.kind: o for o in db.execute(select(DirectorOutput).where(DirectorOutput.job_id == job.id)).scalars()}
    rows = []
    for kind, rel in files.items():
        path = Path(rel) if Path(rel).is_absolute() else root / rel
        if not path.exists():
            continue
        row = old.get(kind) or DirectorOutput(id=new_id("dout"), job_id=job.id, kind=kind, path="")
        row.path = str(path.relative_to(root)) if path.is_relative_to(root) else str(path)
        row.bytes = path.stat().st_size
        row.meta_json = {**(meta or {}), "file": path.name}
        if kind in MEDIA_KINDS:
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            item = store_bytes(path.read_bytes(), mime=mime)
            asset = Asset(id=new_id("as"), kind=AssetKind.video if str(item["mime"]).startswith("video/") else AssetKind.image,
                          url=str(item["url"]), sha256=str(item["sha256"]), mime=str(item["mime"]), bytes=int(item["bytes"]),
                          source=AssetSource.generated, novel_id=novel_id,
                          meta_json={"director_job_id": job.id, "kind": kind, "scene_id": job.scene_id, **(meta or {})})
            db.add(asset)
            row.asset_id, row.url = asset.id, asset.url
        if kind not in old:
            db.add(row)
        rows.append(row)
    db.flush()
    return rows


def outputs_of(db: Session, job_id: str) -> list[dict[str, Any]]:
    rows = db.execute(select(DirectorOutput).where(DirectorOutput.job_id == job_id).order_by(DirectorOutput.created_at)).scalars()
    return [{"kind": o.kind, "path": o.path, "url": o.url or f"/api/v2/director/jobs/{job_id}/files/{o.path}",
             "asset_id": o.asset_id, "bytes": o.bytes} for o in rows]


def safe_file(job_id: str, rel: str) -> Path:
    """任务目录里的文件（挡住 ../ 穿越）。"""
    root = config.job_dir(job_id).resolve()
    p = (root / rel).resolve()
    if not p.is_relative_to(root) or not p.is_file():
        raise FileNotFoundError(rel)
    return p
