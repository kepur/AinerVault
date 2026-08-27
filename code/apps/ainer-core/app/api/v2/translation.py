"""翻译与实体：抽取 → 命名 → 翻译 → 校对。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.ids import new_id
from app.models import (
    Chapter, DocStatus, EntityKind, EntityWorldName, Novel,
    NovelTranslationSettings, ReviewStatus, ScriptBlock, ScriptDoc, TranslationBlock,
    TranslationBlockStatus, WorldEntity, WorldTransform,
)
from app.models.script import TRANSLATABLE_TYPES
from app.models.world import TransformStatus
from app.pipelines import entities as ent_pipe
from app.pipelines import naming as name_pipe
from app.pipelines import speakers as speaker_pipe
from app.pipelines import translate as tr_pipe
from app.pipelines.base import PipelineError

router = APIRouter(prefix="/api/v2", tags=["translation"])


def _chapter(db: Session, chapter_id: str) -> Chapter:
    c = db.get(Chapter, chapter_id)
    if c is None:
        raise HTTPException(status_code=404, detail="chapter not found")
    return c


def _transform(db: Session, transform_id: str) -> WorldTransform:
    t = db.get(WorldTransform, transform_id)
    if t is None:
        raise HTTPException(status_code=404, detail="transform not found")
    return t


def _active_transform(db: Session, novel_id: str, lang: str) -> WorldTransform:
    t = db.execute(
        select(WorldTransform).where(
            WorldTransform.novel_id == novel_id,
            WorldTransform.target_language_code == lang,
            WorldTransform.status == TransformStatus.active,
        ).order_by(WorldTransform.version.desc())
    ).scalars().first()
    if t is None:
        raise HTTPException(
            status_code=409,
            detail=f"{lang} 没有 active 的世界观映射，请先创建并激活",
        )
    return t


# ── 实体 ──────────────────────────────────────────────────────────────────────

@router.post("/chapters/{chapter_id}/entities:extract")
def extract_entities(
    chapter_id: str,
    min_importance: int = Query(2, ge=1, le=5),
    db: Session = Depends(get_db),
) -> dict:
    """从章节抽取实体。占位符防漂移与家族命名都以此为前置。"""
    c = _chapter(db, chapter_id)
    try:
        return ent_pipe.extract_entities(db, c, min_importance=min_importance).as_dict()
    except PipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class ResolveIn(BaseModel):
    use_llm: bool = True
    overwrite: bool = False
    min_confidence: float = 0.6


@router.post("/chapters/{chapter_id}/speakers:resolve")
def resolve_speakers(chapter_id: str, body: ResolveIn,
                     db: Session = Depends(get_db)) -> dict:
    """把对白的 speaker_tag 解析到实体。

    不做这一步，对白就绑不到角色的 voice 素材，全部落到旁白音色兜底 ——
    一屋子人说话都是同一个嗓子。
    """
    c = _chapter(db, chapter_id)
    try:
        return speaker_pipe.resolve_speakers(
            db, c, use_llm=body.use_llm, overwrite=body.overwrite,
            min_confidence=body.min_confidence,
        ).as_dict()
    except PipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/novels/{novel_id}/speakers:resolve")
def resolve_speakers_novel(novel_id: str, body: ResolveIn,
                           db: Session = Depends(get_db)) -> dict:
    """整本书逐章解析说话人。"""
    if db.get(Novel, novel_id) is None:
        raise HTTPException(status_code=404, detail="novel not found")
    return speaker_pipe.resolve_novel(
        db, novel_id, use_llm=body.use_llm, overwrite=body.overwrite
    )


@router.get("/novels/{novel_id}/entities")
def list_entities(
    novel_id: str, kind: str | None = Query(None),
    family_key: str | None = Query(None), db: Session = Depends(get_db),
) -> list[dict]:
    q = select(WorldEntity).where(WorldEntity.novel_id == novel_id)
    if kind:
        q = q.where(WorldEntity.kind == EntityKind(kind))
    if family_key:
        q = q.where(WorldEntity.family_key == family_key)
    rows = db.execute(q.order_by(WorldEntity.family_key, WorldEntity.display_name)).scalars()
    return [
        {
            "id": e.id, "kind": e.kind.value, "canonical_key": e.canonical_key,
            "display_name": e.display_name, "aliases": e.aliases_json or [],
            "family_key": e.family_key, "summary": e.summary,
            "locked": e.locked,
            "appear_chapters": e.appear_chapters_json or [],
        }
        for e in rows
    ]


@router.patch("/entities/{entity_id}")
def update_entity(entity_id: str, body: dict, db: Session = Depends(get_db)) -> dict:
    e = db.get(WorldEntity, entity_id)
    if e is None:
        raise HTTPException(status_code=404, detail="entity not found")
    if e.locked and not body.get("force"):
        raise HTTPException(status_code=409, detail="实体已锁定")
    for field_name in ("display_name", "summary", "family_key"):
        if field_name in body:
            setattr(e, field_name, body[field_name])
    if "aliases" in body:
        e.aliases_json = list(body["aliases"])
    db.flush()
    return {"id": e.id, "display_name": e.display_name,
            "aliases": e.aliases_json or [], "family_key": e.family_key}


# ── L1 命名 ───────────────────────────────────────────────────────────────────

class SuggestIn(BaseModel):
    entity_ids: list[str] = Field(default_factory=list)
    limit: int = 60


@router.post("/transforms/{transform_id}/names:suggest")
def suggest_names(transform_id: str, body: SuggestIn,
                  db: Session = Depends(get_db)) -> dict:
    """按 family_key 分组整族生成译名。

    逐个独立生成时，父女会被映射成两个毫不相干的姓 —— 模型看不到亲属关系。
    生成后过拼音检测与家族一致性两道校验。
    """
    t = _transform(db, transform_id)
    try:
        return name_pipe.suggest_names(
            db, t, entity_ids=body.entity_ids or None, limit=body.limit
        ).as_dict()
    except PipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ── 翻译设置 ──────────────────────────────────────────────────────────────────

class SettingsIn(BaseModel):
    consistency_mode: str = "balanced"
    style_prompt: str | None = None
    batch_size: int = 10
    context_window: int = 1


@router.put("/novels/{novel_id}/translation-settings/{lang}")
def put_settings(novel_id: str, lang: str, body: SettingsIn,
                 db: Session = Depends(get_db)) -> dict:
    from app.models import ConsistencyMode

    if db.get(Novel, novel_id) is None:
        raise HTTPException(status_code=404, detail="novel not found")
    row = db.execute(
        select(NovelTranslationSettings).where(
            NovelTranslationSettings.novel_id == novel_id,
            NovelTranslationSettings.target_language_code == lang,
        )
    ).scalars().first()
    if row is None:
        row = NovelTranslationSettings(
            id=new_id("ts"), novel_id=novel_id, target_language_code=lang
        )
        db.add(row)
    row.consistency_mode = ConsistencyMode(body.consistency_mode)
    row.style_prompt = body.style_prompt
    row.batch_size = body.batch_size
    row.context_window = body.context_window
    db.flush()
    return {"novel_id": novel_id, "target_language_code": lang,
            "consistency_mode": row.consistency_mode.value,
            "style_prompt": row.style_prompt, "batch_size": row.batch_size}


# ── 翻译执行 ──────────────────────────────────────────────────────────────────

class RunIn(BaseModel):
    only_missing: bool = True
    batch_size: int = 10
    strict: bool | None = None
    force: bool = False          # 跳过 preflight 门禁


@router.post("/chapters/{chapter_id}/translation/{lang}:run")
def run_translation(chapter_id: str, lang: str, body: RunIn,
                    db: Session = Depends(get_db)) -> dict:
    """翻译一章。世界观四层全部生效。

    默认先过 preflight 门禁 —— 映射没定死就翻译，等于花钱买返工。
    """
    from app.worldview import preflight as pf

    c = _chapter(db, chapter_id)
    t = _active_transform(db, c.novel_id, lang)

    if not body.force:
        gate = pf.preflight(db, t, [chapter_id])
        if not gate["ready"]:
            raise HTTPException(status_code=409, detail={
                "code": "PREFLIGHT_NOT_READY",
                "message": "世界观映射尚未就绪，翻译前请先完成审核；确需继续请带 force=true",
                "blocking": [i for i in gate["issues"] if i["severity"] == "blocking"],
            })
    try:
        res = tr_pipe.translate_chapter(
            db, c, t, batch_size=body.batch_size,
            only_missing=body.only_missing, strict=body.strict,
        )
    except PipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"transform_id": t.id, **res.as_dict()}


@router.get("/chapters/{chapter_id}/translation/{lang}")
def get_translation(chapter_id: str, lang: str,
                    db: Session = Depends(get_db)) -> dict:
    """逐块原文 / 译文对照。action 与 scene_break 不进翻译线，标记出来。"""
    _chapter(db, chapter_id)
    doc = db.execute(
        select(ScriptDoc).where(
            ScriptDoc.chapter_id == chapter_id, ScriptDoc.status == DocStatus.active
        )
    ).scalars().first()
    if doc is None:
        raise HTTPException(status_code=404, detail="该章节尚未生成剧本")

    blocks = list(
        db.execute(
            select(ScriptBlock).where(ScriptBlock.script_doc_id == doc.id)
            .order_by(ScriptBlock.seq_no)
        ).scalars()
    )
    tmap = {
        t.script_block_id: t
        for t in db.execute(
            select(TranslationBlock).where(
                TranslationBlock.script_block_id.in_([b.id for b in blocks]),
                TranslationBlock.target_language_code == lang,
            )
        ).scalars()
    }

    items = []
    total = done = reviewed = locked = 0
    for b in blocks:
        translatable = b.block_type in TRANSLATABLE_TYPES
        t = tmap.get(b.id)
        if translatable:
            total += 1
            if t and t.translated_text:
                done += 1
            if t and t.status == TranslationBlockStatus.reviewed:
                reviewed += 1
            if t and t.locked:
                locked += 1
        items.append({
            "block_id": b.id, "seq_no": b.seq_no, "type": b.block_type.value,
            "translatable": translatable,
            "speaker": b.speaker_tag,
            "source": b.source_text,
            "target": t.translated_text if t else None,
            "translation_id": t.id if t else None,
            "status": t.status.value if t else None,
            "locked": bool(t and t.locked),
            "lexicon_hits": (t.lexicon_hits_json or []) if t else [],
        })
    return {
        "chapter_id": chapter_id, "language": lang, "blocks": items,
        "stats": {"translatable": total, "translated": done,
                  "reviewed": reviewed, "locked": locked},
    }


class BlockPatch(BaseModel):
    translated_text: str
    status: str | None = None


@router.patch("/translation-blocks/{tb_id}")
def update_block(tb_id: str, body: BlockPatch, db: Session = Depends(get_db)) -> dict:
    t = db.get(TranslationBlock, tb_id)
    if t is None:
        raise HTTPException(status_code=404, detail="translation block not found")
    if t.locked:
        raise HTTPException(status_code=409, detail="该块已锁定，请先解锁")
    t.translated_text = body.translated_text
    if body.status:
        t.status = TranslationBlockStatus(body.status)
    db.flush()
    return {"id": t.id, "translated_text": t.translated_text, "status": t.status.value}


@router.post("/translation-blocks/{tb_id}:lock")
def lock_block(tb_id: str, db: Session = Depends(get_db)) -> dict:
    t = db.get(TranslationBlock, tb_id)
    if t is None:
        raise HTTPException(status_code=404, detail="translation block not found")
    t.locked = True
    t.status = TranslationBlockStatus.locked
    db.flush()
    return {"id": t.id, "locked": True, "status": t.status.value}


@router.post("/translation-blocks/{tb_id}:unlock")
def unlock_block(tb_id: str, db: Session = Depends(get_db)) -> dict:
    t = db.get(TranslationBlock, tb_id)
    if t is None:
        raise HTTPException(status_code=404, detail="translation block not found")
    t.locked = False
    t.status = TranslationBlockStatus.reviewed
    db.flush()
    return {"id": t.id, "locked": False, "status": t.status.value}


class AffectedIn(BaseModel):
    lexicon_ids: list[str] = Field(default_factory=list)


@router.post("/transforms/{transform_id}/translation:retranslate-affected")
def retranslate_affected(transform_id: str, body: AffectedIn,
                         db: Session = Depends(get_db)) -> dict:
    """名物改动后，只清掉受影响块的译文等待重译。已锁定的块不动。"""
    t = _transform(db, transform_id)
    return tr_pipe.retranslate_affected(
        db, t, lexicon_ids=body.lexicon_ids or None
    )
