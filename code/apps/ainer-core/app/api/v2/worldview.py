"""世界观转译 API：档案 / 映射 / 名物词表 / 人名 / 违规 / 门禁。"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.ids import new_id
from app.models import (
    EntityWorldName, LexiconCategory, LexiconSource, Novel, ReviewStatus, Severity,
    ViolationStatus, WorldEntity, WorldLexicon, WorldLexiconTemplate, WorldProfile,
    WorldTransform, WorldViolation,
)
from app.models.world import NamingPolicy, ProfileRole, ProfileStatus, TransformStatus
from app.worldview import naming, preflight as pf, survey

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2", tags=["worldview"])


# ── 档案 ──────────────────────────────────────────────────────────────────────

class ProfileIn(BaseModel):
    code: str
    display_name: str
    role: ProfileRole = ProfileRole.both
    novel_id: str | None = None
    parent_id: str | None = None
    #: 虚构圈层（未来、修真界、异世界），不是任何现实文化
    is_fictional: bool = False
    #: 虚构圈层的语言与常识底座，指向一个现实圈层。虚构圈层必填 ——
    #: 读者是现实里的人，不知道这些人该怎么说话、一里有多远
    base_profile_id: str | None = None
    axes: dict = Field(default_factory=dict)
    visual: dict = Field(default_factory=dict)
    language: dict = Field(default_factory=dict)
    description: str | None = None


def _profile_out(p: WorldProfile) -> dict:
    return {
        "id": p.id, "code": p.code, "display_name": p.display_name,
        "role": p.role.value, "novel_id": p.novel_id, "parent_id": p.parent_id,
        "is_fictional": bool(p.is_fictional),
        "base_profile_id": p.base_profile_id,
        "axes": p.axes_json or {}, "visual": p.visual_json or {},
        "language": p.language_json or {}, "version": p.version,
        "status": p.status.value, "description": p.description,
    }


@router.post("/worldview:seed")
def seed_assets(db: Session = Depends(get_db)) -> dict:
    """幂等写入内置世界观档案与三对预置词表，解决冷启动。"""
    return survey.seed_defaults(db)


@router.get("/languages")
def list_languages(db: Session = Depends(get_db)) -> dict:
    """可选的目标语言。

    **世界观与语言是两个维度，不该绑死。** 档案的 language.code 只是默认值：
    同一个「维多利亚英国」世界观，可能要出 en-GB 给英国读者、
    也可能出 en-US 给美国读者；「昭和日本」的译本可能是 ja-JP，
    也可能是给在日华人看的 zh-CN。写死就少了这一层自由。

    列表来自两处的并集：已建档案实际用到的语言（带各自的圈层数），
    加上命名验证支持的全部语言 —— 后者能保证选了它至少校验不会崩。
    """
    from app.worldview.naming import _FALLBACK_POOLS, _LANG_SCRIPTS

    rows = list(db.execute(select(WorldProfile).where(
        WorldProfile.status == ProfileStatus.active)).scalars())
    by_code: dict[str, dict] = {}
    for p in rows:
        code = (p.language_json or {}).get("code")
        if not code:
            continue
        slot = by_code.setdefault(code, {
            "code": code, "profiles": 0, "examples": [],
            "name_pattern": (p.language_json or {}).get("name_pattern"),
            "script": (p.language_json or {}).get("name_script"),
        })
        slot["profiles"] += 1
        if len(slot["examples"]) < 4:
            slot["examples"].append(p.display_name)

    # 补上有档案但没圈层的语言变体，以及命名层支持的基础语言
    for base in sorted(_LANG_SCRIPTS):
        if not any(c.split("-")[0] == base for c in by_code):
            by_code.setdefault(base, {
                "code": base, "profiles": 0, "examples": [],
                "name_pattern": None, "script": _LANG_SCRIPTS[base][0],
            })

    items = sorted(by_code.values(), key=lambda x: (-x["profiles"], x["code"]))
    for it in items:
        base = it["code"].split("-")[0].lower()
        # 没有兜底姓名池的语言仍可选，但命名失败时无法自动兜底，
        # 需要人工指定 —— 这一点必须让用户在选之前就知道
        it["has_fallback_pool"] = base in _FALLBACK_POOLS
        it["script"] = it.get("script") or (_LANG_SCRIPTS.get(base) or ("latin",))[0]
    return {"total": len(items), "items": items}


@router.get("/world-profiles")
def list_profiles(role: str | None = Query(None), novel_id: str | None = Query(None),
                  db: Session = Depends(get_db)) -> list[dict]:
    q = select(WorldProfile).where(WorldProfile.status != ProfileStatus.archived)
    if role:
        q = q.where(WorldProfile.role.in_([ProfileRole(role), ProfileRole.both]))
    if novel_id:
        q = q.where((WorldProfile.novel_id == novel_id) | (WorldProfile.novel_id.is_(None)))
    return [_profile_out(p) for p in db.execute(q.order_by(WorldProfile.code)).scalars()]


@router.post("/world-profiles", status_code=201)
def create_profile(body: ProfileIn, db: Session = Depends(get_db)) -> dict:
    p = WorldProfile(
        id=new_id("wp"), code=body.code, display_name=body.display_name, role=body.role,
        novel_id=body.novel_id, parent_id=body.parent_id,
        is_fictional=body.is_fictional, base_profile_id=body.base_profile_id,
        axes_json=body.axes,
        visual_json=body.visual, language_json=body.language, version=1,
        status=ProfileStatus.active, description=body.description,
    )
    if body.is_fictional and not body.base_profile_id:
        raise HTTPException(
            status_code=422,
            detail="虚构圈层必须挂一个现实圈层作语言与常识底座 —— "
                   "读者是现实里的人，不知道这些人该怎么说话、一里有多远、"
                   "什么算礼貌。写给谁读就挂谁")
    db.add(p)
    db.flush()
    return _profile_out(p)


@router.post("/world-profiles/{profile_id}:fork", status_code=201)
def fork_profile(profile_id: str, code: str = Query(...), display_name: str = Query(...),
                 db: Session = Depends(get_db)) -> dict:
    """基于父档案派生。昭和·乡村只需覆写差异项，其余继承昭和。"""
    parent = db.get(WorldProfile, profile_id)
    if parent is None:
        raise HTTPException(status_code=404, detail="profile not found")
    p = WorldProfile(
        id=new_id("wp"), code=code, display_name=display_name, role=parent.role,
        novel_id=parent.novel_id, parent_id=parent.id,
        axes_json=dict(parent.axes_json or {}), visual_json=dict(parent.visual_json or {}),
        language_json=dict(parent.language_json or {}), version=1,
        status=ProfileStatus.draft, description=f"派生自 {parent.display_name}",
    )
    db.add(p)
    db.flush()
    return _profile_out(p)


@router.patch("/world-profiles/{profile_id}")
def update_profile(profile_id: str, body: ProfileIn, db: Session = Depends(get_db)) -> dict:
    p = db.get(WorldProfile, profile_id)
    if p is None:
        raise HTTPException(status_code=404, detail="profile not found")
    p.display_name = body.display_name
    p.role = body.role
    p.axes_json = body.axes
    p.visual_json = body.visual
    p.language_json = body.language
    p.description = body.description
    db.flush()
    return _profile_out(p)


# ── 映射 ──────────────────────────────────────────────────────────────────────

class TransformIn(BaseModel):
    #: 不填则取目标圈层的语言 —— 圈层已经决定了语言，
    #: 帝俄晚期就是俄语，摄政英国就是英式英语。
    #: 同语言的不同变体（en-GB／en-US）也已由圈层分开。
    target_language_code: str | None = None
    source_profile_id: str
    target_profile_id: str
    policy: dict = Field(default_factory=lambda: {
        "naming_policy": "cultural_equivalent",
        "honorific_policy": "map",
        "lexicon_policy": "strict",
        "preserve_original_for": [],
        "strictness": "strict",
    })


def _transform_out(t: WorldTransform, db: Session) -> dict:
    src = db.get(WorldProfile, t.source_profile_id)
    tgt = db.get(WorldProfile, t.target_profile_id)
    return {
        "id": t.id, "novel_id": t.novel_id,
        "target_language_code": t.target_language_code,
        "source": {"id": src.id, "code": src.code, "display_name": src.display_name},
        "target": {"id": tgt.id, "code": tgt.code, "display_name": tgt.display_name,
                   "axes": tgt.axes_json or {}},
        "version": t.version, "status": t.status.value, "policy": t.policy_json or {},
    }


@router.get("/novels/{novel_id}/transforms")
def list_transforms(novel_id: str, db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(
        select(WorldTransform).where(WorldTransform.novel_id == novel_id)
        .order_by(WorldTransform.target_language_code, WorldTransform.version.desc())
    ).scalars()
    return [_transform_out(t, db) for t in rows]


@router.post("/novels/{novel_id}/transforms", status_code=201)
def create_transform(novel_id: str, body: TransformIn, db: Session = Depends(get_db)) -> dict:
    if db.get(Novel, novel_id) is None:
        raise HTTPException(status_code=404, detail="novel not found")
    for pid in (body.source_profile_id, body.target_profile_id):
        if db.get(WorldProfile, pid) is None:
            raise HTTPException(status_code=400, detail=f"world profile {pid} not found")

    tgt_profile = db.get(WorldProfile, body.target_profile_id)
    profile_lang = (tgt_profile.language_json or {}).get("code")
    lang = body.target_language_code or profile_lang
    if not lang:
        raise HTTPException(
            status_code=400,
            detail=f"目标圈层 {tgt_profile.code} 的档案没有 language.code，"
                   f"请显式指定 target_language_code",
        )

    # 语言与圈层不一致是允许的，但只服务一种情况：
    # 成品语言与世界观语言确实不同（武侠改编到帝俄背景、写给中文读者）。
    # 除此之外都是配错了，而配错的后果很硬：命名按目标语言的书写系统校验，
    # 名物词表却是按圈层挖的，两条线各说各话。所以记一条警告到 policy 里，
    # 让它跟着这个映射走，而不是只在创建时闪一下。
    mismatch = bool(
        profile_lang and lang.split("-")[0] != profile_lang.split("-")[0]
    )
    policy = dict(body.policy)
    if mismatch:
        policy["language_override"] = {
            "profile_language": profile_lang,
            "chosen": lang,
            "note": "成品语言与世界观语言不同。命名按成品语言的书写系统校验，"
                    "名物词表按圈层挖 —— 两者的落差需要人工把关。",
        }
        log.warning("映射语言与圈层不一致：%s 的档案是 %s，选了 %s",
                    tgt_profile.code, profile_lang, lang)

    version = int(db.execute(
        select(func.coalesce(func.max(WorldTransform.version), 0)).where(
            WorldTransform.novel_id == novel_id,
            WorldTransform.target_language_code == lang,
        )
    ).scalar_one()) + 1

    t = WorldTransform(
        id=new_id("tf"), novel_id=novel_id,
        target_language_code=lang,
        source_profile_id=body.source_profile_id,
        target_profile_id=body.target_profile_id,
        version=version, status=TransformStatus.draft, policy_json=policy,
    )
    db.add(t)
    db.flush()
    out = _transform_out(t, db)
    if mismatch:
        out["warning"] = policy["language_override"]["note"]
    return out


def _get_transform(db: Session, transform_id: str) -> WorldTransform:
    t = db.get(WorldTransform, transform_id)
    if t is None:
        raise HTTPException(status_code=404, detail="transform not found")
    return t


@router.post("/transforms/{transform_id}:activate")
def activate_transform(transform_id: str, db: Session = Depends(get_db)) -> dict:
    t = _get_transform(db, transform_id)
    for other in db.execute(
        select(WorldTransform).where(
            WorldTransform.novel_id == t.novel_id,
            WorldTransform.target_language_code == t.target_language_code,
            WorldTransform.status == TransformStatus.active,
        )
    ).scalars():
        other.status = TransformStatus.archived
    t.status = TransformStatus.active
    db.flush()
    return _transform_out(t, db)


@router.get("/transforms/{transform_id}/coverage")
def get_coverage(transform_id: str, db: Session = Depends(get_db)) -> dict:
    return pf.coverage_report(db, _get_transform(db, transform_id))


@router.get("/transforms/{transform_id}/preflight")
def get_preflight(transform_id: str, db: Session = Depends(get_db)) -> dict:
    """起飞前门禁。ready=false 时不应放行批量翻译。"""
    return pf.preflight(db, _get_transform(db, transform_id))


# ── 名物词表 ──────────────────────────────────────────────────────────────────

class LexiconIn(BaseModel):
    canonical_key: str
    category: LexiconCategory = LexiconCategory.other
    source_term: str
    source_aliases: list[str] = Field(default_factory=list)
    target_term: str
    target_reading: str | None = None
    forbidden_targets: list[str] = Field(default_factory=list)
    rationale: str | None = None


def _lex_out(r: WorldLexicon) -> dict:
    return {
        "id": r.id, "canonical_key": r.canonical_key, "category": r.category.value,
        "source_term": r.source_term, "source_aliases": r.source_aliases or [],
        "target_term": r.target_term, "target_reading": r.target_reading,
        "forbidden_targets": r.forbidden_targets or [],
        "status": r.status.value, "confidence": r.confidence,
        "rationale": r.rationale, "evidence": r.evidence_json or {},
        "source": r.source.value, "hit_count": r.hit_count,
    }


@router.get("/lexicon-templates")
def list_templates(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(select(WorldLexiconTemplate).order_by(WorldLexiconTemplate.pair_code)).scalars()
    return [
        {"id": t.id, "pair_code": t.pair_code, "display_name": t.display_name,
         "source_profile_code": t.source_profile_code,
         "target_profile_code": t.target_profile_code,
         "entry_count": len(t.entries_json or []), "description": t.description}
        for t in rows
    ]


@router.get("/transforms/{transform_id}/lexicon")
def list_lexicon(
    transform_id: str,
    category: str | None = Query(None), status: str | None = Query(None),
    q: str | None = Query(None), missing_target: bool = Query(False),
    db: Session = Depends(get_db),
) -> list[dict]:
    stmt = select(WorldLexicon).where(WorldLexicon.transform_id == transform_id)
    if category:
        stmt = stmt.where(WorldLexicon.category == LexiconCategory(category))
    if status:
        stmt = stmt.where(WorldLexicon.status == ReviewStatus(status))
    if missing_target:
        stmt = stmt.where(WorldLexicon.target_term == "")
    if q:
        stmt = stmt.where(
            WorldLexicon.source_term.ilike(f"%{q}%") | WorldLexicon.target_term.ilike(f"%{q}%")
        )
    rows = db.execute(
        stmt.order_by(WorldLexicon.hit_count.desc(), WorldLexicon.source_term)
    ).scalars()
    return [_lex_out(r) for r in rows]


@router.post("/transforms/{transform_id}/lexicon", status_code=201)
def create_lexicon(transform_id: str, body: LexiconIn, db: Session = Depends(get_db)) -> dict:
    _get_transform(db, transform_id)
    r = WorldLexicon(
        id=new_id("wl"), transform_id=transform_id, **body.model_dump(),
        status=ReviewStatus.approved, source=LexiconSource.manual, confidence=1.0,
    )
    db.add(r)
    db.flush()
    return _lex_out(r)


@router.post("/transforms/{transform_id}/lexicon:import-template")
def import_lexicon_template(transform_id: str, pair_code: str = Query(...),
                            overwrite: bool = Query(False),
                            db: Session = Depends(get_db)) -> dict:
    t = _get_transform(db, transform_id)
    from app.pipelines.base import PipelineError

    try:
        res = survey.import_template(db, t, pair_code)
    except PipelineError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"pair_code": res.pair_code, "created": res.created,
            "skipped": res.skipped, "entries": res.entries[:20]}


@router.post("/transforms/{transform_id}/lexicon:promote-template")
def promote_lexicon_template(
    transform_id: str,
    overwrite: bool = Query(False, description="true 则新建版本替换，默认与已有模板合并"),
    include_candidates: bool = Query(
        False, description="连未审的候选一起沉淀。会把模型的猜测固化成标准，慎用"
    ),
    db: Session = Depends(get_db),
) -> dict:
    """把审定的名物词条沉淀成跨小说可复用的模板。

    25 个圈层两两配对有 600 种组合，不可能预置。所以路径是反的：
    先挖，审定后沉淀，下一本书直接导入 —— 用得越多冷启动成本越低。
    """
    from app.models import ReviewStatus
    from app.pipelines.base import PipelineError

    t = _get_transform(db, transform_id)
    try:
        return survey.promote_to_template(
            db, t, overwrite=overwrite,
            min_status=(
                ReviewStatus.candidate if include_candidates else ReviewStatus.approved
            ),
        )
    except PipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/transforms/{transform_id}/lexicon:survey")
def survey_lexicon(
    transform_id: str,
    chapter_id: str = Query(..., description="要勘探的章节"),
    mine: bool = Query(True, description="false 则只做模板扫描，不调 LLM 不花钱"),
    max_candidates: int = Query(40, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    """勘探一章：模板扫描 → 统计新词发现 → LLM 判定译法。

    产出待审核的候选词条。审核发生在这一层的产物上 ——
    审几百条词表，管全书几十万字。
    """
    from app.models import Chapter
    from app.pipelines.base import PipelineError

    t = _get_transform(db, transform_id)
    chapter = db.get(Chapter, chapter_id)
    if chapter is None:
        raise HTTPException(status_code=404, detail="chapter not found")
    try:
        res = survey.survey_chapter(db, t, chapter, mine=mine,
                                    max_candidates=max_candidates)
    except PipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return res.as_dict()


class LexiconPatch(BaseModel):
    """部分更新。字段全部可选 —— 原来复用 LexiconIn（全字段必填），
    那是 PUT 的语义：想改一个译法就得把 source_aliases、forbidden_targets
    一并原样传回，漏传一个就被清空，而清空不会报错。
    """

    canonical_key: str | None = None
    category: LexiconCategory | None = None
    source_term: str | None = None
    source_aliases: list[str] | None = None
    target_term: str | None = None
    target_reading: str | None = None
    forbidden_targets: list[str] | None = None
    rationale: str | None = None


@router.patch("/lexicon/{lex_id}")
def update_lexicon(lex_id: str, body: LexiconPatch,
                   db: Session = Depends(get_db)) -> dict:
    r = db.get(WorldLexicon, lex_id)
    if r is None:
        raise HTTPException(status_code=404, detail="lexicon entry not found")
    if r.status == ReviewStatus.locked:
        raise HTTPException(status_code=409, detail="条目已锁定，请先解锁再修改")
    # exclude_unset：只写用户真正传了的字段。
    # 用 exclude_none 会让「把 rationale 清空」变得无法表达。
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(r, k, v)
    db.flush()
    return _lex_out(r)


@router.post("/lexicon/{lex_id}:approve")
def approve_lexicon(lex_id: str, db: Session = Depends(get_db)) -> dict:
    r = db.get(WorldLexicon, lex_id)
    if r is None:
        raise HTTPException(status_code=404, detail="lexicon entry not found")
    if not r.target_term:
        raise HTTPException(status_code=422, detail="没有译法的条目不能通过审核")
    r.status = ReviewStatus.approved
    db.flush()
    return _lex_out(r)


@router.post("/lexicon/{lex_id}:lock")
def lock_lexicon(lex_id: str, db: Session = Depends(get_db)) -> dict:
    r = db.get(WorldLexicon, lex_id)
    if r is None:
        raise HTTPException(status_code=404, detail="lexicon entry not found")
    if not r.target_term:
        raise HTTPException(status_code=422, detail="没有译法的条目不能锁定")
    r.status = ReviewStatus.locked
    db.flush()
    return _lex_out(r)


class BatchIds(BaseModel):
    ids: list[str]


@router.post("/transforms/{transform_id}/lexicon:batch-approve")
def batch_approve(transform_id: str, body: BatchIds, db: Session = Depends(get_db)) -> dict:
    rows = db.execute(
        select(WorldLexicon).where(
            WorldLexicon.transform_id == transform_id, WorldLexicon.id.in_(body.ids)
        )
    ).scalars().all()
    ok = skipped = 0
    for r in rows:
        if not r.target_term or r.status == ReviewStatus.locked:
            skipped += 1
            continue
        r.status = ReviewStatus.approved
        ok += 1
    db.flush()
    return {"approved": ok, "skipped": skipped}


@router.delete("/lexicon/{lex_id}", status_code=204)
def delete_lexicon(lex_id: str, db: Session = Depends(get_db)) -> None:
    r = db.get(WorldLexicon, lex_id)
    if r is None:
        raise HTTPException(status_code=404, detail="lexicon entry not found")
    if r.status == ReviewStatus.locked:
        raise HTTPException(status_code=409, detail="条目已锁定，不能删除")
    db.delete(r)


# ── 人名 ──────────────────────────────────────────────────────────────────────

class NameIn(BaseModel):
    target_name: str
    target_reading: str | None = None
    naming_policy: NamingPolicy = NamingPolicy.cultural_equivalent
    rationale: str | None = None


def _name_out(n: EntityWorldName, e: WorldEntity | None = None) -> dict:
    return {
        "id": n.id, "entity_id": n.entity_id,
        "entity_name": e.display_name if e else None,
        "entity_kind": e.kind.value if e else None,
        "target_name": n.target_name, "target_reading": n.target_reading,
        "family_key": n.family_key, "family_surname": n.family_surname,
        "naming_policy": n.naming_policy.value,
        "candidates": n.candidates_json or [], "rationale": n.rationale,
        "status": n.status.value, "locked": n.locked,
    }


@router.get("/transforms/{transform_id}/names")
def list_names(transform_id: str, family_key: str | None = Query(None),
               db: Session = Depends(get_db)) -> list[dict]:
    stmt = (
        select(EntityWorldName, WorldEntity)
        .join(WorldEntity, WorldEntity.id == EntityWorldName.entity_id)
        .where(EntityWorldName.transform_id == transform_id)
    )
    if family_key:
        stmt = stmt.where(EntityWorldName.family_key == family_key)
    rows = db.execute(stmt.order_by(EntityWorldName.family_key, WorldEntity.display_name)).all()
    return [_name_out(n, e) for n, e in rows]


@router.patch("/names/{name_id}")
def update_name(name_id: str, body: NameIn, db: Session = Depends(get_db)) -> dict:
    n = db.get(EntityWorldName, name_id)
    if n is None:
        raise HTTPException(status_code=404, detail="name not found")
    if n.locked:
        raise HTTPException(status_code=409, detail="译名已锁定，请先解锁")

    t = db.get(WorldTransform, n.transform_id)
    tgt_profile = db.get(WorldProfile, t.target_profile_id)
    pattern = (
        (tgt_profile.language_json or {}).get("name_pattern") if tgt_profile else None
    )
    ok, why = naming.validate_localized_name(
        body.target_name, t.target_language_code, pattern
    )
    if not ok:
        raise HTTPException(status_code=422, detail=why)

    tgt = db.get(WorldProfile, t.target_profile_id)
    pattern = str((tgt.language_json or {}).get("name_pattern") or "family_given")
    n.target_name = body.target_name
    n.target_reading = body.target_reading
    n.naming_policy = body.naming_policy
    n.rationale = body.rationale
    n.family_surname = naming.split_surname(body.target_name, pattern)[0]
    n.status = ReviewStatus.approved
    db.flush()
    return _name_out(n, db.get(WorldEntity, n.entity_id))


@router.post("/names/{name_id}:lock")
def lock_name(name_id: str, db: Session = Depends(get_db)) -> dict:
    n = db.get(EntityWorldName, name_id)
    if n is None:
        raise HTTPException(status_code=404, detail="name not found")
    n.locked = True
    n.status = ReviewStatus.locked
    db.flush()
    return _name_out(n, db.get(WorldEntity, n.entity_id))


@router.post("/transforms/{transform_id}/names:check-family")
def check_family(transform_id: str, db: Session = Depends(get_db)) -> dict:
    """家族姓氏一致性检查。李清照与李格非若被映射成两个姓，在这里被抓住。"""
    t = _get_transform(db, transform_id)
    tgt = db.get(WorldProfile, t.target_profile_id)
    pattern = str((tgt.language_json or {}).get("name_pattern") or "family_given")
    rows = db.execute(
        select(WorldEntity.id, WorldEntity.family_key, EntityWorldName.target_name,
               WorldEntity.display_name)
        .join(EntityWorldName, EntityWorldName.entity_id == WorldEntity.id)
        .where(EntityWorldName.transform_id == transform_id,
               WorldEntity.family_key.is_not(None))
    ).all()
    conflicts = naming.check_family_consistency([(r[0], r[1], r[2]) for r in rows], pattern)
    labels = {r[0]: r[3] for r in rows}
    for c in conflicts:
        c["source_name"] = labels.get(c["entity_id"])
    return {"conflicts": conflicts, "checked": len(rows)}


# ── 违规 ──────────────────────────────────────────────────────────────────────

@router.get("/transforms/{transform_id}/violations")
def list_violations(transform_id: str, kind: str | None = Query(None),
                    severity: str | None = Query(None),
                    status: str = Query("open"),
                    db: Session = Depends(get_db)) -> list[dict]:
    stmt = select(WorldViolation).where(WorldViolation.transform_id == transform_id)
    if status:
        stmt = stmt.where(WorldViolation.status == ViolationStatus(status))
    if kind:
        stmt = stmt.where(WorldViolation.kind == kind)
    if severity:
        stmt = stmt.where(WorldViolation.severity == Severity(severity))
    rows = db.execute(stmt.order_by(WorldViolation.severity, WorldViolation.created_at.desc())).scalars()
    return [
        {"id": v.id, "kind": v.kind.value, "severity": v.severity.value,
         "scope": v.scope.value, "ref_id": v.ref_id, "detected": v.detected,
         "expected": v.expected, "suggested_fix": v.suggested_fix,
         "evidence": v.evidence_json or {}, "status": v.status.value}
        for v in rows
    ]


@router.post("/violations/{violation_id}:resolve")
def resolve_violation(violation_id: str, action: str = Query("resolved"),
                      db: Session = Depends(get_db)) -> dict:
    v = db.get(WorldViolation, violation_id)
    if v is None:
        raise HTTPException(status_code=404, detail="violation not found")
    v.status = ViolationStatus.ignored if action == "ignore" else ViolationStatus.resolved
    db.flush()
    return {"id": v.id, "status": v.status.value}


# ── 转译力度 · 导读篇 · 虚构圈层 ──────────────────────────────────────────────

class FidelityIn(BaseModel):
    fidelity: str


@router.patch("/transforms/{transform_id}/fidelity")
def set_fidelity(transform_id: str, body: FidelityIn,
                 db: Session = Depends(get_db)) -> dict:
    """设这次映射的转译力度。

    存真／折中／移植 —— 它不替代九档策略阶梯，只给阶梯一个偏置。
    每处的具体判断仍由文化依赖度 × 情节承载 × 时效性决定。
    """
    from app.models import Fidelity

    t = db.get(WorldTransform, transform_id)
    if t is None:
        raise HTTPException(status_code=404, detail="transform not found")
    try:
        fid = Fidelity(body.fidelity)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"未知力度 {body.fidelity}，可选："
                   f"{'、'.join(f.value for f in Fidelity)}") from exc
    t.policy_json = {**(t.policy_json or {}), "fidelity": fid.value}
    db.flush()
    return {"ok": True, "fidelity": fid.value}


@router.post("/transforms/{transform_id}/primer:generate")
def generate_primer(transform_id: str, force: bool = Query(False),
                    db: Session = Depends(get_db)) -> dict:
    """写一篇正文前的导读。

    修仙的境界、科幻的自造词在目标语里没有对应物。就地解释的话，
    这类词有几十个，读者每隔两页被打断一次。导读一次讲完，
    正文里就可以直接用原物。
    """
    from app.pipelines import primer as primer_pipe
    from app.pipelines.base import PipelineError

    t = db.get(WorldTransform, transform_id)
    if t is None:
        raise HTTPException(status_code=404, detail="transform not found")
    try:
        return primer_pipe.generate_primer(db, t, force=force).as_dict()
    except PipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/transforms/{transform_id}/primer")
def get_primer(transform_id: str, db: Session = Depends(get_db)) -> dict:
    """导读篇 + 它对正文的影响面。"""
    from app.models import Fidelity, WorldPrimer
    from app.pipelines.primer import (
        MAX_WORDS, MIN_WORDS, NEEDS_PRIMER, fidelity_of,
    )

    t = db.get(WorldTransform, transform_id)
    if t is None:
        raise HTTPException(status_code=404, detail="transform not found")
    fid = fidelity_of(t)
    row = db.execute(
        select(WorldPrimer).where(WorldPrimer.transform_id == transform_id)
        .order_by(WorldPrimer.version.desc())
    ).scalars().first()

    issues: list[str] = []
    if NEEDS_PRIMER[fid] == "required" and row is None:
        issues.append(
            "存真档但没有导读 —— 这一档的整个前提就是「术语原样保留，"
            "读者靠导读挂靠」。没有导读，读者会撞上一堆没有来处的词")
    if row is not None and row.status is ReviewStatus.candidate:
        issues.append(
            "导读还是候选状态，正文不会按「已经讲过」来写 —— "
            "审核通过后，讲过的词条在正文里才会直接用原物")
    if row is not None and row.word_count > MAX_WORDS:
        issues.append(f"{row.word_count} 词，超过 {MAX_WORDS} —— 太长没人读，"
                      f"而没人读的导读比没有导读更糟")

    return {
        "fidelity": fid.value,
        "fidelity_label": {
            Fidelity.preserve_world: "存真 · 体系原样保留，靠导读挂靠",
            Fidelity.anchored: "折中 · 体系保留，关键处给目标文化锚点",
            Fidelity.transplant_world: "移植 · 整体搬进目标圈层",
        }[fid],
        "primer_needed": NEEDS_PRIMER[fid],
        "word_budget": {"min": MIN_WORDS, "max": MAX_WORDS},
        "primer": None if row is None else {
            "id": row.id, "version": row.version, "title": row.title,
            "sections": row.sections_json or [],
            "body": row.body, "covers": row.covers_json or [],
            "word_count": row.word_count, "status": row.status.value,
            "locked": row.locked, "edited_by_human": row.edited_by_human,
            "rationale": row.rationale,
        },
        "issues": issues,
    }


class PrimerPatch(BaseModel):
    title: str | None = None
    body: str | None = None
    covers: list[str] | None = None
    status: str | None = None
    locked: bool | None = None


@router.patch("/primers/{primer_id}")
def patch_primer(primer_id: str, body: PrimerPatch,
                 db: Session = Depends(get_db)) -> dict:
    """人工改导读。改过的标 edited_by_human，重写要显式 force。"""
    from app.models import WorldPrimer

    row = db.get(WorldPrimer, primer_id)
    if row is None:
        raise HTTPException(status_code=404, detail="primer not found")
    for f in ("title", "body"):
        v = getattr(body, f)
        if v is not None:
            setattr(row, f, v)
            row.edited_by_human = True
    if body.covers is not None:
        row.covers_json = body.covers or None
        row.edited_by_human = True
    if body.status:
        try:
            row.status = ReviewStatus(body.status)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="unknown status") from exc
    if body.locked is not None:
        row.locked = body.locked
    db.flush()
    return {"ok": True, "id": row.id, "status": row.status.value}


@router.get("/world-profiles/{profile_id}/resolved")
def get_resolved_profile(profile_id: str, db: Session = Depends(get_db)) -> dict:
    """解析后的圈层：虚构圈层叠加它的现实底座。

    三体的未来、修真界不是任何现实文化，但读者是现实里的人 ——
    语域、日常常识、礼貌尺度都得有个现实依托。
    """
    from app.worldview import profile_resolve

    p = db.get(WorldProfile, profile_id)
    if p is None:
        raise HTTPException(status_code=404, detail="world profile not found")
    out = profile_resolve.resolve(db, p)
    warn = profile_resolve.missing_base(p)
    out["issues"] = [warn] if warn else []
    return out


# ── 混合源圈层 ────────────────────────────────────────────────────────────────

class ExtraSourcesIn(BaseModel):
    profile_ids: list[str] = Field(default_factory=list)


@router.patch("/transforms/{transform_id}/source-worlds")
def set_extra_sources(transform_id: str, body: ExtraSourcesIn,
                      db: Session = Depends(get_db)) -> dict:
    """配这次映射的额外源圈层。

    穿越／双线小说的源文本本身横跨两个圈层：「先生」在古代场是老师，
    在现代场是 Mr.。配了之后才谈得上按场消歧。
    """
    t = db.get(WorldTransform, transform_id)
    if t is None:
        raise HTTPException(status_code=404, detail="transform not found")
    ids = [i for i in body.profile_ids if i != t.source_profile_id]
    for pid in ids:
        if db.get(WorldProfile, pid) is None:
            raise HTTPException(status_code=400,
                                detail=f"world profile {pid} not found")
    t.extra_source_profiles_json = ids or None
    db.flush()
    return {"ok": True, "main": t.source_profile_id, "extra": ids}


@router.post("/chapters/{chapter_id}/source-worlds:assign")
def assign_source_worlds(chapter_id: str, transform_id: str = Query(...),
                         force: bool = Query(False),
                         db: Session = Depends(get_db)) -> dict:
    """给这一章的每一场戏定源圈层。

    按场而不是按章：穿越的切换点就是场景切换，一章里可以来回切好几次。
    """
    from app.models import Chapter
    from app.pipelines import source_worlds
    from app.pipelines.base import PipelineError

    ch = db.get(Chapter, chapter_id)
    if ch is None:
        raise HTTPException(status_code=404, detail="chapter not found")
    t = db.get(WorldTransform, transform_id)
    if t is None:
        raise HTTPException(status_code=404, detail="transform not found")
    try:
        return source_worlds.assign_scenes(db, t, ch, force=force).as_dict()
    except PipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/transforms/{transform_id}/source-worlds")
def get_source_worlds(transform_id: str, db: Session = Depends(get_db)) -> dict:
    """源圈层配置与各场归属，附体检。"""
    from app.models import Chapter, Scene, ScriptDoc, WorldLexicon
    from app.pipelines.source_worlds import source_profiles

    t = db.get(WorldTransform, transform_id)
    if t is None:
        raise HTTPException(status_code=404, detail="transform not found")
    profiles = source_profiles(db, t)
    names = {p.id: p.display_name for p in profiles}

    scenes = list(db.execute(
        select(Scene).join(ScriptDoc, ScriptDoc.id == Scene.script_doc_id)
        .join(Chapter, Chapter.id == ScriptDoc.chapter_id)
        .where(Chapter.novel_id == t.novel_id)
        .order_by(Chapter.order_no, Scene.order_no)
    ).scalars())
    lex = list(db.execute(
        select(WorldLexicon).where(WorldLexicon.transform_id == transform_id)
    ).scalars())

    unassigned = [s.title or s.id for s in scenes if not s.source_profile_id]
    issues: list[str] = []
    if len(profiles) > 1 and unassigned:
        issues.append(
            f"{len(unassigned)} 场没定源圈层，会回落到主源圈层「"
            f"{names.get(t.source_profile_id, '?')}」—— "
            f"落错的那几场整场用错词表，而沿途没有任何一处会报错")
    # 同一个源词挂了多个圈层 = 消歧真的在起作用；一个都没有 = 白配了
    by_term: dict[str, set] = {}
    for r in lex:
        by_term.setdefault(r.source_term, set()).add(r.source_profile_id)
    ambiguous = {k: v for k, v in by_term.items() if len(v) > 1}
    if len(profiles) > 1 and not ambiguous:
        issues.append(
            "配了多个源圈层，但没有任何一个词在两个世界里有不同译法 —— "
            "要么这本书其实不需要分圈层，要么词表挖掘时还没分场（先跑 assign）")

    return {
        "main": {"id": t.source_profile_id,
                 "display_name": names.get(t.source_profile_id)},
        "extra": [{"id": p.id, "display_name": p.display_name}
                  for p in profiles[1:]],
        "scenes": len(scenes),
        "assigned": len(scenes) - len(unassigned),
        "by_profile": {
            names.get(pid, "未定"): sum(1 for s in scenes
                                       if s.source_profile_id == pid)
            for pid in {s.source_profile_id for s in scenes}
        },
        "ambiguous_terms": [
            {"term": k, "worlds": [names.get(w, "通用") for w in v]}
            for k, v in sorted(ambiguous.items())[:20]
        ],
        "unassigned": unassigned[:10],
        "issues": issues,
    }
