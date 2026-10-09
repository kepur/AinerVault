"""3D-BOX 预演接口：场景项目、脚本文件、编译、手动改动、智能体对话、导出。"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.capability.mediastore import store_bytes
from app.capability.router import resolve_routes
from app.capability.schemas import Capability
from app.db import get_db
from app.ids import new_id
from app.models import Asset, AssetKind, AssetSource, SceneMessage, SceneProject
from app.scene3d import agent, service
from app.scene3d.runner import SceneRunError, catalog
from app.scene3d.templates import TEMPLATES, listing

router = APIRouter(prefix="/api/v2/scene3d", tags=["scene3d"])


def _project(db: Session, pid: str) -> SceneProject:
    p = db.get(SceneProject, pid)
    if p is None:
        raise HTTPException(404, "场景项目不存在")
    return p


def _compile(p: SceneProject) -> dict[str, Any]:
    try:
        return service.compile_project(p)
    except SceneRunError as exc:
        raise HTTPException(503, f"场景执行器不可用：{exc}") from exc


# ── 目录 ────────────────────────────────────────────────

@router.get("/catalog")
def get_catalog() -> dict[str, Any]:
    """预制件、体型、姿势、运镜预设。"""
    try:
        return catalog()
    except SceneRunError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("/templates")
def get_templates() -> list[dict[str, str]]:
    return listing()


@router.get("/templates/{key}")
def get_template(key: str) -> dict[str, str]:
    t = TEMPLATES.get(key)
    if not t:
        raise HTTPException(404, "没有这个模板")
    return t


@router.get("/models")
def get_models(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """智能体可选的对话模型（text.chat 路由里启用的、免费的）。"""
    seen: dict[str, dict[str, Any]] = {}
    for r in resolve_routes(db, Capability.text_chat, agent.PURPOSE, None):
        if r.model and r.model not in seen:
            seen[r.model] = {"model": r.model, "billing": r.billing, "default": not seen}
    return list(seen.values())


# ── 项目 ────────────────────────────────────────────────

class ProjectIn(BaseModel):
    title: str = ""
    template: str | None = None
    novel_id: str | None = None
    shot_plan_id: str | None = None
    scene_id: str | None = None


class ProjectPatch(BaseModel):
    title: str | None = None
    seed: int | None = None
    settings: dict[str, Any] | None = None


@router.get("/projects")
def list_projects(plan_id: str | None = None, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """白模项目列表。plan_id：只列这份分镜的白模（导演出片搭的那些，按镜号排），每项带 shot_id / shot_order。

    镜头 → 白模的关联记在 shots.camera_json.director_run.box_project_id（老项目的 shot_plan_id 列是空的），
    所以从镜头这一侧反查，不用回填数据库。
    """
    if not plan_id:
        rows = db.execute(select(SceneProject).order_by(SceneProject.updated_at.desc()).limit(200)).scalars()
        return [service.project_out(p, full=False) for p in rows]
    from app.models import Shot

    by_box: dict[str, Shot] = {}
    for sh in db.execute(select(Shot).where(Shot.shot_plan_id == plan_id).order_by(Shot.order_no)).scalars():
        run = (sh.camera_json or {}).get("director_run") if isinstance(sh.camera_json, dict) else None
        pid = run.get("box_project_id") if isinstance(run, dict) else None
        if pid and pid not in by_box:
            by_box[pid] = sh
    q = select(SceneProject).where((SceneProject.id.in_(list(by_box))) | (SceneProject.shot_plan_id == plan_id))
    out = []
    for p in db.execute(q).scalars():
        d = service.project_out(p, full=False)
        sh = by_box.get(p.id)
        d.update({"shot_id": sh.id if sh else None, "shot_order": sh.order_no if sh else None})
        out.append(d)
    out.sort(key=lambda d: (d["shot_order"] is None, d["shot_order"] or 0, d["title"] or ""))
    return out


@router.post("/projects")
def create_project(body: ProjectIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    if body.template and body.template not in TEMPLATES:
        raise HTTPException(422, f"没有模板「{body.template}」")
    try:
        p = service.new_project(db, title=body.title, template=body.template, novel_id=body.novel_id,
                                shot_plan_id=body.shot_plan_id, scene_id=body.scene_id)
    except SceneRunError as exc:
        raise HTTPException(503, f"场景执行器不可用：{exc}") from exc
    db.commit()
    return service.project_out(p)


@router.get("/projects/{pid}")
def get_project(pid: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    p = _project(db, pid)
    out = service.project_out(p)
    run = agent.active_run(pid)
    out["active_run"] = run.id if run else None
    return out


@router.patch("/projects/{pid}")
def patch_project(pid: str, body: ProjectPatch, db: Session = Depends(get_db)) -> dict[str, Any]:
    p = _project(db, pid)
    if body.title is not None:
        p.title = body.title.strip()[:200] or p.title
    if body.settings is not None:
        p.settings_json = {**(p.settings_json or {}), **body.settings}
    if body.seed is not None and body.seed != p.seed:
        p.seed = body.seed
        _compile(p)
    db.commit()
    return service.project_out(p)


@router.delete("/projects/{pid}")
def delete_project(pid: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    p = _project(db, pid)
    if agent.active_run(pid):
        raise HTTPException(409, "智能体正在改这个场景，先停止")
    db.delete(p)
    db.commit()
    return {"deleted": pid}


class FileIn(BaseModel):
    content: str = Field(max_length=service.MAX_FILE)


@router.put("/projects/{pid}/files/{path}")
def put_file(pid: str, path: str, body: FileIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    """人在界面上直接改脚本。和智能体的 x_write 走同一条路，进同一份版本历史。"""
    p = _project(db, pid)
    if agent.active_run(pid):
        raise HTTPException(409, "智能体正在改这个场景，先停止再手改")
    try:
        service.write_file(p, path, body.content, by="user", note=f"手改 {path}")
    except service.SceneFileError as exc:
        raise HTTPException(422, str(exc)) from exc
    if path == service.ENTRY:
        _compile(p)
    db.commit()
    return service.project_out(p)


@router.post("/projects/{pid}:compile")
def compile_project(pid: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    p = _project(db, pid)
    _compile(p)
    db.commit()
    return service.project_out(p)


class OverridesIn(BaseModel):
    overrides: dict[str, Any]


@router.put("/projects/{pid}/overrides")
def put_overrides(pid: str, body: OverridesIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    """台上拖动、改颜色、改机位关键帧：存成覆盖层，脚本重跑后按 id 叠回去。"""
    p = _project(db, pid)
    service.set_overrides(p, body.overrides)
    _compile(p)
    db.commit()
    return service.project_out(p)


@router.post("/projects/{pid}/versions/{index}:restore")
def restore(pid: str, index: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    p = _project(db, pid)
    if agent.active_run(pid):
        raise HTTPException(409, "智能体正在改这个场景，先停止")
    try:
        service.restore_version(p, index, by="user")
    except service.SceneFileError as exc:
        raise HTTPException(422, str(exc)) from exc
    _compile(p)
    db.commit()
    return service.project_out(p)


# ── 智能体 ──────────────────────────────────────────────

class AgentIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    selected: list[str] = Field(default_factory=list)
    sketches: list[dict[str, Any]] = Field(default_factory=list)
    model: str | None = None


@router.post("/projects/{pid}/agent")
def start_agent(pid: str, body: AgentIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    _project(db, pid)
    try:
        run = agent.start_run(pid, body.message.strip(), selected=body.selected, sketches=body.sketches, model=body.model)
    except agent.AgentError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"run_id": run.id}


@router.get("/projects/{pid}/agent/{rid}/events")
def agent_events(pid: str, rid: str, after: int = 0) -> dict[str, Any]:
    run = agent.get_run(rid)
    if run is None or run.project_id != pid:
        raise HTTPException(404, "这次运行不在内存里了（服务重启过），看对话记录")
    events, done = run.after(after)
    return {"events": events, "done": done, "status": run.status}


@router.get("/projects/{pid}/agent/{rid}/stream")
def agent_stream(pid: str, rid: str, after: int = 0) -> StreamingResponse:
    """SSE：运行在后台线程里跑，断线不影响它；重连带 after 接着收。"""
    run = agent.get_run(rid)
    if run is None or run.project_id != pid:
        raise HTTPException(404, "这次运行不在内存里了（服务重启过），看对话记录")

    def gen():
        seq = after
        while True:
            events, done = run.after(seq)
            for e in events:
                seq = e["seq"]
                yield f"id: {seq}\ndata: {json.dumps(e, ensure_ascii=False)}\n\n"
            if done and not run.after(seq)[0]:
                break
            run.wait(seq, 15)
            if not run.after(seq)[0] and not done:
                yield ": keepalive\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/projects/{pid}/agent/{rid}:stop")
def stop_agent(pid: str, rid: str) -> dict[str, Any]:
    return {"stopped": agent.stop_run(rid)}


@router.get("/projects/{pid}/messages")
def messages(pid: str, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    _project(db, pid)
    rows = db.execute(select(SceneMessage).where(SceneMessage.project_id == pid)
                      .order_by(SceneMessage.created_at).limit(400)).scalars()
    return [{"id": m.id, "run_id": m.run_id, "role": m.role, "content": m.content,
             "meta": {k: v for k, v in (m.meta_json or {}).items() if k != "thought"},
             "at": m.created_at.isoformat()} for m in rows]


# ── 导出 ────────────────────────────────────────────────

@router.post("/projects/{pid}/exports")
async def export_video(pid: str, file: UploadFile = File(...), camera: str = Form(""),
                       duration: float = Form(0), kind: str = Form("preview"),
                       db: Session = Depends(get_db)) -> dict[str, Any]:
    """成片预演录成的视频（浏览器录画布）或关键帧截图，存成资产。"""
    p = _project(db, pid)
    raw = await file.read()
    if not raw:
        raise HTTPException(422, "空文件")
    if len(raw) > 200 * 1024 * 1024:
        raise HTTPException(413, "文件超过 200MB")
    mime = file.content_type or "video/webm"
    if not (mime.startswith("video/") or mime.startswith("image/")):
        raise HTTPException(422, "只收视频或图片")
    item = store_bytes(raw, mime=mime)
    asset = Asset(id=new_id("as"), kind=AssetKind.video if mime.startswith("video/") else AssetKind.image,
                  url=str(item["url"]), sha256=str(item["sha256"]), mime=str(item["mime"]), bytes=int(item["bytes"]),
                  source=AssetSource.uploaded, novel_id=p.novel_id,
                  meta_json={"scene_project_id": p.id, "camera": camera, "duration": duration, "kind": kind,
                             "title": p.title})
    db.add(asset)
    if asset.kind == AssetKind.image and kind == "thumb":
        p.thumb_url = asset.url
    db.commit()
    return {"asset_id": asset.id, "url": asset.url, "kind": asset.kind.value}


@router.get("/projects/{pid}/exports")
def list_exports(pid: str, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    _project(db, pid)
    rows = db.execute(select(Asset).where(Asset.meta_json["scene_project_id"].astext == pid)
                      .order_by(Asset.created_at.desc()).limit(50)).scalars()
    return [{"asset_id": a.id, "url": a.url, "kind": a.kind.value, "meta": a.meta_json,
             "at": a.created_at.isoformat()} for a in rows]
