"""R0/R1 APIs: source-backed context, reference resolution and canonical binding."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Asset, AssetEpoch, AssetKind, EntityKind, StudioBoard, WorldEntity, WorldProfile
from app.production import service as svc
from app.production.schema import AddReferenceIn, ContextPatch, PackBinding, PrepareIn, ResolveIn

router = APIRouter(prefix="/api/v2/production", tags=["production"])


def fail(exc: svc.ProductionError):
    raise HTTPException(exc.status, detail={"code": exc.code, "message": str(exc), "issues": []}) from exc


@router.get("/context")
def get_context(board_id: str, db: Session = Depends(get_db)):
    try:
        row = svc.board(db, board_id)
        context, issues = svc.context_for(db, row)
        return svc.envelope({"context": context.model_dump(), "board_version": row.version,
                             "readiness": {"context": "partial" if issues else "available",
                                           "editing": "available",
                                           "story_source": "bound" if context.novel_id else "unbound",
                                           "world_binding": "bound" if context.world_profile_id else "unbound",
                                           "resource_resolution": "available",
                                           "snapshot": "not_implemented",
                                           "generation": "not_implemented"}}, issues)
    except svc.ProductionError as exc:
        fail(exc)


@router.patch("/canvases/{board_id}/context")
def patch_context(board_id: str, body: ContextPatch, db: Session = Depends(get_db)):
    try:
        row = svc.board(db, board_id, lock=True)
        if row.version != body.base_version:
            raise svc.ProductionError("board_version_conflict", "画布已变化，请刷新后保存", 409)
        if body.return_to:
            target = svc.board(db, body.return_to.board_id)
            if target.workspace_id != row.workspace_id:
                raise svc.ProductionError("return_target_invalid", "返回画布不属于当前工作区")
            if body.return_to.node_id:
                nodes = (target.doc_json or {}).get("nodes") or []
                if not any(n.get("id") == body.return_to.node_id for n in nodes if isinstance(n, dict)):
                    raise svc.ProductionError("return_target_invalid", "返回节点不存在", 404)
        scope = dict(row.scope_json or {})
        scope["production"] = {
            "purpose": body.purpose, "world_profile_id": body.world_profile_id,
            "return_to": body.return_to.model_dump() if body.return_to else None,
        }
        scope["purpose"] = body.purpose  # Existing canvas metadata callers see the same purpose.
        row.scope_json = scope
        context, issues = svc.context_for(db, row)
        row.version += 1
        db.commit()
        return svc.envelope({"context": context.model_dump(), "board_version": row.version}, issues)
    except svc.ProductionError as exc:
        db.rollback()
        fail(exc)


@router.post("/resources:resolve")
def resolve_resources(body: ResolveIn, db: Session = Depends(get_db)):
    try:
        row, context = svc.assert_context(db, body.context)
        items = []
        for ref in body.refs:
            try:
                items.append(svc.resolve_one(db, row, context, ref))
            except svc.ProductionError as exc:
                items.append({"ref": ref.model_dump(), "status": "unresolved", "resource": None,
                              "issues": [{"code": exc.code, "message": str(exc), "http_status": exc.status}]})
        return svc.envelope({"context": context.model_dump(), "items": items})
    except svc.ProductionError as exc:
        fail(exc)


@router.get("/entities/{entity_id}/epochs")
def entity_epochs(entity_id: str, board_id: str | None = None, db: Session = Depends(get_db)):
    """选择真实已存在的世界/时期；读取不会生成或绑定任何素材。"""
    try:
        ent = svc.get(db, WorldEntity, entity_id)
        row = svc.board(db, board_id) if board_id else None
        context, issues = svc.context_for(db, row) if row else (None, [])
        if row and (ent.workspace_id != row.workspace_id or (context.novel_id and ent.novel_id != context.novel_id)):
            raise svc.ProductionError("scope_mismatch", "实体不属于当前项目")
        q = select(AssetEpoch).where(AssetEpoch.subject_key == ent.id,
                                    AssetEpoch.workspace_id == ent.workspace_id)
        if context and context.world_profile_id:
            q = q.where(AssetEpoch.world_profile_id == context.world_profile_id)
        epochs = list(db.scalars(q.order_by(AssetEpoch.order_no, AssetEpoch.id)))
        profiles = {w.id: w for w in db.scalars(select(WorldProfile).where(
            WorldProfile.id.in_({e.world_profile_id for e in epochs}),
            WorldProfile.workspace_id == ent.workspace_id))} if epochs else {}
        return svc.envelope({"items": [{"id": e.id, "epoch_key": e.epoch_key,
            "name": e.display_name, "world_profile_id": e.world_profile_id,
            "world_name": getattr(profiles.get(e.world_profile_id), "display_name", None) or e.world_profile_id,
            "from_chapter_order": e.from_chapter_order, "to_chapter_order": e.to_chapter_order}
            for e in epochs if e.world_profile_id in profiles]}, issues)
    except svc.ProductionError as exc:
        fail(exc)


@router.get("/entities/{entity_id}/canonical-pack")
def get_pack(entity_id: str, world_profile_id: str, epoch_id: str | None = None,
             chapter_order: int | None = Query(None, ge=1), db: Session = Depends(get_db)):
    try:
        ent = svc.get(db, WorldEntity, entity_id)
        epoch = svc.choose_epoch(db, ent, world_profile_id, epoch_id, chapter_order)
        return svc.envelope(svc.pack_data(db, ent, epoch))
    except svc.ProductionError as exc:
        fail(exc)


@router.patch("/entities/{entity_id}/canonical-pack")
def bind_pack(entity_id: str, body: PackBinding, db: Session = Depends(get_db)):
    try:
        ent = svc.get(db, WorldEntity, entity_id)
        # Lock the authoritative epoch before comparing its resource revision.
        epoch = db.scalar(select(AssetEpoch).where(
            AssetEpoch.id == body.epoch_id, AssetEpoch.subject_key == ent.id,
            AssetEpoch.workspace_id == ent.workspace_id).with_for_update())
        if epoch is None:
            raise svc.ProductionError("epoch_missing", "造型时期不属于该角色", 404)
        svc.choose_epoch(db, ent, epoch.world_profile_id, epoch.id)
        result = svc.bind_pack(db, ent, epoch, body)
        db.commit()
        return svc.envelope(result)
    except svc.ProductionError as exc:
        db.rollback()
        fail(exc)


@router.get("/resources")
def list_resources(board_id: str, kind: Literal["entity", "asset", "audio"] = "entity",
                   query: str = Query("", max_length=200), entity_kind: EntityKind | None = None, offset: int = Query(0, ge=0),
                   limit: int = Query(50, ge=1, le=100), db: Session = Depends(get_db)):
    try:
        row = svc.board(db, board_id)
        context, issues = svc.context_for(db, row)
        if kind == "entity":
            q = select(WorldEntity).where(WorldEntity.workspace_id == row.workspace_id)
            if context.novel_id:
                q = q.where(WorldEntity.novel_id == context.novel_id)
            if entity_kind is not None:
                q = q.where(WorldEntity.kind == entity_kind)
            if query:
                q = q.where(WorldEntity.display_name.contains(query, autoescape=True))
        else:
            q = select(Asset).where(Asset.workspace_id == row.workspace_id)
            if context.novel_id:
                q = q.where(Asset.novel_id.in_([context.novel_id]) | Asset.novel_id.is_(None))
            if kind == "audio":
                q = q.where(Asset.kind == AssetKind.audio)
            if query:
                q = q.where(Asset.id.contains(query, autoescape=True))
        model = WorldEntity if kind == "entity" else Asset
        rows = list(db.scalars(q.order_by(model.id).offset(offset).limit(limit + 1)))
        items = []
        for item in rows[:limit]:
            data = (svc.entity_data(db, item, context.transform_id) if kind == "entity" else
                    {**svc.asset_data(item), "novel_id": item.novel_id})
            items.append({"ref": {"kind": kind, "id": item.id, "revision": data["revision"],
                                  "mode": "reference", "binding": {}}, "resource": data})
        return svc.envelope({"items": items, "next_offset": offset + limit if len(rows) > limit else None}, issues)
    except svc.ProductionError as exc:
        fail(exc)


@router.post("/canvases/{board_id}/references")
def add_reference(board_id: str, body: AddReferenceIn, db: Session = Depends(get_db)):
    """从角色库直接加入指定画布；原子写入引用，不复制素材或启动生成。"""
    from app.api.v2.canvas import _save, _validated, place_below
    try:
        row = svc.board(db, board_id, lock=True)
        if row.version != body.base_version:
            raise svc.ProductionError("board_version_conflict", "画布已变化，请重新载入后再加入", 409)
        if not body.ref.revision:
            raise svc.ProductionError("revision_required", "请选择已有版本的素材")
        context, _issues = svc.context_for(db, row)
        item = svc.resolve_one(db, row, context, body.ref)
        resource = item["resource"]
        media = resource.get("media")
        if resource.get("kind") not in {"stage", "coverage"} and (not media or resource.get("kind") not in {"image", "video", "audio"}):
            raise svc.ProductionError("media_required", "请选择可用的图片、视频或音频视图")
        ref = item["ref"]
        doc = dict(row.doc_json or {})
        doc.setdefault("schema", "ainer.board/v1")
        doc.setdefault("viewport", {"x": 0, "y": 0, "zoom": 1})
        nodes = list(doc.get("nodes") or [])
        for n in nodes:
            if isinstance(n, dict) and (n.get("data") or {}).get("ref") == ref:
                return svc.envelope({"node_id": n["id"], "board_version": row.version, "reused": True})
        from app.ids import new_id
        nid = new_id("nref")
        data = {"ref": ref, "title": body.title or resource.get("name") or ref["id"]}
        if ref["kind"] == "canonical_view":
            data["role"] = "view"
        nodes.append({"id": nid, "type": resource["kind"], "position": place_below(doc), "data": data})
        doc.update(nodes=nodes, edges=list(doc.get("edges") or []))
        saved = _save(db, row, _validated(doc))
        return svc.envelope({"node_id": nid, "board_version": saved.version, "reused": False})
    except svc.ProductionError as exc:
        db.rollback()
        fail(exc)


@router.post("/prepare")
def prepare_resources(body: PrepareIn, db: Session = Depends(get_db)):
    """A real reuse/missing plan. Submission is explicitly unavailable in this batch."""
    try:
        row, context = svc.assert_context(db, body.context)
        if body.submit:
            raise svc.ProductionError("submission_not_implemented", "本批 prepare 只规划缺项；尚未接入单格补建任务")
        if body.return_slot:
            target = svc.board(db, body.return_slot.board_id)
            target_context, _ = svc.context_for(db, target)
            if target.workspace_id != row.workspace_id or target_context.novel_id != context.novel_id:
                raise svc.ProductionError("return_target_invalid", "返回槽位与当前生产项目不一致")
            if not any(isinstance(n, dict) and n.get("id") == body.return_slot.node_id
                       for n in (target.doc_json or {}).get("nodes") or []):
                raise svc.ProductionError("return_target_invalid", "返回槽位节点尚未保存或不存在", 404)
        plan = []
        for ref in body.refs:
            try:
                resolved = svc.resolve_one(db, row, context, ref)
                resource = resolved["resource"]
                missing = resource.get("missing", []) if ref.kind in {"canonical_pack", "variant"} else []
                plan.append({"ref": resolved["ref"], "action": "missing_views" if missing else "reuse",
                             "missing": missing, "resource": resource, "issues": []})
            except svc.ProductionError as exc:
                action = "missing" if exc.code in {"view_missing", "epoch_missing", "resource_missing"} else "blocked"
                plan.append({"ref": ref.model_dump(), "action": action, "resource": None,
                             "issues": [{"code": exc.code, "message": str(exc)}]})
        return svc.envelope({"context": context.model_dump(), "plan": plan, "jobs": [],
                             "submission": "not_implemented",
                             "return_slot": body.return_slot.model_dump() if body.return_slot else None},
                            [{"code": "plan_only", "message": "仅复用/缺项规划，没有提交生成任务"}])
    except svc.ProductionError as exc:
        fail(exc)


@router.get("/resources/{resource_id}/usages")
def resource_usages(resource_id: str, board_id: str, revision: str | None = None,
                    offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
                    db: Session = Depends(get_db)):
    """Report persisted canvas references only; never claim a complete render dependency index."""
    try:
        row = svc.board(db, board_id)
        context, issues = svc.context_for(db, row)
        q = select(StudioBoard).where(StudioBoard.workspace_id == row.workspace_id)
        # Shared resources can be referenced by free boards and chapter boards in
        # the same workspace; the story association is not the usage boundary.
        found = []
        for target in db.scalars(q.order_by(StudioBoard.id)):
            for node in (target.doc_json or {}).get("nodes") or []:
                if not isinstance(node, dict):
                    continue
                ref = (node.get("data") or {}).get("ref") or {}
                if ref.get("id") == resource_id and (revision is None or ref.get("revision") == revision):
                    found.append({"board_id": target.id, "board_version": target.version,
                                  "node_id": node.get("id"), "ref": ref})
        return svc.envelope({"items": found[offset:offset + limit],
                             "next_offset": offset + limit if len(found) > offset + limit else None,
                             "coverage": {"scanned": ["studio_boards.doc_json.nodes[].data.ref"],
                                          "not_scanned": ["recipes", "frame_specs", "director_jobs", "render_tasks"],
                                          "complete": False}}, issues)
    except svc.ProductionError as exc:
        fail(exc)
