"""Scene Store：Director 场景的读写。

两种来源：
  3dbox —— 从 3D-BOX 项目导出（项目的脚本＋手动改动是真身，这里存导出时的协议快照，重导出就更新）
  api / llm —— 协议是真身（JSON 优先）；同时生成一个 3D-BOX 项目（scene.js 由协议生成），方便在台上看、拖、让智能体接着改

对 3dbox 场景打 JSON Patch：改动落在协议上，并用协议重新生成项目的 scene.js（原脚本进版本史，可以恢复），
场景随之转成 JSON 优先 —— 两份真身并存只会互相覆盖。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.director import patch as jpatch
from app.director.convert import doc_to_protocol, protocol_to_script
from app.director.protocol import SceneProtocol
from app.ids import new_id
from app.models import DirectorScene, SceneProject
from app.scene3d import service as box
from app.scene3d.runner import bake_scene, compile_scene


class SceneStoreError(ValueError):
    pass


def scene_out(s: DirectorScene, *, full: bool = True) -> dict[str, Any]:
    p = s.protocol_json or {}
    out = {
        "id": s.id, "title": s.title, "source": s.source, "box_project_id": s.box_project_id, "version": s.version,
        "prompt": s.prompt, "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        "duration": (p.get("meta") or {}).get("duration_sec"), "actors": len(p.get("actors") or []),
        "props": len(p.get("props") or []), "cameras": len(p.get("cameras") or []), "ops": len(p.get("timeline") or []),
    }
    if full:
        out["protocol"] = p
        out["notes"] = s.notes_json
    return out


def get_scene(db: Session, sid: str) -> DirectorScene:
    s = db.get(DirectorScene, sid)
    if s is None:
        raise SceneStoreError("场景不存在")
    return s


def _project(db: Session, pid: str) -> SceneProject:
    p = db.get(SceneProject, pid)
    if p is None:
        raise SceneStoreError("3D-BOX 项目不存在")
    return p


def export_box(db: Session, project_id: str) -> DirectorScene:
    """3D-BOX 项目 → 协议快照（同一项目只留一份场景，重导出版本号 +1）。"""
    p = _project(db, project_id)
    r = box.compile_project(p)
    if not r.get("ok") or not p.compiled_json:
        errs = "；".join(e.get("message", "") for e in (r.get("errors") or [])[:3])
        raise SceneStoreError(f"场景脚本有错，先在 3D-BOX 里修好：{errs}")
    doc = p.compiled_json
    baked = bake_scene(doc)
    s = db.execute(select(DirectorScene).where(DirectorScene.box_project_id == p.id)
                   .order_by(DirectorScene.created_at.desc())).scalars().first()
    sid = s.id if s else new_id("dsc")
    proto = doc_to_protocol(doc, scene_id=sid, title=p.title, source={"kind": "3dbox", "project_id": p.id}, baked=baked)
    if s is None:
        s = DirectorScene(id=sid, title=p.title, source="3dbox", box_project_id=p.id, protocol_json=proto, version=1)
        db.add(s)
    else:
        if s.protocol_json != proto:
            s.version = (s.version or 1) + 1
        s.protocol_json, s.title, s.source = proto, p.title, "3dbox"
    db.flush()
    return s


def _sync_box(db: Session, s: DirectorScene, sp: SceneProtocol, note: str) -> SceneProject:
    """协议 → scene.js 写进项目（没有项目就建一个），重编译。"""
    script = protocol_to_script(sp)
    r = compile_scene(script)
    if not r.get("ok"):
        errs = "；".join(e.get("message", "") for e in (r.get("errors") or [])[:3])
        raise SceneStoreError(f"协议转成场景脚本后跑不通：{errs}")
    p = db.get(SceneProject, s.box_project_id) if s.box_project_id else None
    if p is None:
        p = box.new_project(db, title=sp.meta.title, template="blank")
        s.box_project_id = p.id
    box.write_file(p, box.ENTRY, script, by="director", note=note)
    p.overrides_json = {}
    box.compile_project(p)
    return p


def create_from_protocol(db: Session, protocol: dict[str, Any], *, source: str = "api", prompt: str | None = None,
                         notes: dict[str, Any] | None = None) -> DirectorScene:
    data = dict(protocol)
    data.setdefault("scene_id", new_id("dsc"))
    try:
        sp = SceneProtocol.model_validate(data)
    except Exception as exc:
        raise SceneStoreError(f"场景协议不合法：{exc}") from exc
    sid = sp.scene_id if not db.get(DirectorScene, sp.scene_id) else new_id("dsc")
    if sid != sp.scene_id:
        sp = sp.model_copy(update={"scene_id": sid})
    s = DirectorScene(id=sid, title=sp.meta.title, source=source, protocol_json=sp.model_dump(mode="json", exclude_none=True),
                      version=1, prompt=prompt, notes_json=notes)
    db.add(s)
    db.flush()
    _sync_box(db, s, sp, "由场景协议生成")
    db.flush()
    return s


def scene_doc(db: Session, s: DirectorScene) -> dict[str, Any]:
    """渲染用的场景文档。3dbox 场景用项目当前编译结果；JSON 场景由协议生成脚本再编译。"""
    if s.source == "3dbox" and s.box_project_id:
        p = _project(db, s.box_project_id)
        r = box.compile_project(p)
        if not r.get("ok") or not p.compiled_json:
            raise SceneStoreError("3D-BOX 场景脚本有错，先修好再渲染")
        return p.compiled_json
    r = compile_scene(protocol_to_script(s.protocol_json))
    if not r.get("ok") or not r.get("doc"):
        errs = "；".join(e.get("message", "") for e in (r.get("errors") or [])[:3])
        raise SceneStoreError(f"场景跑不通：{errs}")
    return r["doc"]


def patch_scene(db: Session, s: DirectorScene, ops: list[dict[str, Any]], *, by: str = "api") -> DirectorScene:
    new = jpatch.apply(s.protocol_json or {}, ops)
    new["scene_id"] = s.id
    try:
        sp = SceneProtocol.model_validate(new)
    except Exception as exc:
        raise SceneStoreError(f"打完补丁后协议不合法：{exc}") from exc
    s.protocol_json = sp.model_dump(mode="json", exclude_none=True)
    s.version = (s.version or 1) + 1
    s.title = sp.meta.title
    if s.source == "3dbox":
        s.source = "api"          # 改动落在协议上：从此协议是真身（原脚本在项目版本史里）
    _sync_box(db, s, sp, f"JSON Patch（{by}，{len(ops)} 条）")
    db.flush()
    return s
