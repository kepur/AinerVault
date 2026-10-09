"""Resolve existing DB objects without submitting jobs or inventing missing assets."""
from __future__ import annotations

import hashlib
import json

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import (
    Asset, AssetEpoch, AssetKind, Chapter, EntityKind, EntityWorldName, Novel,
    Scene, ScriptBlock, ScriptDoc, Shot, ShotPlan, StudioBoard, WorldEntity, WorldProfile, WorldTransform,
)
from app.production.canonical import ALIASES, VIEW_KEYS, canonical_views
from app.production.schema import ProductionContext, ResourceRef, SCHEMA_VERSION, Scope


class ProductionError(ValueError):
    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code, self.status = code, status


def envelope(data, issues: list | None = None) -> dict:
    return {"schema_version": SCHEMA_VERSION, "data": data, "issues": issues or []}


def revision(value) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()


def get(db: Session, model, key: str | None, workspace: str | None = None):
    row = db.get(model, key) if key else None
    if row is None or (workspace is not None and row.workspace_id != workspace):
        raise ProductionError("resource_missing", f"{model.__name__}: {key} 不存在", 404)
    return row


def board(db: Session, board_id: str, *, lock: bool = False) -> StudioBoard:
    q = select(StudioBoard).where(StudioBoard.id == board_id)
    row = db.execute(q.with_for_update() if lock else q).scalar_one_or_none()
    if row is None:
        raise ProductionError("board_missing", "画布不存在", 404)
    return row


def context_for(db: Session, row: StudioBoard) -> tuple[ProductionContext, list]:
    ws = row.workspace_id
    plan = get(db, ShotPlan, row.shot_plan_id, ws) if row.shot_plan_id else None
    script = get(db, ScriptDoc, plan.script_doc_id, ws) if plan else None
    chapter_id = script.chapter_id if script else row.chapter_id
    chapter = get(db, Chapter, chapter_id, ws) if chapter_id else None
    if row.chapter_id and row.chapter_id != chapter_id:
        raise ProductionError("context_conflict", "画布章节与分镜计划不一致", 409)
    novel_id = chapter.novel_id if chapter else row.novel_id
    novel = get(db, Novel, novel_id, ws) if novel_id else None
    if row.novel_id and row.novel_id != novel_id:
        raise ProductionError("context_conflict", "画布小说与章节不一致", 409)
    transform = get(db, WorldTransform, plan.transform_id, ws) if plan and plan.transform_id else None
    if transform and transform.novel_id != novel_id:
        raise ProductionError("context_conflict", "转译映射不属于当前小说", 409)
    stored = row.scope_json or {}
    production = stored.get("production") or {}
    profile_id = (transform.target_profile_id if transform else
                  production.get("world_profile_id") or (novel.source_world_profile_id if novel else None))
    if transform and production.get("world_profile_id") not in (None, profile_id):
        raise ProductionError("context_conflict", "画布表现世界与分镜转译映射不一致", 409)
    if profile_id:
        profile = get(db, WorldProfile, profile_id, ws)
        if profile.novel_id not in (None, novel_id):
            raise ProductionError("context_conflict", "世界观不属于当前小说", 409)
    scenes = list(stored.get("scene_ids") or [])
    shots = list(stored.get("shot_ids") or [])
    if scenes:
        found = list(db.scalars(select(Scene).where(Scene.id.in_(scenes), Scene.workspace_id == ws)))
        if len(found) != len(set(scenes)) or not script or any(s.script_doc_id != script.id for s in found):
            raise ProductionError("scope_conflict", "画布场次不属于当前剧本", 409)
    if shots:
        found = list(db.scalars(select(Shot).where(Shot.id.in_(shots), Shot.workspace_id == ws)))
        if len(found) != len(set(shots)) or not plan or any(s.shot_plan_id != plan.id for s in found):
            raise ProductionError("scope_conflict", "画布镜头不属于当前计划", 409)
    purpose = production.get("purpose", stored.get("purpose", "directing" if row.kind in {"scene", "plan"} else "general"))
    issues = []
    if purpose not in {"assets", "directing", "finishing", "general"}:
        issues.append({"code": "legacy_purpose", "message": "旧用途标签保留，生产用途暂为 general"})
        purpose = "directing" if row.kind in {"scene", "plan"} else "general"
    # A free board is valid in its own right. Missing story/world bindings are only
    # requirements of specific compiling operations, never of editing a blank canvas.
    if plan and not profile_id:
        issues.append({"code": "context_incomplete", "field": "world_profile_id", "message": "该计划尚未绑定表现世界"})
    source = ({"script": script.id, "version": script.version, "input": script.input_fingerprint,
               "plan": plan.id, "plan_version": plan.version} if script and plan else
              {"chapter": chapter.id, "content": chapter.content} if chapter else None)
    if script:
        blocks = list(db.scalars(select(ScriptBlock).where(
            ScriptBlock.script_doc_id == script.id, ScriptBlock.workspace_id == ws).order_by(ScriptBlock.seq_no, ScriptBlock.id)))
        source["blocks"] = [{"id": b.id, "seq": b.seq_no, "type": b.block_type,
                             "text": b.source_text, "scene": b.scene_id, "speaker": b.speaker_entity_id,
                             "speaker_tag": b.speaker_tag, "addressees": b.addressee_tags,
                             "present": b.present_tags, "meta": b.meta_json} for b in blocks]
    ctx = ProductionContext(
        board_id=row.id, project_id=f"novel:{novel_id}" if novel_id else f"board:{row.id}",
        novel_id=novel_id, chapter_id=chapter_id, plan_id=plan.id if plan else None,
        script_doc_id=script.id if script else None, source_revision=revision(source) if source else None,
        transform_id=transform.id if transform else None, world_profile_id=profile_id,
        production_language=(transform.target_language_code if transform else
                             plan.target_language_code if plan and plan.target_language_code else
                             novel.source_language_code if novel else None),
        purpose=purpose, scope=Scope(
            kind="chapter" if row.kind == "plan" else "scene" if scenes else "shots" if shots else "custom",
            chapter_ids=[chapter_id] if chapter_id else [], scene_ids=scenes, shot_ids=shots),
        return_to=production.get("return_to"),
    )
    return ctx, issues


def assert_context(db: Session, supplied: ProductionContext) -> tuple[StudioBoard, ProductionContext]:
    row = board(db, supplied.board_id)
    current, _ = context_for(db, row)
    # Only explicitly supplied persistent fields are assertions. Selection is transient UI state.
    for key in supplied.model_fields_set - {"schema_version", "selection", "return_to", "board_id"}:
        if getattr(supplied, key) != getattr(current, key):
            raise ProductionError("context_stale", f"{key} 与画布当前上下文不一致，请刷新", 409)
    return row, current


def asset_data(asset: Asset) -> dict:
    digest = revision({"id": asset.id, "sha256": asset.sha256, "kind": asset.kind,
                       "mime": asset.mime, "meta": asset.meta_json,
                       "fallback_url": asset.url if not asset.sha256 else None})
    return {"id": asset.id, "revision": digest, "kind": asset.kind.value,
            "name": (asset.meta_json or {}).get("uploaded_as") or (asset.meta_json or {}).get("name") or asset.id,
            "media": {"asset_id": asset.id, "url": asset.url, "mime": asset.mime,
                      "metadata": asset.meta_json or {}},
            "provenance": {"source": asset.source.value, "gen_task_id": asset.gen_task_id,
                           "content_hash_available": bool(asset.sha256)}}


def entity_data(db: Session, entity: WorldEntity, transform_id: str | None = None) -> dict:
    name = None
    if transform_id:
        name = db.scalar(select(EntityWorldName).where(
            EntityWorldName.entity_id == entity.id, EntityWorldName.transform_id == transform_id,
            EntityWorldName.workspace_id == entity.workspace_id))
    return {"id": entity.id, "kind": entity.kind.value, "name": entity.display_name,
            "screen_name": name.target_name if name else None, "novel_id": entity.novel_id,
            "revision": revision({"id": entity.id, "version": entity.version,
                                  "appearance": entity.appearance, "visual_prompt": entity.visual_prompt,
                                  "refs": entity.ref_asset_ids, "summary": entity.summary,
                                  "voice": entity.voice_profile_json,
                                  "screen_name": name.target_name if name else None})}


def choose_epoch(db: Session, entity: WorldEntity, profile_id: str | None,
                 epoch_id: str | None = None, chapter_order: int | None = None,
                 *, lock: bool = False) -> AssetEpoch:
    if not profile_id:
        raise ProductionError("world_required", "请先选择表现世界观")
    profile = get(db, WorldProfile, profile_id, entity.workspace_id)
    if profile.novel_id not in (None, entity.novel_id):
        raise ProductionError("world_mismatch", "世界观与角色小说不一致")
    q = select(AssetEpoch).where(AssetEpoch.subject_key == entity.id,
                                AssetEpoch.entity_id == entity.id,
                                AssetEpoch.world_profile_id == profile_id,
                                AssetEpoch.workspace_id == entity.workspace_id)
    if epoch_id:
        q = q.where(AssetEpoch.id == epoch_id)
    elif chapter_order is not None:
        q = q.where(AssetEpoch.from_chapter_order <= chapter_order,
                    or_(AssetEpoch.to_chapter_order.is_(None), AssetEpoch.to_chapter_order >= chapter_order))
    rows = list(db.scalars(q.with_for_update() if lock else q))
    if not rows:
        raise ProductionError("epoch_missing", "该实体在此世界观下没有可用造型时期", 404)
    if len(rows) != 1:
        raise ProductionError("epoch_ambiguous", "多个造型时期可用，请明确指定 epoch_id", 409)
    return rows[0]


def pack_data(db: Session, entity: WorldEntity, epoch: AssetEpoch) -> dict:
    refs = epoch.reference_set_json or {}
    bindings = canonical_views(refs)
    ids = {v["asset_id"] for v in bindings.values()}
    legacy_sheet = (refs.get("views") or {}).get("sheet") or {}
    sheet_id = refs.get("canonical_sheet_asset_id") or legacy_sheet.get("asset_id")
    ids.update(i for i in (epoch.identity_ref_asset_id, sheet_id) if i)
    assets = {a.id: a for a in db.scalars(select(Asset).where(
        Asset.id.in_(ids), Asset.workspace_id == entity.workspace_id))} if ids else {}
    views, missing = {}, []
    for key in VIEW_KEYS:
        binding = bindings.get(key) or {}
        asset = assets.get(binding.get("asset_id"))
        if not asset or asset.kind != AssetKind.image or asset.novel_id not in (None, entity.novel_id):
            missing.append(key)
            continue
        views[key] = {"view_key": key, "asset_id": asset.id, **asset_data(asset),
                      "status": binding.get("status", "bound_unreviewed"), "legacy_key": binding.get("legacy_key"),
                      "side": binding.get("side", "unspecified"),
                      "source_refs": binding.get("source_refs", [])}
    def media(key):
        asset = assets.get(key)
        return asset_data(asset) if asset and asset.kind == AssetKind.image and asset.novel_id in (None, entity.novel_id) else None
    from app.stage.cards import infer_physical
    physical = refs.get("physical")
    if entity.kind == EntityKind.character and not (isinstance(physical, dict) and physical.get("source") == "user"):
        physical = infer_physical(entity.appearance, entity.summary, epoch.visual_prompt or entity.visual_prompt).model_dump()
    physical = physical or {"source": "missing"}
    data = {"id": epoch.id, "entity_id": entity.id, "entity_kind": entity.kind.value,
            "world_profile_id": epoch.world_profile_id, "epoch_id": epoch.id,
            "epoch_key": epoch.epoch_key, "identity_anchor": media(epoch.identity_ref_asset_id),
            "sheet": media(sheet_id), "views": views, "missing": missing,
            "physical": physical,
            "locked": epoch.locked, "review_status": epoch.status.value}
    # URLs may rotate; hash actual content revisions and reference bindings instead.
    data["revision"] = revision({"entity": entity_data(db, entity)["revision"],
                                 "epoch": epoch.id, "invariant": epoch.invariant_json,
                                 "variant": epoch.variant_json, "visual_prompt": epoch.visual_prompt,
                                 "negative_prompt": epoch.negative_prompt,
                                 "bindings": {k: {field: v.get(field) for field in ("asset_id", "side", "source_refs", "status")} for k, v in bindings.items()},
                                 "physical": physical,
                                 "sheet": data["sheet"]["revision"] if data["sheet"] else None,
                                 "anchor": data["identity_anchor"]["revision"] if data["identity_anchor"] else None,
                                 "views": {k: v["revision"] for k, v in views.items()}})
    data["issues"] = [{"code": "legacy_view_mapped", "from": v["legacy_key"], "to": key,
                       "status": v["status"]} for key, v in views.items() if v.get("legacy_key")]
    for key, view in views.items():
        view["asset_revision"] = view["revision"]
        view["id"] = f"{epoch.id}:{key}"
        view["revision"] = revision({"pack": data["revision"], "view": key, "asset": view["asset_revision"]})
    return data


def resolve_one(db: Session, row: StudioBoard, ctx: ProductionContext, ref: ResourceRef) -> dict:
    if ref.mode != "reference":
        raise ProductionError("mode_not_implemented", "当前批次只支持 reference；历史快照和派生尚未实现")
    if ref.binding.instance_id:
        raise ProductionError("instance_not_implemented", "实例覆盖将在舞台批次接入，不可忽略 instance_id")
    if ctx.world_profile_id and ref.binding.world_profile_id and ref.binding.world_profile_id != ctx.world_profile_id:
        raise ProductionError("world_mismatch", "素材引用与画布表现世界不一致")
    normalized = ref.model_dump()
    if ref.kind in {"stage", "coverage"}:
        from app.production.stage_resources import resolve
        data = resolve(db, row, ref)
    elif ref.kind in {"asset", "audio"}:
        asset = get(db, Asset, ref.id, row.workspace_id)
        if ctx.novel_id and asset.novel_id not in (None, ctx.novel_id):
            raise ProductionError("scope_mismatch", "素材不属于当前项目")
        if ref.kind == "audio" and asset.kind != AssetKind.audio:
            raise ProductionError("kind_mismatch", "audio 引用必须指向音频素材")
        if any((ref.binding.entity_id, ref.binding.epoch_id, ref.binding.view_key)):
            raise ProductionError("binding_not_supported", "有角色/造型绑定的图片请使用 canonical_view")
        data = {**asset_data(asset), "novel_id": asset.novel_id}
    elif ref.kind in {"entity", "variant", "canonical_pack", "canonical_view"}:
        entity_id = ref.id if ref.kind == "entity" else ref.binding.entity_id
        if not entity_id:
            raise ProductionError("entity_required", "标准包/视图引用需要 binding.entity_id")
        ent = get(db, WorldEntity, entity_id, row.workspace_id)
        if ctx.novel_id and ent.novel_id != ctx.novel_id:
            raise ProductionError("scope_mismatch", "实体不属于当前项目")
        if ref.kind == "entity":
            if ref.binding.entity_id not in (None, ent.id) or ref.binding.epoch_id or ref.binding.view_key:
                raise ProductionError("binding_mismatch", "实体引用的绑定与实体 ID 不一致")
            data = entity_data(db, ent, ctx.transform_id if ent.novel_id == ctx.novel_id else None)
            normalized["binding"].update(entity_id=ent.id, world_profile_id=ctx.world_profile_id)
        else:
            chapter = get(db, Chapter, ctx.chapter_id, row.workspace_id) if ctx.chapter_id else None
            # Unbound canvases keep each reference's original world/epoch. Do not
            # silently adopt the resource's novel or transform as the board's source.
            profile_id = ctx.world_profile_id or ref.binding.world_profile_id
            if not ctx.novel_id and not ref.binding.epoch_id:
                raise ProductionError("epoch_required", "自由画布引用标准包/视图时，请明确选择造型时期")
            ep = choose_epoch(db, ent, profile_id, ref.binding.epoch_id,
                              chapter.order_no if chapter else None)
            pack = pack_data(db, ent, ep)
            normalized["binding"].update(entity_id=ent.id, epoch_id=ep.id, world_profile_id=ep.world_profile_id)
            if ref.kind == "canonical_view":
                key = ALIASES.get(ref.binding.view_key, ref.binding.view_key)
                if key not in VIEW_KEYS:
                    raise ProductionError("view_invalid", "必须指定标准 view_key")
                if ref.id != f"{ep.id}:{key}":
                    raise ProductionError("binding_mismatch", "视图 ID 必须为 epoch_id:view_key")
                if key not in pack["views"]:
                    raise ProductionError("view_missing", f"缺少视图 {key}", 404)
                data = pack["views"][key]
                normalized["binding"]["view_key"] = key
            else:
                if ref.id != ep.id or ref.binding.view_key:
                    raise ProductionError("binding_mismatch", "包/造型 ID 必须与 epoch_id 一致，不能携带 view_key")
                data = pack
    else:
        raise ProductionError("kind_not_implemented", f"{ref.kind} 将在后续批次接入")
    if ref.revision and ref.revision != data["revision"]:
        raise ProductionError("revision_conflict", "资源版本已改变；保留原引用并由用户选择刷新", 409)
    normalized["revision"] = data["revision"]
    return {"ref": normalized, "status": "resolved", "resource": data, "issues": []}


def bind_pack(db: Session, entity: WorldEntity, epoch: AssetEpoch, body) -> dict:
    if entity.kind != EntityKind.character:
        raise ProductionError("kind_not_supported", "16 格标准包目前适用于角色")
    if epoch.locked:
        raise ProductionError("pack_locked", "当前造型时期已锁定，请先在造型管理中明确解除锁定", 409)
    if body.base_revision != pack_data(db, entity, epoch)["revision"]:
        raise ProductionError("revision_conflict", "标准包已变化，请刷新后重新绑定", 409)
    mapped = {}
    for raw_key, aid in body.views.items():
        key = ALIASES.get(raw_key, raw_key)
        if key not in VIEW_KEYS or key in mapped:
            raise ProductionError("view_invalid", f"无效或重复的视图键：{raw_key}")
        mapped[key] = aid
    ids = list(mapped.values())
    if len(set(ids)) != len(ids):
        raise ProductionError("duplicate_view_asset", "每一格需要独立素材，不能用同一张拼版代替多个视角")
    if body.sheet_asset_id and body.sheet_asset_id in ids:
        raise ProductionError("sheet_used_as_view", "展示拼版不能兼作单格素材")
    for aid in [*ids, *([body.sheet_asset_id] if body.sheet_asset_id else [])]:
        asset = get(db, Asset, aid, entity.workspace_id)
        if asset.kind != AssetKind.image or asset.novel_id not in (None, entity.novel_id):
            raise ProductionError("asset_binding_invalid", "角色视图必须是当前项目或共享库的图片")
    refs = dict(epoch.reference_set_json or {})
    views = dict(refs.get("canonical_views") or {})
    # Existing unaffected panels and identity anchor remain intact.
    for key, aid in mapped.items():
        views[key] = {"asset_id": aid, "status": "bound_unreviewed", "source_refs": []}
    merged = canonical_views({**refs, "canonical_views": views})
    merged_ids = [p["asset_id"] for p in merged.values()]
    if len(set(merged_ids)) != len(merged_ids):
        raise ProductionError("duplicate_view_asset", "新视图与已有格引用同一素材，请使用独立单格图片")
    refs["canonical_views"] = views
    if body.sheet_asset_id:
        refs["canonical_sheet_asset_id"] = body.sheet_asset_id
    epoch.reference_set_json = refs
    db.flush()
    return pack_data(db, entity, epoch)
