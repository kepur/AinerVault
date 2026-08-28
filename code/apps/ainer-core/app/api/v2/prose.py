"""译本线 —— 先产出符合目标世界观的译本小说，再谈剧本。

    分块(规则) → 翻译(四层注入) → 规则闸 → LLM 二次审核 → 全书审计
    → 校对锁定 → 有声书

这条线不依赖剧本生成，也不产出分镜。译本的人名、名物、身份称谓
全部校对锁定之后，剧本线才有可信的地基。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import (
    Chapter, DocMode, DocStatus, Novel, ScriptDoc, TranslationBlock,
    TranslationBlockStatus, WorldTransform,
)
from app.models.world import TransformStatus
from app.pipelines import audiobook as ab
from app.pipelines import audit as audit_pipe
from app.pipelines import backcheck as bc_pipe
from app.pipelines import devices as dev_pipe
from app.pipelines import prose as prose_pipe
from app.pipelines import review as review_pipe
from app.pipelines.base import PipelineError

router = APIRouter(prefix="/api/v2", tags=["prose"])


def _chapter(db: Session, cid: str) -> Chapter:
    c = db.get(Chapter, cid)
    if c is None:
        raise HTTPException(status_code=404, detail="chapter not found")
    return c


def _transform(db: Session, tid: str) -> WorldTransform:
    t = db.get(WorldTransform, tid)
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
            status_code=409, detail=f"{lang} 没有 active 的世界观映射")
    return t


# ── 1. 分块 ───────────────────────────────────────────────────────────────────

class ProseIn(BaseModel):
    force: bool = False
    activate: bool = True


@router.post("/chapters/{chapter_id}/prose:build")
def build_prose(chapter_id: str, body: ProseIn,
                db: Session = Depends(get_db)) -> dict:
    """按段落切成译本块。纯规则，不调 LLM、零成本。"""
    c = _chapter(db, chapter_id)
    try:
        return prose_pipe.build_prose(
            db, c, activate=body.activate, force=body.force
        ).as_dict()
    except PipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/novels/{novel_id}/prose:build")
def build_prose_novel(novel_id: str, body: ProseIn,
                      db: Session = Depends(get_db)) -> dict:
    """整本书分块。"""
    if db.get(Novel, novel_id) is None:
        raise HTTPException(status_code=404, detail="novel not found")
    chapters = list(
        db.execute(
            select(Chapter).where(Chapter.novel_id == novel_id)
            .order_by(Chapter.order_no)
        ).scalars()
    )
    out, failed = [], []
    for c in chapters:
        try:
            r = prose_pipe.build_prose(db, c, activate=True, force=body.force)
            out.append({"chapter_id": c.id, "title": c.title, **r.as_dict()})
        except PipelineError as exc:
            failed.append({"chapter_id": c.id, "title": c.title, "error": str(exc)})
    return {
        "chapters": len(chapters), "built": len(out), "failed": failed,
        "blocks": sum(x["blocks"] for x in out),
        "dialogue": sum(x["dialogue"] for x in out),
        "items": out[:20],
    }


# ── 2. 译本读取 ───────────────────────────────────────────────────────────────

@router.get("/chapters/{chapter_id}/prose/{lang}")
def read_prose(chapter_id: str, lang: str,
               with_source: bool = Query(False),
               db: Session = Depends(get_db)) -> dict:
    """读译本。with_source=true 出双语对照。"""
    c = _chapter(db, chapter_id)
    try:
        return prose_pipe.render_translated(db, c, lang, with_source=with_source)
    except PipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/chapters/{chapter_id}/prose/{lang}/export")
def export_prose(chapter_id: str, lang: str,
                 fmt: str = Query("markdown", pattern="^(markdown|text)$"),
                 db: Session = Depends(get_db)) -> dict:
    """导出可读译本。"""
    c = _chapter(db, chapter_id)
    try:
        data = prose_pipe.render_translated(db, c, lang)
    except PipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    lines: list[str] = []
    for p in data["paragraphs"]:
        text = p["text"]
        if not text:
            continue
        if p["type"] == "heading":
            lines.append(f"## {text}" if fmt == "markdown" else text)
        else:
            lines.append(text)
    body = "\n\n".join(lines)
    title = data["chapter_title"] or ""
    if fmt == "markdown" and title:
        body = f"# {title}\n\n{body}"
    return {
        "chapter_id": chapter_id, "language": lang, "format": fmt,
        "title": title, "content": body,
        "stats": data["stats"],
    }


# ── 3. LLM 二次审核 ───────────────────────────────────────────────────────────

class ReviewIn(BaseModel):
    transform_id: str | None = None
    language: str | None = None
    batch_size: int = 12
    max_blocks: int | None = None


@router.post("/chapters/{chapter_id}/prose:review")
def review_prose(chapter_id: str, body: ReviewIn,
                 db: Session = Depends(get_db)) -> dict:
    """译本二次审核。抓规则闸抓不到的漏洞：

    音译残留（林凡→Lin Fan 而非 Mason）、名物没转译（刀剑保留 dao/jian）、
    身份称谓不符（剑客直译成 sword guest）、语体错位、时代不符。
    """
    c = _chapter(db, chapter_id)
    t = (
        _transform(db, body.transform_id) if body.transform_id
        else _active_transform(db, c.novel_id, body.language or "en-US")
    )
    try:
        return review_pipe.review_translation(
            db, c, t, batch_size=body.batch_size, max_blocks=body.max_blocks
        ).as_dict()
    except PipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ── 3.5 叙事装置与回译校验 ─────────────────────────────────────────────────────

class DeviceIn(BaseModel):
    batch_size: int = 14


@router.post("/chapters/{chapter_id}/devices:extract")
def extract_devices(chapter_id: str, body: DeviceIn,
                    db: Session = Depends(get_db)) -> dict:
    """抽离叙事装置 —— 笑点、泪点、反转的「机制」。

    跨文化改编真正会丢的不是词，是效果。抽机制而非文本，
    重写时才能在目标文化里重造出同样的反应。
    """
    c = _chapter(db, chapter_id)
    try:
        return dev_pipe.extract_devices(db, c, batch_size=body.batch_size).as_dict()
    except PipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/chapters/{chapter_id}/devices")
def list_devices(chapter_id: str, db: Session = Depends(get_db)) -> dict:
    from app.models import NarrativeDevice

    _chapter(db, chapter_id)
    rows = list(
        db.execute(
            select(NarrativeDevice).where(NarrativeDevice.chapter_id == chapter_id)
            .order_by(NarrativeDevice.intensity.desc())
        ).scalars()
    )
    items = [
        {
            "id": d.id, "block_id": d.block_id,
            "device_type": d.device_type.value, "effect": d.effect.value,
            "cultural_load": d.cultural_load.value, "strategy": d.strategy.value,
            "source_text": d.source_text, "mechanism": d.mechanism,
            "setup": d.setup, "punch": d.punch, "intensity": d.intensity,
            "depends_on": d.depends_on or [],
            "target_plan": d.target_plan,
            "landed": d.landed, "landed_note": d.landed_note,
        }
        for d in rows
    ]
    by_load: dict[str, int] = {}
    for d in rows:
        by_load[d.cultural_load.value] = by_load.get(d.cultural_load.value, 0) + 1
    return {
        "items": items,
        "stats": {
            "total": len(rows), "by_load": by_load,
            "high_intensity": sum(1 for d in rows if d.intensity >= 4),
            "landed": sum(1 for d in rows if d.landed is True),
            "lost": sum(1 for d in rows if d.landed is False),
        },
    }


class BackCheckIn(BaseModel):
    transform_id: str | None = None
    language: str | None = None
    max_blocks: int | None = None
    pass_threshold: float = 0.9


@router.post("/chapters/{chapter_id}/prose:back-check")
def back_check(chapter_id: str, body: BackCheckIn,
               db: Session = Depends(get_db)) -> dict:
    """回译校验：把译文回译成源语言，与骨架逐点比对。

    译文读着通顺不代表情节没丢。改编模式允许调整句式，
    模型可能为了顺畅悄悄抹掉一个情节点，而译文毫无破绽 ——
    只有回译比对能查出来。
    """
    c = _chapter(db, chapter_id)
    t = (
        _transform(db, body.transform_id) if body.transform_id
        else _active_transform(db, c.novel_id, body.language or "en-US")
    )
    try:
        return bc_pipe.back_check(
            db, c, t, max_blocks=body.max_blocks,
            pass_threshold=body.pass_threshold,
        ).as_dict()
    except PipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ── 4. 全书审计 ───────────────────────────────────────────────────────────────

@router.get("/transforms/{transform_id}/audit")
def audit(transform_id: str, db: Session = Depends(get_db)) -> dict:
    """全书一致性审计。单章看不出的问题跨章才现形：

    主角在第 1 章叫 Mason、第 7 章又变回 Lin Fan，逐章审核时每章都自洽。
    不调 LLM —— 一致性是可枚举的事实，规则查更快也更准。
    """
    t = _transform(db, transform_id)
    try:
        return audit_pipe.audit_novel(db, t).as_dict()
    except PipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ── 5. 校对锁定 ───────────────────────────────────────────────────────────────

class LockIn(BaseModel):
    block_ids: list[str] = Field(default_factory=list)
    language: str
    only_reviewed: bool = False


@router.post("/chapters/{chapter_id}/prose:lock")
def lock_prose(chapter_id: str, body: LockIn,
               db: Session = Depends(get_db)) -> dict:
    """锁定校对完的译文。锁定后任何重译都不会覆盖。"""
    c = _chapter(db, chapter_id)
    doc = prose_pipe.active_prose_doc(db, c.id)
    if doc is None:
        raise HTTPException(status_code=422, detail="该章节还没有译本分块")

    from app.models import ScriptBlock

    ids = body.block_ids or [
        b.id for b in db.execute(
            select(ScriptBlock).where(ScriptBlock.script_doc_id == doc.id)
        ).scalars()
    ]
    rows = list(
        db.execute(
            select(TranslationBlock).where(
                TranslationBlock.script_block_id.in_(ids),
                TranslationBlock.target_language_code == body.language,
            )
        ).scalars()
    )
    locked = skipped = 0
    for r in rows:
        if not (r.translated_text or "").strip():
            skipped += 1
            continue
        if body.only_reviewed and r.status != TranslationBlockStatus.reviewed:
            skipped += 1
            continue
        r.locked = True
        r.status = TranslationBlockStatus.locked
        locked += 1
    db.flush()
    return {"locked": locked, "skipped": skipped, "total": len(rows)}


# ── 6. 有声书 ─────────────────────────────────────────────────────────────────

class AudiobookIn(BaseModel):
    transform_id: str | None = None
    language: str | None = None


@router.post("/chapters/{chapter_id}/audiobook:compile")
def compile_audiobook(chapter_id: str, body: AudiobookIn,
                      db: Session = Depends(get_db)) -> dict:
    """把译本编译成有声书音频规格。音色与分镜共用同一套 voice 素材。"""
    c = _chapter(db, chapter_id)
    t = (
        _transform(db, body.transform_id) if body.transform_id
        else _active_transform(db, c.novel_id, body.language or "en-US")
    )
    try:
        return ab.compile_audiobook(db, c, t).as_dict()
    except PipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class AudiobookGenIn(BaseModel):
    regenerate: bool = False
    confirm_cost: bool = False


@router.post("/chapters/{chapter_id}/audiobook:generate")
def generate_audiobook(chapter_id: str, body: AudiobookGenIn,
                       db: Session = Depends(get_db)) -> dict:
    """提交有声书 TTS。"""
    c = _chapter(db, chapter_id)
    return ab.generate_audiobook(
        db, c, regenerate=body.regenerate, confirm_cost=body.confirm_cost
    ).as_dict()


@router.get("/chapters/{chapter_id}/audiobook")
def get_audiobook(chapter_id: str, db: Session = Depends(get_db)) -> dict:
    """章节音频时间轴。交付给拼接工具，本系统不做音频合成。"""
    c = _chapter(db, chapter_id)
    try:
        return ab.build_timeline(db, c)
    except PipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ── 就绪度 ────────────────────────────────────────────────────────────────────

@router.get("/chapters/{chapter_id}/prose/{lang}/status")
def prose_status(chapter_id: str, lang: str,
                 db: Session = Depends(get_db)) -> dict:
    """译本线的进度与下一步。"""
    c = _chapter(db, chapter_id)
    doc = prose_pipe.active_prose_doc(db, c.id)
    if doc is None:
        return {"stage": "not_started", "next_step": "执行 prose:build 切分译本块"}

    data = prose_pipe.render_translated(db, c, lang)
    st = data["stats"]
    t = db.execute(
        select(WorldTransform).where(
            WorldTransform.novel_id == c.novel_id,
            WorldTransform.target_language_code == lang,
            WorldTransform.status == TransformStatus.active,
        )
    ).scalars().first()

    open_high = 0
    if t is not None:
        from app.models import Severity, ViolationStatus, WorldViolation
        from sqlalchemy import func

        open_high = int(db.execute(
            select(func.count()).select_from(WorldViolation).where(
                WorldViolation.transform_id == t.id,
                WorldViolation.status == ViolationStatus.open,
                WorldViolation.severity == Severity.high,
            )
        ).scalar_one())

    specs = ab._chapter_specs(db, c)
    voiced = sum(1 for s in specs if s.asset_id)

    if st["translated"] == 0:
        nxt = f"翻译：POST /chapters/{c.id}/translation/{lang}:run"
    elif t is None:
        nxt = "创建并激活世界观映射"
    elif open_high:
        nxt = f"处理 {open_high} 条高危违规"
    elif st["locked"] < st["translated"]:
        nxt = "审核后锁定译文：prose:lock"
    elif not specs:
        nxt = "编译有声书：audiobook:compile"
    elif voiced < len(specs):
        nxt = "生成有声书音频：audiobook:generate"
    else:
        nxt = "译本与有声书均已就绪"

    return {
        "stage": "in_progress",
        "blocks": st["blocks"], "translated": st["translated"],
        "locked": st["locked"], "coverage": st["coverage"],
        "open_high_violations": open_high,
        "audiobook": {"segments": len(specs), "generated": voiced},
        "next_step": nxt,
    }
