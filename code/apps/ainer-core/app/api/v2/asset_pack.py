"""基础素材包 API：抽离 → 世界观变体 → 完整度 → 审核。

依赖方向单向：素材包是画面生成的唯一真源，分镜只引用不描述。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.ids import new_id
from app.models import (
    AssetKindSpec, AssetOrigin, AssetSpec, AssetVariant, Chapter, DirectorProfile,
    ReviewStatus, WorldProfile, WorldTransform,
)
from app.pipelines import asset_pack as pack
from app.pipelines.base import PipelineError
from app.worldview.asset_requirements import requirements_for

router = APIRouter(prefix="/api/v2", tags=["asset-pack"])


def _transform(db: Session, tid: str) -> WorldTransform:
    t = db.get(WorldTransform, tid)
    if t is None:
        raise HTTPException(status_code=404, detail="transform not found")
    return t


def _spec_out(s: AssetSpec, v: AssetVariant | None = None) -> dict:
    return {
        "id": s.id, "kind": s.kind.value, "canonical_key": s.canonical_key,
        "display_name": s.display_name, "aliases": s.aliases_json or [],
        "summary": s.summary, "entity_id": s.entity_id,
        "importance": s.importance, "source": s.source.value,
        "evidence": s.evidence_json or {},
        "variant": None if v is None else {
            "id": v.id, "target_name": v.target_name,
            "target_reading": v.target_reading,
            "visual_prompt": v.visual_prompt, "negative_prompt": v.negative_prompt,
            "structured": v.structured_json or {},
            "ref_asset_ids": v.ref_asset_ids or [],
            "status": v.status.value, "missing_fields": v.missing_fields or [],
            "confidence": v.confidence, "rationale": v.rationale,
        },
    }


# ── 抽离 ──────────────────────────────────────────────────────────────────────

@router.post("/chapters/{chapter_id}/assets:extract")
def extract_assets(chapter_id: str, min_importance: int = Query(2, ge=1, le=5),
                   db: Session = Depends(get_db)) -> dict:
    """从章节抽离基础素材。幂等 —— 小说更新后重跑只补新的，不动已有的。"""
    c = db.get(Chapter, chapter_id)
    if c is None:
        raise HTTPException(status_code=404, detail="chapter not found")
    try:
        return pack.extract_assets(db, c, min_importance=min_importance).as_dict()
    except PipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/novels/{novel_id}/assets")
def list_assets(
    novel_id: str,
    kind: str | None = Query(None),
    profile_id: str | None = Query(None, description="带上则一并返回该世界观下的变体"),
    status: str | None = Query(None),
    missing_only: bool = Query(False, description="只看缺变体或字段不全的"),
    db: Session = Depends(get_db),
) -> list[dict]:
    q = select(AssetSpec).where(AssetSpec.novel_id == novel_id)
    if kind:
        q = q.where(AssetSpec.kind == AssetKindSpec(kind))
    specs = list(
        db.execute(q.order_by(AssetSpec.kind, AssetSpec.importance.desc())).scalars()
    )

    variants: dict[str, AssetVariant] = {}
    if profile_id:
        variants = {
            v.asset_spec_id: v
            for v in db.execute(
                select(AssetVariant).where(
                    AssetVariant.world_profile_id == profile_id,
                    AssetVariant.asset_spec_id.in_([s.id for s in specs]),
                )
            ).scalars()
        }

    out = []
    for s in specs:
        v = variants.get(s.id)
        if status and (v is None or v.status.value != status):
            continue
        if missing_only and v is not None and not v.missing_fields:
            continue
        out.append(_spec_out(s, v))
    return out


class SpecIn(BaseModel):
    kind: AssetKindSpec
    canonical_key: str
    display_name: str
    aliases: list[str] = Field(default_factory=list)
    summary: str | None = None
    entity_id: str | None = None
    importance: int = 3


@router.post("/novels/{novel_id}/assets", status_code=201)
def create_asset(novel_id: str, body: SpecIn, db: Session = Depends(get_db)) -> dict:
    dup = db.execute(
        select(AssetSpec).where(
            AssetSpec.novel_id == novel_id,
            AssetSpec.canonical_key == body.canonical_key,
        )
    ).scalars().first()
    if dup:
        raise HTTPException(status_code=409,
                            detail=f"canonical_key {body.canonical_key} 已存在")
    s = AssetSpec(
        id=new_id("as"), novel_id=novel_id, kind=body.kind,
        canonical_key=body.canonical_key, display_name=body.display_name,
        aliases_json=body.aliases, summary=body.summary,
        entity_id=body.entity_id, importance=body.importance,
        source=AssetOrigin.manual,
    )
    db.add(s)
    db.flush()
    return _spec_out(s)


@router.delete("/assets/{spec_id}", status_code=204)
def delete_asset(spec_id: str, db: Session = Depends(get_db)) -> None:
    s = db.get(AssetSpec, spec_id)
    if s is None:
        raise HTTPException(status_code=404, detail="asset not found")
    locked = db.execute(
        select(AssetVariant).where(
            AssetVariant.asset_spec_id == spec_id,
            AssetVariant.status == ReviewStatus.locked,
        )
    ).scalars().first()
    if locked:
        raise HTTPException(status_code=409, detail="该素材有已锁定的世界观变体，不能删除")
    db.delete(s)


# ── 世界观变体 ────────────────────────────────────────────────────────────────

class EnsureIn(BaseModel):
    asset_ids: list[str] = Field(default_factory=list)
    only_missing: bool = True
    batch: int = 12


@router.post("/transforms/{transform_id}/assets:ensure-variants")
def ensure_variants(transform_id: str, body: EnsureIn,
                    db: Session = Depends(get_db)) -> dict:
    """确保素材在目标世界观下都有变体，缺什么按当前标准补什么。

    这是常态操作而非一次性初始化 —— 小说在更新、抽取会不全，
    每次编译分镜前调一次。已锁定的变体一律不动。
    """
    t = _transform(db, transform_id)
    try:
        return pack.ensure_variants(
            db, t, asset_ids=body.asset_ids or None,
            only_missing=body.only_missing, batch=body.batch,
        ).as_dict()
    except PipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/transforms/{transform_id}/asset-pack")
def get_pack_status(transform_id: str, db: Session = Depends(get_db)) -> dict:
    """基础素材包完整度总览。分镜编译前看这一屏。"""
    return pack.pack_status(db, _transform(db, transform_id))


class EpochIn(BaseModel):
    epoch_key: str
    display_name: str
    kind: str = "age"
    from_chapter_order: int = 1
    to_chapter_order: int | None = None
    order_no: int = 0
    trigger: str | None = None
    invariant: dict = Field(default_factory=dict)
    variant: dict = Field(default_factory=dict)
    identity_ref_asset_id: str | None = None


@router.get("/transforms/{transform_id}/assets/{spec_id}/epochs")
def list_epochs(transform_id: str, spec_id: str,
                db: Session = Depends(get_db)) -> dict:
    """一个素材的全部时期。

    人物是沿时间变的：少年林凡与中年林凡不是同一套衣着兵器。
    而固定物体（老家、祖传的刀）只有一期、覆盖全书 ——
    「探访故乡」那一镜才会与二十章前是同一个院子。
    """
    from app.models import AssetEpoch, AssetSpec

    t = _transform(db, transform_id)
    spec = db.get(AssetSpec, spec_id)
    if spec is None:
        raise HTTPException(status_code=404, detail="asset spec not found")
    rows = list(db.execute(
        select(AssetEpoch).where(
            AssetEpoch.subject_key == spec_id,
            AssetEpoch.world_profile_id == t.target_profile_id,
        ).order_by(AssetEpoch.order_no, AssetEpoch.from_chapter_order)
    ).scalars())
    return {
        "spec_id": spec_id, "name": spec.display_name, "kind": spec.kind.value,
        "total": len(rows),
        "items": [
            {
                "id": e.id, "epoch_key": e.epoch_key,
                "display_name": e.display_name, "kind": e.kind.value,
                "order_no": e.order_no,
                "from_chapter_order": e.from_chapter_order,
                "to_chapter_order": e.to_chapter_order,
                "trigger": e.trigger,
                "invariant": e.invariant_json or {},
                "variant": e.variant_json or {},
                "visual_prompt": e.visual_prompt,
                "identity_ref_asset_id": e.identity_ref_asset_id,
                "status": e.status.value, "locked": e.locked,
            }
            for e in rows
        ],
    }


@router.post("/transforms/{transform_id}/assets/{spec_id}/epochs", status_code=201)
def create_epoch(transform_id: str, spec_id: str, body: EpochIn,
                 db: Session = Depends(get_db)) -> dict:
    """新增一个时期。

    identity_ref_asset_id 应跨期共用同一张 ——
    换了脸参考图，脸就会跟着漂，而那正是分期最该守住的东西。
    """
    from app.models import AssetEpoch, AssetSpec, EpochKind
    from app.pipelines.epochs import compose_epoch_prompt

    t = _transform(db, transform_id)
    spec = db.get(AssetSpec, spec_id)
    if spec is None:
        raise HTTPException(status_code=404, detail="asset spec not found")
    try:
        kind = EpochKind(body.kind)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"未知时期类型 {body.kind}") from exc

    row = AssetEpoch(
        id=new_id("ae"), subject_key=spec_id, asset_spec_id=spec_id,
        world_profile_id=t.target_profile_id,
        epoch_key=body.epoch_key, display_name=body.display_name,
        kind=kind, order_no=body.order_no,
        from_chapter_order=body.from_chapter_order,
        to_chapter_order=body.to_chapter_order,
        trigger=body.trigger,
        invariant_json=body.invariant or None,
        variant_json=body.variant or None,
        identity_ref_asset_id=body.identity_ref_asset_id,
    )
    row.visual_prompt = compose_epoch_prompt(row, spec.kind.value)
    db.add(row)
    db.flush()
    return {"id": row.id, "epoch_key": row.epoch_key,
            "visual_prompt": row.visual_prompt}


@router.post("/transforms/{transform_id}/epochs:seed-baseline")
def seed_baselines(transform_id: str, db: Session = Depends(get_db)) -> dict:
    """把已有的基准形态迁成第一期。

    存量素材都只有一个形态。要求全部重填时期不现实，
    所以先收成 baseline 覆盖全书 —— 需要分期的再往上加，
    不需要的（老家、祖传的刀）就此打住。
    """
    from app.models import AssetSpec, AssetVariant
    from app.pipelines.epochs import seed_baseline_epoch

    t = _transform(db, transform_id)
    rows = list(db.execute(
        select(AssetSpec, AssetVariant)
        .join(AssetVariant, AssetVariant.asset_spec_id == AssetSpec.id)
        .where(
            AssetSpec.novel_id == t.novel_id,
            AssetVariant.world_profile_id == t.target_profile_id,
        )
    ))
    n = 0
    for spec, var in rows:
        seed_baseline_epoch(db, spec, var, spec.kind.value)
        n += 1
    return {"seeded": n}


@router.get("/transforms/{transform_id}/prompt-ledger")
def prompt_ledger(transform_id: str, kind: str | None = None,
                  q: str | None = None, db: Session = Depends(get_db)) -> dict:
    """生图提示词台账。

    提示词散在各条素材里就等于没有：改一条之前必须知道它影响哪些镜头，
    否则是盲改 —— 一个道具的描述改了，可能连带十几个镜头的画面全变。
    台账把「提示词本身 / 依据的原文 / 被谁引用」拼在一起。
    """
    return pack.prompt_ledger(db, _transform(db, transform_id), kind=kind, q=q)


@router.get("/transforms/{transform_id}/prompt-ledger/export")
def export_prompt_ledger(transform_id: str, db: Session = Depends(get_db)):
    """导出为纯文本，便于存档比对或贴进别的工具。"""
    from fastapi.responses import PlainTextResponse

    text = pack.export_prompts(db, _transform(db, transform_id))
    return PlainTextResponse(text, headers={
        "Content-Disposition": f'attachment; filename="prompts-{transform_id}.md"'
    })


class VariantPatch(BaseModel):
    target_name: str | None = None
    target_reading: str | None = None
    visual_prompt: str | None = None
    negative_prompt: str | None = None
    structured: dict | None = None
    ref_asset_ids: list[str] | None = None


@router.patch("/asset-variants/{variant_id}")
def update_variant(variant_id: str, body: VariantPatch,
                   db: Session = Depends(get_db)) -> dict:
    from app.worldview.asset_requirements import check_completeness

    v = db.get(AssetVariant, variant_id)
    if v is None:
        raise HTTPException(status_code=404, detail="variant not found")
    if v.status == ReviewStatus.locked:
        raise HTTPException(status_code=409, detail="变体已锁定，请先解锁")

    for f in ("target_name", "target_reading", "visual_prompt", "negative_prompt"):
        val = getattr(body, f)
        if val is not None:
            setattr(v, f, val)
    if body.structured is not None:
        v.structured_json = body.structured
    if body.ref_asset_ids is not None:
        v.ref_asset_ids = body.ref_asset_ids

    spec = db.get(AssetSpec, v.asset_spec_id)
    profile = db.get(WorldProfile, v.world_profile_id)
    v.missing_fields = check_completeness(spec.kind.value, v.structured_json, profile)
    v.source = AssetOrigin.manual
    db.flush()
    return _spec_out(spec, v)


@router.post("/asset-variants/{variant_id}:approve")
def approve_variant(variant_id: str, db: Session = Depends(get_db)) -> dict:
    v = db.get(AssetVariant, variant_id)
    if v is None:
        raise HTTPException(status_code=404, detail="variant not found")
    if v.missing_fields:
        raise HTTPException(
            status_code=422,
            detail=f"结构化字段不全，缺 {v.missing_fields}，补齐后才能通过审核",
        )
    v.status = ReviewStatus.approved
    db.flush()
    return {"id": v.id, "status": v.status.value}


@router.post("/asset-variants/{variant_id}:lock")
def lock_variant(variant_id: str, db: Session = Depends(get_db)) -> dict:
    v = db.get(AssetVariant, variant_id)
    if v is None:
        raise HTTPException(status_code=404, detail="variant not found")
    if v.missing_fields:
        raise HTTPException(status_code=422, detail=f"字段不全：缺 {v.missing_fields}")
    v.status = ReviewStatus.locked
    db.flush()
    return {"id": v.id, "status": v.status.value}


class BatchIds(BaseModel):
    ids: list[str]


@router.post("/transforms/{transform_id}/asset-variants:batch-approve")
def batch_approve(transform_id: str, body: BatchIds,
                  db: Session = Depends(get_db)) -> dict:
    rows = db.execute(
        select(AssetVariant).where(AssetVariant.id.in_(body.ids))
    ).scalars().all()
    ok = skipped = 0
    for v in rows:
        if v.missing_fields or v.status == ReviewStatus.locked:
            skipped += 1
            continue
        v.status = ReviewStatus.approved
        ok += 1
    db.flush()
    return {"approved": ok, "skipped": skipped}


@router.get("/asset-requirements")
def get_requirements(kind: str | None = Query(None),
                     profile_id: str | None = Query(None),
                     db: Session = Depends(get_db)) -> dict:
    """各类素材的必填结构化字段。前端据此渲染编辑表单。"""
    profile = db.get(WorldProfile, profile_id) if profile_id else None
    kinds = [kind] if kind else [k.value for k in AssetKindSpec]
    return {k: requirements_for(k, profile) for k in kinds}


# ── 导演包 ────────────────────────────────────────────────────────────────────

@router.get("/director-profiles")
def list_directors(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(
        select(DirectorProfile).where(DirectorProfile.status == "active")
        .order_by(DirectorProfile.code)
    ).scalars()
    return [
        {
            "id": d.id, "code": d.code, "display_name": d.display_name,
            "summary": d.summary, "camera": d.camera_json or {},
            "editing": d.editing_json or {}, "composition": d.composition_json or {},
            "lighting": d.lighting_json or {}, "avoid": d.avoid_json or [],
            "kb_collection_id": d.kb_collection_id, "version": d.version,
        }
        for d in rows
    ]


class DirectorIn(BaseModel):
    code: str
    display_name: str
    summary: str | None = None
    parent_id: str | None = None
    novel_id: str | None = None
    camera: dict = Field(default_factory=dict)
    editing: dict = Field(default_factory=dict)
    composition: dict = Field(default_factory=dict)
    lighting: dict = Field(default_factory=dict)
    avoid: list[str] = Field(default_factory=list)
    kb_collection_id: str | None = None


@router.post("/director-profiles", status_code=201)
def create_director(body: DirectorIn, db: Session = Depends(get_db)) -> dict:
    d = DirectorProfile(
        id=new_id("dp"), code=body.code, display_name=body.display_name,
        summary=body.summary, parent_id=body.parent_id, novel_id=body.novel_id,
        camera_json=body.camera, editing_json=body.editing,
        composition_json=body.composition, lighting_json=body.lighting,
        avoid_json=body.avoid, kb_collection_id=body.kb_collection_id,
        version=1, status="active",
    )
    db.add(d)
    db.flush()
    return {"id": d.id, "code": d.code, "display_name": d.display_name}


@router.post("/director-profiles/{director_id}:fork", status_code=201)
def fork_director(director_id: str, code: str = Query(...),
                  display_name: str = Query(...),
                  db: Session = Depends(get_db)) -> dict:
    parent = db.get(DirectorProfile, director_id)
    if parent is None:
        raise HTTPException(status_code=404, detail="director profile not found")
    d = DirectorProfile(
        id=new_id("dp"), code=code, display_name=display_name,
        summary=f"派生自 {parent.display_name}", parent_id=parent.id,
        novel_id=parent.novel_id,
        camera_json=dict(parent.camera_json or {}),
        editing_json=dict(parent.editing_json or {}),
        composition_json=dict(parent.composition_json or {}),
        lighting_json=dict(parent.lighting_json or {}),
        avoid_json=list(parent.avoid_json or []),
        version=1, status="active",
    )
    db.add(d)
    db.flush()
    return {"id": d.id, "code": d.code, "display_name": d.display_name,
            "parent_id": parent.id}


# ── 人物时期 ──────────────────────────────────────────────────────────────────

class MineEpochsIn(BaseModel):
    entity_ids: list[str] = Field(default_factory=list)
    force: bool = False


@router.post("/novels/{novel_id}/entity-epochs:mine")
def mine_entity_epochs(novel_id: str, profile_id: str = Query(...),
                       body: MineEpochsIn | None = None,
                       db: Session = Depends(get_db)) -> dict:
    """给主要角色划时期。

    脸跨期不变、衣着兵器随期变 —— 这是整套时期设计的初衷，
    而人物一度是唯一挂不上的主体。
    """
    from app.models import WorldProfile
    from app.pipelines import entity_epochs

    profile = db.get(WorldProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="world profile not found")
    body = body or MineEpochsIn()
    try:
        return entity_epochs.mine_entity_epochs(
            db, novel_id, profile,
            entity_ids=body.entity_ids or None, force=body.force,
        ).as_dict()
    except PipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/novels/{novel_id}/entity-epochs")
def list_entity_epochs(novel_id: str, profile_id: str = Query(...),
                       db: Session = Depends(get_db)) -> dict:
    """全书人物的时期表 + 体检。

    体检查的与规则层同一套：区间有没有缺口、不变项跨期一致不一致、
    分界有没有依据。**把没能检查的也报出来** —— 与场记同一条规矩。
    """
    from app.models import (
        INVARIANT_FIELDS, AssetEpoch, Chapter, EntityKind, WorldEntity,
        WorldProfile,
    )
    from app.pipelines.epochs import compose_epoch_prompt
    from app.worldview.epoch_rules import (
        EpochDraft, check_shared_marks, check_spans, check_triggers,
    )

    profile = db.get(WorldProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="world profile not found")

    chapters = list(db.execute(
        select(Chapter.order_no).where(Chapter.novel_id == novel_id)
    ).scalars())
    total = max(chapters) if chapters else 0
    ents = {
        e.id: e for e in db.execute(
            select(WorldEntity).where(
                WorldEntity.novel_id == novel_id,
                WorldEntity.kind == EntityKind.character,
            )
        ).scalars()
    }
    rows = list(db.execute(
        select(AssetEpoch).where(
            AssetEpoch.world_profile_id == profile_id,
            AssetEpoch.entity_id.in_(list(ents)),
        ).order_by(AssetEpoch.subject_key, AssetEpoch.from_chapter_order)
    ).scalars()) if ents else []

    by_entity: dict[str, list] = {}
    for r in rows:
        by_entity.setdefault(r.entity_id, []).append(r)

    items, issues = [], []
    for eid, group in by_entity.items():
        ent = ents[eid]
        drafts = [
            EpochDraft(
                epoch_key=r.epoch_key, display_name=r.display_name,
                kind=r.kind.value, from_chapter_order=r.from_chapter_order,
                to_chapter_order=r.to_chapter_order, trigger=r.trigger or "",
                invariant=r.invariant_json or {}, variant=r.variant_json or {},
            ) for r in group
        ]
        # 落库后仍要复查：区间可能被人工改出缺口
        prev_end = 0
        for dft in drafts:
            if dft.from_chapter_order != prev_end + 1:
                issues.append({
                    "type": "gap" if dft.from_chapter_order > prev_end + 1
                            else "overlap",
                    "entity": ent.display_name, "epoch": dft.epoch_key,
                    "detail": f"「{dft.display_name}」从第 {dft.from_chapter_order} "
                              f"章起，上一期到第 {prev_end} 章",
                })
            prev_end = (dft.to_chapter_order if dft.to_chapter_order is not None
                        else total)
        anchor = drafts[0].invariant if drafts else {}
        for dft in drafts[1:]:
            for f in INVARIANT_FIELDS["character"]:
                a, b = str(anchor.get(f) or ""), str(dft.invariant.get(f) or "")
                if a and b and a != b:
                    issues.append({
                        "type": "invariant_drift", "entity": ent.display_name,
                        "epoch": dft.epoch_key,
                        "detail": f"「{f}」在「{dft.display_name}」是「{b}」，"
                                  f"第一期是「{a}」—— 不变项漂了，脸会跟着漂",
                    })
        for note in check_triggers(drafts) + check_spans(drafts, total):
            note["entity"] = ent.display_name
            issues.append(note)

        anchors = {r.identity_ref_asset_id for r in group
                   if r.identity_ref_asset_id}
        if len(anchors) > 1:
            issues.append({
                "type": "ref_split", "entity": ent.display_name,
                "detail": "各期用了不同的脸参考图 —— 换了参考图，脸就跟着漂",
            })

        items.append({
            "entity_id": eid, "name": ent.display_name,
            "appear_chapters": len(ent.appear_chapters_json or []),
            "identity_ref": next(iter(anchors), None),
            "invariant": anchor,
            "epochs": [
                {
                    "id": r.id, "epoch_key": r.epoch_key,
                    "display_name": r.display_name, "kind": r.kind.value,
                    "from_chapter_order": r.from_chapter_order,
                    "to_chapter_order": r.to_chapter_order,
                    "trigger": r.trigger, "variant": r.variant_json or {},
                    "prompt": r.visual_prompt or compose_epoch_prompt(r, "character"),
                    "rationale": r.rationale,
                    "status": r.status.value, "locked": r.locked,
                } for r in group
            ],
        })
    # 辨识特征撞了 —— 撞声的视觉版，同样只有放到一起才看得出
    issues.extend(check_shared_marks(
        {i["name"]: i["invariant"] for i in items if i["invariant"]}))
    items.sort(key=lambda i: (-i["appear_chapters"], i["name"]))

    not_checked = []
    uncast = [e.display_name for e in ents.values() if e.id not in by_entity]
    if not total:
        not_checked.append("这本书没有章节，区间覆盖无法检查")
    if not any(i["identity_ref"] for i in items):
        not_checked.append(
            "还没有任何角色的脸参考图 —— 跨期同一性目前只靠文字描述，"
            "生成参考图后才谈得上真正锁住")

    return {
        "total_chapters": total, "entities": len(items),
        "epochs": len(rows), "items": items,
        "issues": issues, "without_epochs": uncast,
        "not_checked": not_checked,
    }
