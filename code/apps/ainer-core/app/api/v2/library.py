"""书架：小说 / 章节 / 导入分章。"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, insert, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.base import utcnow

log = logging.getLogger(__name__)
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


def _impact(db: Session, novel_id: str) -> dict[str, int]:
    """删这本书会连带删掉什么。

    **删除前必须能看见影响面。** 一本长篇连带几千个块、几百个任务与产物，
    删了不可恢复 —— 而「确定吗？」这三个字不构成信息。
    """
    from app.models import (
        Asset, GenTask, ScriptBlock, WorldEntity, WorldLexicon, WorldTransform,
    )

    ch = select(Chapter.id).where(Chapter.novel_id == novel_id)
    docs = select(ScriptDoc.id).where(ScriptDoc.chapter_id.in_(ch))
    tf = select(WorldTransform.id).where(WorldTransform.novel_id == novel_id)

    def n(stmt) -> int:
        return db.execute(select(func.count()).select_from(stmt.subquery())).scalar() or 0

    return {
        "chapters": n(ch),
        "script_docs": n(docs),
        "blocks": n(select(ScriptBlock.id).where(ScriptBlock.script_doc_id.in_(docs))),
        "translations": n(
            select(TranslationBlock.id).join(
                ScriptBlock, ScriptBlock.id == TranslationBlock.script_block_id
            ).where(ScriptBlock.script_doc_id.in_(docs))),
        "entities": n(select(WorldEntity.id).where(WorldEntity.novel_id == novel_id)),
        "transforms": n(tf),
        "lexicon": n(select(WorldLexicon.id).where(WorldLexicon.transform_id.in_(tf))),
        "gen_tasks": n(select(GenTask.id).where(GenTask.novel_id == novel_id)),
        "assets": n(select(Asset.id).where(Asset.novel_id == novel_id)),
    }


@router.get("/novels/{novel_id}/delete-preview")
def preview_delete(novel_id: str, db: Session = Depends(get_db)) -> dict:
    """删这本书会连带删掉什么。删之前看一眼。"""
    n = _get_novel(db, novel_id)
    return {"novel": {"id": n.id, "title": n.title}, "impact": _impact(db, novel_id)}


@router.delete("/novels/{novel_id}")
def delete_novel(novel_id: str, purge_media: bool = Query(True),
                 db: Session = Depends(get_db)) -> dict:
    """删一本书及其全部衍生数据。

    多数表挂了 novel_id 外键、`ON DELETE CASCADE`，删小说自动带走。
    但 **gen_tasks 与 assets 的 novel_id 不是外键** ——
    它们要跨表引用不同来源（章节、映射、镜头），加外键会把生命周期
    绑死在小说上，而任务记录有独立的审计价值。
    代价是删小说时它们不会自动走，所以这里显式删。

    purge_media 连带删掉落盘的媒体文件。**按内容寻址是个陷阱**：
    同一张图可能被多本书引用（sha256 相同就是同一个文件），
    删文件前必须确认没有别的 asset 还指着它。
    """
    from app.models import Asset, GenTask

    novel = _get_novel(db, novel_id)
    title = novel.title
    impact = _impact(db, novel_id)

    # 先收集要删的媒体 URL，删行之后就查不到了
    urls = [
        u for (u,) in db.execute(
            select(Asset.url).where(Asset.novel_id == novel_id)
        ).all() if u
    ] if purge_media else []

    db.execute(delete(GenTask).where(GenTask.novel_id == novel_id))
    db.execute(delete(Asset).where(Asset.novel_id == novel_id))
    db.delete(novel)
    db.flush()

    removed_files = 0
    if urls:
        # 删行之后再查：还有没有别的 asset 指着同一个文件
        still_used = {
            u for (u,) in db.execute(
                select(Asset.url).where(Asset.url.in_(urls))
            ).all()
        }
        removed_files = _purge_media([u for u in urls if u not in still_used])

    return {
        "deleted": True, "novel_id": novel_id, "title": title,
        "impact": impact, "media_files_removed": removed_files,
    }


def _purge_media(urls: list[str]) -> int:
    """删掉本地媒体目录里的文件。只删本服务落盘的那些。

    URL 指向别处（中间层、对象存储）的一律不碰 —— 那不是我们的文件，
    而误删别人的存储是不可逆的。
    """
    from app.capability.mediastore import media_root

    root = media_root().resolve()
    n = 0
    for u in set(urls):
        name = u.rsplit("/media/", 1)[-1] if "/media/" in u else None
        if not name or "/" in name or "\\" in name or name.startswith("."):
            continue
        path = (root / name).resolve()
        # 解析后仍在媒体目录内才删 —— 防 ../ 逃逸
        if path.parent != root or not path.is_file():
            continue
        try:
            path.unlink()
            n += 1
        except OSError:
            log.warning("删除媒体文件失败：%s", path)
    return n


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

    # 预览只回前后各若干条。**全量预览对人没有用** ——
    # 没人会看三千行分章表，而三千条带正文摘要的响应有好几 MB，
    # 前端画一遍就卡住了。
    # 首尾都给：分章出错最常见的两处就是开头（前言被当成第一章）
    # 与结尾（尾声没被切出来）
    preview = _preview(result.chapters)
    if body.dry_run:
        return {
            "dry_run": True, "strategy": result.strategy,
            "detected_headings": result.detected_headings,
            "chapter_count": len(result.chapters), "total_words": result.total_words,
            "chapters": preview,
        }

    if body.replace:
        # 逐个 delete 会把几千行全部载进 session 再逐个发 DELETE。
        # 整本替换是常见操作（分章错了重来），不该等半分钟
        db.execute(delete(Chapter).where(Chapter.novel_id == novel_id))
        db.flush()
        base = 0
    else:
        base = _next_order(db, novel_id) - 1

    # 批量插入。逐个 db.add 会为每一行建一个 ORM 实例并跟踪它 ——
    # 三千章下来光是身份映射就占满内存，而这里根本不需要跟踪：
    # 插完就不再碰它们了
    now = utcnow()
    db.execute(insert(Chapter), [
        {
            "id": new_id("ch"), "novel_id": novel_id,
            "order_no": base + c.order_no, "title": c.title,
            "content": c.content, "word_count": c.word_count,
            "source_format": SourceFormat.plain,
            "ingest_meta_json": {"detected_by": c.detected_by,
                                 "strategy": result.strategy},
            "workspace_id": "default", "created_at": now, "updated_at": now,
        }
        for c in result.chapters
    ])
    db.flush()
    return {
        "dry_run": False, "strategy": result.strategy,
        "detected_headings": result.detected_headings,
        "chapter_count": len(result.chapters), "total_words": result.total_words,
        "chapters": preview,
    }


#: 预览返回的条数上限（首尾各一半）。
#: 分章出错最常见的两处是开头与结尾 —— 前言被当成第一章，
#: 或尾声没被切出来。中间那几千章长得都一样，看了也看不出问题
_PREVIEW_N = 24


def _preview(chapters: list) -> list[dict]:
    def one(c) -> dict:
        return {
            "order_no": c.order_no, "title": c.title,
            "word_count": c.word_count, "detected_by": c.detected_by,
            "excerpt": c.content[:120].replace("\n", " "),
        }

    if len(chapters) <= _PREVIEW_N:
        return [one(c) for c in chapters]
    half = _PREVIEW_N // 2
    head = [one(c) for c in chapters[:half]]
    tail = [one(c) for c in chapters[-half:]]
    return head + [{"order_no": None, "title": f"… 中间 {len(chapters) - _PREVIEW_N} 章省略 …",
                    "word_count": None, "detected_by": "elided", "excerpt": ""}] + tail


#: 整本上传的大小上限。一本三百万字的中文长篇约 6 MB，
#: 20 MB 足够覆盖任何真实的书，而再往上多半是传错了文件 ——
#: 不设限的话，一个几百 MB 的文件会被整个读进内存再切成几万个对象
_MAX_UPLOAD = 20 * 1024 * 1024

#: 编码回落顺序。gb18030 放在 gbk/gb2312 之前 —— 它是超集，
#: 能解 gbk 的它都能解，反过来不成立
_ENCODINGS = ("utf-8", "utf-8-sig", "gb18030", "big5", "shift_jis", "euc-kr")


@router.post("/novels/{novel_id}/chapters:upload")
async def upload_chapters(
    novel_id: str,
    file: UploadFile = File(...),
    dry_run: bool = Query(False),
    replace: bool = Query(False),
    source_format: str = Query("plain"),
    min_chars: int = Query(200, ge=0),
    fallback_chars: int = Query(3000, ge=500),
    db: Session = Depends(get_db),
) -> dict:
    """整本 txt 导入。按标题行分章，纯规则，不调 LLM。

    分章错了后面全错，所以**默认建议先 dry_run 看一眼** ——
    尤其是前几章与最后几章：前言被当成第一章、尾声没被切出来，
    是这一步最常见的两种错。
    """
    _get_novel(db, novel_id)
    raw = await file.read()
    if len(raw) > _MAX_UPLOAD:
        raise HTTPException(
            status_code=413,
            detail=f"文件 {len(raw) // 1024 // 1024} MB，超过上限 "
                   f"{_MAX_UPLOAD // 1024 // 1024} MB。"
                   f"一本三百万字的中文长篇约 6 MB —— 确认没传错文件？")
    if not raw.strip():
        raise HTTPException(status_code=400, detail="文件是空的")

    for enc in _ENCODINGS:
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise HTTPException(
            status_code=400,
            detail=f"无法识别文件编码（试过 {'/'.join(_ENCODINGS)}）。"
                   f"用文本编辑器另存为 UTF-8 再传")

    return import_chapters(
        novel_id,
        ImportIn(text=text, dry_run=dry_run, replace=replace,
                 source_format=source_format, min_chars=min_chars,
                 fallback_chars=fallback_chars),
        db,
    )


# ── 章节 ──────────────────────────────────────────────────────────────────────

@router.get("/novels/{novel_id}/chapters")
def list_chapters(
    novel_id: str,
    with_state: bool = Query(True),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    q: str | None = Query(None, description="按标题或章号搜索"),
    db: Session = Depends(get_db),
) -> dict:
    """列表带状态四联，后台直接画进度条。

    **必须分页。** 一本长篇几千章，全量返回既撑爆响应，
    状态四联那四个 JOIN 也会在几千个 id 上跑 ——
    而人一次只看得了几十行。

    状态只对**当前页**算：`with_state` 的四个查询用的是本页的 id，
    不是全书的。翻页时重新算，代价与页大小成正比而不是与书长成正比。
    """
    _get_novel(db, novel_id)

    base = select(Chapter).where(Chapter.novel_id == novel_id)
    if q and q.strip():
        term = q.strip()
        cond = Chapter.title.ilike(f"%{term}%")
        if term.isdigit():
            # 数字既可能是章号也可能出现在标题里，两边都认 ——
            # 「跳到第 1500 章」是长篇里最常做的动作
            cond = or_(cond, Chapter.order_no == int(term))
        base = base.where(cond)

    total = db.execute(
        select(func.count()).select_from(base.subquery())
    ).scalar() or 0
    rows = db.execute(
        base.order_by(Chapter.order_no).offset(offset).limit(limit)
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
        for doc_id, lang, tot, done in trans_rows:
            cid = doc_to_chapter.get(doc_id)
            if cid:
                trans.setdefault(cid, {})[lang] = round(done / tot, 3) if tot else 0.0

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
        "total": total,
        "offset": offset,
        "limit": limit,
        "query": q or None,
    }


@router.get("/novels/{novel_id}/progress")
def novel_progress(novel_id: str, db: Session = Depends(get_db)) -> dict:
    """整本的进度总览。**一次聚合，不逐章算。**

    几千章的书，逐章翻页去数「还有多少没译」是不现实的 ——
    而那恰恰是接手一本长篇时第一个要知道的数字。
    """
    _get_novel(db, novel_id)
    total = db.execute(
        select(func.count()).select_from(Chapter)
        .where(Chapter.novel_id == novel_id)
    ).scalar() or 0
    words = db.execute(
        select(func.coalesce(func.sum(Chapter.word_count), 0))
        .where(Chapter.novel_id == novel_id)
    ).scalar() or 0

    ch_ids = select(Chapter.id).where(Chapter.novel_id == novel_id)
    docs = db.execute(
        select(ScriptDoc.chapter_id).where(
            ScriptDoc.chapter_id.in_(ch_ids), ScriptDoc.status == DocStatus.active)
    ).scalars().all()
    doc_ids = select(ScriptDoc.id).where(
        ScriptDoc.chapter_id.in_(ch_ids), ScriptDoc.status == DocStatus.active)

    # 按语言分别统计译完的章数 —— 一本书可以同时译成几种语言，
    # 合在一起算会得到一个谁也用不上的平均数
    by_lang: dict[str, int] = {}
    for lang, cnt in db.execute(
        select(TranslationBlock.target_language_code,
               func.count(func.distinct(ScriptDoc.chapter_id)))
        .join(ScriptBlock, ScriptBlock.id == TranslationBlock.script_block_id)
        .join(ScriptDoc, ScriptDoc.id == ScriptBlock.script_doc_id)
        .where(ScriptDoc.chapter_id.in_(ch_ids),
               TranslationBlock.translated_text.isnot(None))
        .group_by(TranslationBlock.target_language_code)
    ).all():
        by_lang[lang] = cnt

    planned = db.execute(
        select(func.count(func.distinct(ShotPlan.script_doc_id)))
        .where(ShotPlan.script_doc_id.in_(doc_ids),
               ShotPlan.status == DocStatus.active)
    ).scalar() or 0

    return {
        "chapters": total, "words": words,
        "scripted": len(set(docs)),
        "translated_by_lang": by_lang,
        "shot_planned": planned,
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


class BulkDeleteIn(BaseModel):
    """按 id 或按章号区间删。两种都要有 —— 前者是在列表里勾选，
    后者是「把第 800 章之后的全删掉」，而后者在长篇里更常用。"""

    chapter_ids: list[str] = Field(default_factory=list)
    from_order: int | None = None
    to_order: int | None = None
    dry_run: bool = True


@router.post("/novels/{novel_id}/chapters:bulk-delete")
def bulk_delete_chapters(novel_id: str, body: BulkDeleteIn,
                         db: Session = Depends(get_db)) -> dict:
    """批量删章。**默认 dry_run** —— 删几百章不可恢复。

    衍生数据（剧本、块、译文、分镜）挂 chapter 外键 CASCADE，
    删章自动带走，不必也不该分别删。
    """
    _get_novel(db, novel_id)
    q = select(Chapter).where(Chapter.novel_id == novel_id)
    if body.chapter_ids:
        q = q.where(Chapter.id.in_(body.chapter_ids))
    if body.from_order is not None:
        q = q.where(Chapter.order_no >= body.from_order)
    if body.to_order is not None:
        q = q.where(Chapter.order_no <= body.to_order)
    if not body.chapter_ids and body.from_order is None and body.to_order is None:
        # 三个条件都空 = 删全部。**不接受** —— 那多半是前端漏传，
        # 而「整本删」有它自己的端点，走那条路时人知道自己在做什么
        raise HTTPException(
            status_code=400,
            detail="没有指定要删哪些章。整本删请用 DELETE /novels/{id}")

    rows = db.execute(q.order_by(Chapter.order_no)).scalars().all()
    sample = [{"order_no": c.order_no, "title": c.title} for c in rows[:10]]
    if body.dry_run:
        return {"dry_run": True, "count": len(rows), "sample": sample,
                "words": sum(c.word_count or 0 for c in rows)}

    ids = [c.id for c in rows]
    if ids:
        db.execute(delete(Chapter).where(Chapter.id.in_(ids)))
        db.flush()
    return {"dry_run": False, "deleted": len(ids), "sample": sample}


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
