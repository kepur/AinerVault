"""Ainer Director Core 接口：场景协议、Blender 控制素材、LTX 成片、UE 预埋、功能开关。

对应 V1 方案里的 /api/v1/*，挂在 /api/v2/director 下（与本系统其它接口同一版本号）：
  POST /scenes                       建场景：{protocol} 或 {box_project_id}（从 3D-BOX 导出）
  GET  /scenes /scenes/{id}          读
  PATCH /scenes/{id}                 JSON Patch（RFC 6902）
  POST /scenes:generate              一句话 → 场景协议（LLM）→ 同时生成 3D-BOX 项目
  POST /scenes/{id}:edit             一句话修改 → LLM 出 patch → 打上
  POST /jobs/blender-render          渲控制素材（preview/clay/depth/pose/canny＋camera/motion json）
  GET  /jobs /jobs/{id}              任务状态、进度
  POST /jobs/{id}/render-final       控制素材 → LTX 成片
  GET  /jobs/{id}/artifacts          产物清单
  GET  /jobs/{id}/files/{path}       产物文件
  POST /jobs/{id}:cancel             取消
  POST /ue/plan                      UE 翻译 dry-run（开关关着也能看）
  POST /ue/execute                   真连 UE（V1 关闭）
  GET  /system/features              功能开关与各后端状态
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.director import blender_adapter, config, jobs, outputs, planner, store
from app.director.patch import PatchError
from app.director.protocol import json_schema
from app.director.renderers import registry
from app.director.renderers.base import RendererError
from app.director.ue_worker import adapter as ue
from app.models import DirectorJob, DirectorScene

router = APIRouter(prefix="/api/v2/director", tags=["director"])


def _fail(exc: Exception) -> HTTPException:
    if isinstance(exc, config.FeatureDisabled):
        return HTTPException(409, str(exc))
    if isinstance(exc, (store.SceneStoreError, PatchError, jobs.JobError, RendererError, planner.PlannerError)):
        return HTTPException(422, str(exc))
    return HTTPException(500, f"{type(exc).__name__}: {exc}")


def _started() -> None:
    jobs.recover()


# ── 系统 ────────────────────────────────────────────────

@router.get("/system/features")
def features(db: Session = Depends(get_db)) -> dict[str, Any]:
    _started()
    ltx = registry.get("ltx_097")
    return {
        **config.features(),
        "blender": blender_adapter.status(),
        "renderers": {
            "ltx_097": {**ltx.describe(), "control_types": ltx.control_types(db) if ltx.enabled() else []},
            "ltx_25": registry.get("ltx_25").describe(),
        },
        "ue": {"enabled": config.enabled("ue_enabled"), "remote_control": (config.load("ue").get("remote_control") or {}).get("http")},
    }


@router.get("/protocol/schema")
def protocol_schema() -> dict[str, Any]:
    return json_schema()


@router.get("/catalog")
def director_catalog() -> dict[str, Any]:
    from app.scene3d.runner import catalog
    cat = catalog()
    return {"motions": cat.get("motions", []), "camera_presets": cat.get("cameraPresets", []),
            "bodies": cat.get("bodies", []), "poses": cat.get("poses", [])}


# ── 场景 ────────────────────────────────────────────────

class SceneIn(BaseModel):
    protocol: dict[str, Any] | None = None
    box_project_id: str | None = None
    title: str | None = None


@router.post("/scenes")
def create_scene(body: SceneIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        if body.box_project_id:
            s = store.export_box(db, body.box_project_id)
        elif body.protocol:
            proto = dict(body.protocol)
            if body.title:
                proto.setdefault("meta", {})["title"] = body.title
            s = store.create_from_protocol(db, proto, source="api")
        else:
            raise HTTPException(422, "给 protocol 或 box_project_id")
        db.commit()
        return store.scene_out(s)
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise _fail(exc) from exc


@router.get("/scenes")
def list_scenes(box_project_id: str | None = None, limit: int = 50, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    q = select(DirectorScene).order_by(DirectorScene.updated_at.desc()).limit(min(200, limit))
    if box_project_id:
        q = q.where(DirectorScene.box_project_id == box_project_id)
    return [store.scene_out(s, full=False) for s in db.execute(q).scalars()]


@router.get("/scenes/{sid}")
def get_scene(sid: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        return store.scene_out(store.get_scene(db, sid))
    except store.SceneStoreError as exc:
        raise HTTPException(404, str(exc)) from exc


class PatchIn(BaseModel):
    patch: list[dict[str, Any]]


@router.patch("/scenes/{sid}")
def patch_scene(sid: str, body: PatchIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        s = store.patch_scene(db, store.get_scene(db, sid), body.patch)
        db.commit()
        return store.scene_out(s)
    except Exception as exc:
        db.rollback()
        raise _fail(exc) from exc


class GenerateIn(BaseModel):
    prompt: str = Field(min_length=2, max_length=2000)
    duration: float | None = Field(None, gt=0, le=60)
    model: str | None = None


@router.post("/scenes:generate")
def generate_scene(body: GenerateIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        proto, repairs = planner.generate_protocol(db, body.prompt, duration=body.duration, model=body.model)
        s = store.create_from_protocol(db, proto, source="llm", prompt=body.prompt, notes={"repairs": repairs})
        db.commit()
        return {**store.scene_out(s), "repairs": len(repairs)}
    except Exception as exc:
        db.rollback()
        raise _fail(exc) from exc


class ShotRenderIn(BaseModel):
    seed: int | None = None
    control_type: str = Field("union", pattern="^(union|pose|depth)$")


@router.post("/shots/{shot_id}:render")
def render_shot(shot_id: str, body: ShotRenderIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    """分镜 → 3D 导演出片：LLM 按这一镜搭 3D-BOX 场景 → Blender 控制素材 → LTX 2.5 按控制出片 → 挂回镜头。

    接口只做搭景、交 Blender 任务；成片和挂回在任务队列里接着跑（看 /jobs/{blender_job_id} 的进度）。
    """
    from app.director import from_shot

    _started()
    try:
        out = from_shot.render_shot(db, shot_id, seed=body.seed, control_type=body.control_type)
        db.commit()
        return out
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        raise _fail(exc) from exc


class EditIn(BaseModel):
    instruction: str = Field(min_length=2, max_length=2000)
    model: str | None = None


@router.post("/scenes/{sid}:edit")
def edit_scene(sid: str, body: EditIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        s = store.get_scene(db, sid)
        ops, say = planner.edit_patch(db, s.protocol_json or {}, body.instruction, model=body.model)
        s = store.patch_scene(db, s, ops, by="llm")
        db.commit()
        return {**store.scene_out(s), "patch": ops, "say": say}
    except Exception as exc:
        db.rollback()
        raise _fail(exc) from exc


# ── 任务 ────────────────────────────────────────────────

class BlenderIn(BaseModel):
    scene_id: str | None = None
    box_project_id: str | None = None
    render_plan: dict[str, Any] | None = None


@router.post("/jobs/blender-render")
def blender_render(body: BlenderIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    _started()
    try:
        if body.box_project_id:
            s = store.export_box(db, body.box_project_id)
        elif body.scene_id:
            s = store.get_scene(db, body.scene_id)
        else:
            raise HTTPException(422, "给 scene_id 或 box_project_id")
        j = jobs.submit_blender(db, s, body.render_plan)
        return jobs.job_out(j, db)
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise _fail(exc) from exc


def _job(db: Session, jid: str) -> DirectorJob:
    j = db.get(DirectorJob, jid)
    if j is None:
        raise HTTPException(404, "任务不存在")
    return j


@router.get("/jobs")
def list_jobs(scene_id: str | None = None, box_project_id: str | None = None, limit: int = 30,
              db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    _started()
    q = select(DirectorJob).order_by(DirectorJob.created_at.desc()).limit(min(200, limit))
    if box_project_id:
        sids = [s.id for s in db.execute(select(DirectorScene).where(DirectorScene.box_project_id == box_project_id)).scalars()]
        q = q.where(DirectorJob.scene_id.in_(sids or [""]))
    elif scene_id:
        q = q.where(DirectorJob.scene_id == scene_id)
    return [jobs.job_out(j, db) for j in db.execute(q).scalars()]


@router.get("/jobs/{jid}")
def get_job(jid: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return jobs.job_out(_job(db, jid), db)


class FinalIn(BaseModel):
    renderer: str = "ltx_097"
    control_type: str | None = None
    v2v_source: str | None = None
    prompt: str | None = None
    negative_prompt: str | None = None
    seed: int | None = None
    denoise: float | None = Field(None, ge=0.3, le=1.0)
    strength: float | None = Field(None, ge=0, le=2)
    pin_first: bool | None = None
    reference_images: list[str] = Field(default_factory=list)
    style: str | None = None
    style_prompt: str | None = None
    use_llm_prompt: bool = True


@router.post("/jobs/{jid}/render-final")
def render_final(jid: str, body: FinalIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    _started()
    try:
        j = jobs.submit_final(db, _job(db, jid), body.model_dump(exclude_none=True))
        return jobs.job_out(j, db)
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise _fail(exc) from exc


@router.get("/jobs/{jid}/artifacts")
def artifacts(jid: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    j = _job(db, jid)
    return {"job_id": j.id, "status": j.status, "manifest": j.output_manifest_json, "outputs": outputs.outputs_of(db, j.id)}


@router.get("/jobs/{jid}/files/{path:path}")
def job_file(jid: str, path: str) -> FileResponse:
    try:
        p = outputs.safe_file(jid, path)
    except FileNotFoundError as exc:
        raise HTTPException(404, "文件不存在") from exc
    return FileResponse(p)


@router.post("/jobs/{jid}:cancel")
def cancel_job(jid: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return jobs.job_out(jobs.cancel(db, _job(db, jid)), db)


# ── UE（V1 预埋）───────────────────────────────────────────

class UEIn(BaseModel):
    job_id: str | None = None          # 用某次 Blender 任务的烘焙快照
    scene_id: str | None = None


def _ue_inputs(db: Session, body: UEIn) -> tuple[dict[str, Any], dict[str, Any]]:
    if body.job_id:
        j = _job(db, body.job_id)
        jd = config.job_dir(j.id)
        return (json.loads((jd / "scene_protocol.json").read_text(encoding="utf-8")),
                json.loads(Path((j.input_json or {})["baked_path"]).read_text(encoding="utf-8")))
    if body.scene_id:
        from app.scene3d.runner import bake_scene
        s = store.get_scene(db, body.scene_id)
        return s.protocol_json or {}, bake_scene(store.scene_doc(db, s))
    raise HTTPException(422, "给 job_id 或 scene_id")


@router.post("/ue/plan")
def ue_plan(body: UEIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        return ue.plan(*_ue_inputs(db, body))
    except HTTPException:
        raise
    except Exception as exc:
        raise _fail(exc) from exc


@router.post("/ue/execute")
def ue_execute(body: UEIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        config.require("ue_enabled", "Unreal Engine 执行")
        return ue.execute(*_ue_inputs(db, body))
    except HTTPException:
        raise
    except Exception as exc:
        raise _fail(exc) from exc
