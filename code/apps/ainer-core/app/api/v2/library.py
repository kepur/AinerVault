"""书架：小说 / 章节 / 导入分章。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.ids import new_id
from app.models import (
    Chapter, DocStatus, Novel, ScriptDoc, SourceFormat, TranslationBlock,
    ScriptBlock, GenTask, TaskStatus, ShotPlan,
)
from app.pipelines.ingest import count_words, split_chapters

router = APIRouter(prefix="/api/v2", tags=["library"])


# ── DTO ───────────────────────────────────────────────────────────────────────

class NovelIn(BaseModel):
    title: str
    author: str | None = None
    source_language_code: str = "zh-CN"
    description: str | None = None
    default_target_languages: list[str] = Field(default_factory=list)
    source_world_profile_id: str | None = None


class NovelOut(BaseModel):
    id: str
    title: str
    author: str | None
    source_language_code: str
    description: str | None
    default_target_languages: list[str]
    source_world_profile_id: str | None
    chapter_count: int = 0
    word_count: int = 0
    created_at: str

    @classmethod
    def of(cls, n: Novel, *, chapters: int = 0, words: int = 0) -> NovelOut:
        return cls(
            id=n.id, title=n.title, author=n.author,
            source_language_code=n.source_language_code, description=n.description,
            default_target_languages=list(n.default_target_languages or []),
            source_world_profile_id=n.source_world_profile_id,
            chapter_count=chapters, word_count=words,
            created_at=n.created_at.isoformat(),
        )


class ChapterIn(BaseModel):
    title: str | None = None
    content: str = ""
    order_no: int | None = None


class ImportIn(BaseModel):
    text: str
    source_format: str = "plain"        # plain | markdown
    min_chars: int = 200                # 低于此长度不单独成章，并入前一章
    fallback_chars: int = 3000          # 识别不到章节标记时的按长切分粒度
    dry_run: bool = False
    replace: bool = False


def _get_novel(db: Session, novel_id: str) -> Novel:
    n = db.get(Novel, novel_id)
    if n is None:
        raise HTTPException(status_code=404, detail="novel not found")
    return n


def _get_chapter(db: Session, chapter_id: str) -> Chapter:
    c = db.get(Chapter, chapter_id)
    if c is None:
        raise HTTPException(status_code=404, detail="chapter not found")
    return c


def _next_order(db: Session, novel_id: str) -> int:
    mx = db.execute(
        select(func.max(Chapter.order_no)).where(Chapter.novel_id == novel_id)
    ).scalar()
    return (mx or 0) + 1


# ── 小说 ──────────────────────────────────────────────────────────────────────

@router.get("/novels")
def list_novels(
    q: str | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(Novel)
    if q:
        stmt = stmt.where(Novel.title.ilike(f"%{q}%"))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(
        stmt.order_by(Novel.created_at.desc()).offset((page - 1) * size).limit(size)
    ).scalars().all()

    stats: dict[str, tuple[int, int]] = {}
    if rows:
        stats = {
            nid: (cnt, words)
            for nid, cnt, words in db.execute(
                select(
                    Chapter.novel_id, func.count(),
                    func.coalesce(func.sum(Chapter.word_count), 0),
                )
                .where(Chapter.novel_id.in_([n.id for n in rows]))
                .group_by(Chapter.novel_id)
            ).all()
        }
    return {
        "items": [
            NovelOut.of(n, chapters=stats.get(n.id, (0, 0))[0],
                        words=stats.get(n.id, (0, 0))[1]).model_dump()
            for n in rows
        ],
        "total": total, "page": page, "size": size,
    }


@router.post("/novels", status_code=201)
def create_novel(body: NovelIn, db: Session = Depends(get_db)) -> dict:
    n = Novel(id=new_id("nv"), **body.model_dump())
    db.add(n)
    db.flush()
    return NovelOut.of(n).model_dump()


@router.get("/novels/{novel_id}")
def get_novel(novel_id: str, db: Session = Depends(get_db)) -> dict:
    n = _get_novel(db, novel_id)
    cnt, words = db.execute(
        select(func.count(), func.coalesce(func.sum(Chapter.word_count), 0))
        .where(Chapter.novel_id == novel_id)
    ).one()
    return NovelOut.of(n, chapters=cnt, words=words).model_dump()


@router.patch("/novels/{novel_id}")
def update_novel(novel_id: str, body: NovelIn, db: Session = Depends(get_db)) -> dict:
    n = _get_novel(db, novel_id)
    for k, v in body.model_dump().items():
        setattr(n, k, v)
    db.flush()
    return NovelOut.of(n).model_dump()


@router.delete("/novels/{novel_id}", status_code=204)
def delete_novel(novel_id: str, db: Session = Depends(get_db)) -> None:
    db.delete(_get_novel(db, novel_id))


# ── 导入分章 ──────────────────────────────────────────────────────────────────

@router.post("/novels/{novel_id}/chapters:import")
def import_chapters(novel_id: str, body: ImportIn, db: Session = Depends(get_db)) -> dict:
    """按标题行切分文本为章节。

    dry_run=True 只返回预览不落库 —— 分章错了后面全错，值得先看一眼。
    """
    _get_novel(db, novel_id)
    result = split_chapters(
        body.text,
        source_format=body.source_format,
        min_chars=body.min_chars,
        fallback_chars=body.fallback_chars,
    )

    preview = [
        {
            "order_no": c.order_no, "title": c.title, "word_count": c.word_count,
            "detected_by": c.detected_by,
            "excerpt": c.content[:120].replace("\n", " "),
        }
        for c in result.chapters
    ]
    if body.dry_run:
        return {
            "dry_run": True, "strategy": result.strategy,
            "detected_headings": result.detected_headings,
            "chapter_count": len(result.chapters), "total_words": result.total_words,
            "chapters": preview,
        }

    if body.replace:
        for old in db.execute(
            select(Chapter).where(Chapter.novel_id == novel_id)
        ).scalars().all():
            db.delete(old)
        db.flush()
        base = 0
    else:
        base = _next_order(db, novel_id) - 1

    for c in result.chapters:
        db.add(Chapter(
            id=new_id("ch"), novel_id=novel_id, order_no=base + c.order_no,
            title=c.title, content=c.content, word_count=c.word_count,
            source_format=SourceFormat.plain,
            ingest_meta_json={"detected_by": c.detected_by, "strategy": result.strategy},
        ))
    db.flush()
    return {
        "dry_run": False, "strategy": result.strategy,
        "detected_headings": result.detected_headings,
        "chapter_count": len(result.chapters), "total_words": result.total_words,
        "chapters": preview,
    }


@router.post("/novels/{novel_id}/chapters:upload")
async def upload_chapters(
    novel_id: str,
    file: UploadFile = File(...),
    dry_run: bool = Query(False),
    replace: bool = Query(False),
    db: Session = Depends(get_db),
) -> dict:
    _get_novel(db, novel_id)
    raw = await file.read()
    for enc in ("utf-8", "utf-8-sig", "gb18030", "big5"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise HTTPException(status_code=400, detail="无法识别文件编码（试过 utf-8/gb18030/big5）")

    return import_chapters(
        novel_id, ImportIn(text=text, dry_run=dry_run, replace=replace), db
    )


# ── 章节 ──────────────────────────────────────────────────────────────────────

@router.get("/novels/{novel_id}/chapters")
def list_chapters(
    novel_id: str,
    with_state: bool = Query(True),
    db: Session = Depends(get_db),
) -> dict:
    """列表带状态四联，后台直接画进度条。"""
    _get_novel(db, novel_id)
    rows = db.execute(
        select(Chapter).where(Chapter.novel_id == novel_id).order_by(Chapter.order_no)
    ).scalars().all()

    states: dict[str, dict] = {}
    if with_state and rows:
        ids = [c.id for c in rows]

        script_status = {
            cid: st.value
            for cid, st in db.execute(
                select(ScriptDoc.chapter_id, ScriptDoc.status)
                .where(ScriptDoc.chapter_id.in_(ids), ScriptDoc.status == DocStatus.active)
            ).all()
        }

        # 译文完成率：按 (chapter, lang) 统计已译块 / 可译块
        trans_rows = db.execute(
            select(
                ScriptBlock.script_doc_id, TranslationBlock.target_language_code,
                func.count(), func.count(TranslationBlock.translated_text),
            )
            .join(TranslationBlock, TranslationBlock.script_block_id == ScriptBlock.id)
            .join(ScriptDoc, ScriptDoc.id == ScriptBlock.script_doc_id)
            .where(ScriptDoc.chapter_id.in_(ids))
            .group_by(ScriptBlock.script_doc_id, TranslationBlock.target_language_code)
        ).all()
        doc_to_chapter = {
            d: c for d, c in db.execute(
                select(ScriptDoc.id, ScriptDoc.chapter_id).where(ScriptDoc.chapter_id.in_(ids))
            ).all()
        }
        trans: dict[str, dict[str, float]] = {}
        for doc_id, lang, total, done in trans_rows:
            cid = doc_to_chapter.get(doc_id)
            if cid:
                trans.setdefault(cid, {})[lang] = round(done / total, 3) if total else 0.0

        asset_rows = db.execute(
            select(GenTask.chapter_id, GenTask.status, func.count())
            .where(GenTask.chapter_id.in_(ids))
            .group_by(GenTask.chapter_id, GenTask.status)
        ).all()
        assets: dict[str, dict[str, int]] = {}
        for cid, st, cnt in asset_rows:
            bucket = assets.setdefault(cid, {"total": 0, "ready": 0, "failed": 0})
            bucket["total"] += cnt
            if st == TaskStatus.succeeded:
                bucket["ready"] += cnt
            elif st == TaskStatus.failed:
                bucket["failed"] += cnt

        shot_docs = {
            d for (d,) in db.execute(
                select(ShotPlan.script_doc_id)
                .where(ShotPlan.script_doc_id.in_(list(doc_to_chapter)), 
                       ShotPlan.status == DocStatus.active)
            ).all()
        }
        shots_by_chapter = {doc_to_chapter[d] for d in shot_docs if d in doc_to_chapter}

        for c in rows:
            states[c.id] = {
                "script": script_status.get(c.id, "none"),
                "translation": trans.get(c.id, {}),
                "shots": "active" if c.id in shots_by_chapter else "none",
                "assets": assets.get(c.id, {"total": 0, "ready": 0, "failed": 0}),
            }

    return {
        "items": [
            {
                "id": c.id, "order_no": c.order_no, "title": c.title,
                "word_count": c.word_count,
                **({"state": states[c.id]} if c.id in states else {}),
            }
            for c in rows
        ],
        "total": len(rows),
    }


@router.post("/novels/{novel_id}/chapters", status_code=201)
def create_chapter(novel_id: str, body: ChapterIn, db: Session = Depends(get_db)) -> dict:
    _get_novel(db, novel_id)
    order = body.order_no if body.order_no is not None else _next_order(db, novel_id)
    c = Chapter(
        id=new_id("ch"), novel_id=novel_id, order_no=order,
        title=body.title, content=body.content, word_count=count_words(body.content),
    )
    db.add(c)
    db.flush()
    return {"id": c.id, "order_no": c.order_no, "title": c.title,
            "word_count": c.word_count}


@router.get("/chapters/{chapter_id}")
def get_chapter(chapter_id: str, db: Session = Depends(get_db)) -> dict:
    c = _get_chapter(db, chapter_id)
    return {
        "id": c.id, "novel_id": c.novel_id, "order_no": c.order_no, "title": c.title,
        "content": c.content, "word_count": c.word_count,
        "source_format": c.source_format.value,
        "ingest_meta": c.ingest_meta_json or {},
    }


@router.patch("/chapters/{chapter_id}")
def update_chapter(chapter_id: str, body: ChapterIn, db: Session = Depends(get_db)) -> dict:
    c = _get_chapter(db, chapter_id)
    if body.title is not None:
        c.title = body.title
    if body.content is not None:
        c.content = body.content
        c.word_count = count_words(body.content)
    if body.order_no is not None:
        c.order_no = body.order_no
    db.flush()
    return {"id": c.id, "order_no": c.order_no, "title": c.title, "word_count": c.word_count}


@router.delete("/chapters/{chapter_id}", status_code=204)
def delete_chapter(chapter_id: str, db: Session = Depends(get_db)) -> None:
    db.delete(_get_chapter(db, chapter_id))


class ReorderIn(BaseModel):
    chapter_ids: list[str]


@router.post("/novels/{novel_id}/chapters:reorder")
def reorder_chapters(novel_id: str, body: ReorderIn, db: Session = Depends(get_db)) -> dict:
    _get_novel(db, novel_id)
    rows = {
        c.id: c
        for c in db.execute(
            select(Chapter).where(Chapter.novel_id == novel_id)
        ).scalars()
    }
    unknown = [cid for cid in body.chapter_ids if cid not in rows]
    if unknown:
        raise HTTPException(status_code=400, detail=f"不属于本书的章节: {unknown[:5]}")
    # 先挪到负区间避开 UNIQUE(novel_id, order_no)
    for i, cid in enumerate(body.chapter_ids, start=1):
        rows[cid].order_no = -i
    db.flush()
    for i, cid in enumerate(body.chapter_ids, start=1):
        rows[cid].order_no = i
    db.flush()
    return {"count": len(body.chapter_ids)}
