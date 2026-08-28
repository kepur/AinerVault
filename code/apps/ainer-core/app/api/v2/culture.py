"""文化层 API：梗表、梗渲染、文化差异审查与人工裁决。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import (
    Chapter, CultureFinding, CultureReview, DeviceStrategy, MemeEntry,
    MemeRendering, ReviewStatus, TransformStatus, Verdict, Volatility,
    WorldTransform,
)
from app.pipelines import culture_review as cr_pipe
from app.pipelines import memes as meme_pipe
from app.pipelines.base import PipelineError

router = APIRouter(prefix="/api/v2", tags=["culture"])


def _chapter(db: Session, cid: str) -> Chapter:
    c = db.get(Chapter, cid)
    if c is None:
        raise HTTPException(status_code=404, detail="chapter not found")
    return c


def _transform(db: Session, novel_id: str, lang: str) -> WorldTransform:
    t = db.execute(
        select(WorldTransform).where(
            WorldTransform.novel_id == novel_id,
            WorldTransform.target_language_code == lang,
            WorldTransform.status == TransformStatus.active,
        ).order_by(WorldTransform.version.desc())
    ).scalars().first()
    if t is None:
        raise HTTPException(status_code=409, detail=f"{lang} 没有 active 的世界观映射")
    return t


# ── 文化梗 ────────────────────────────────────────────────────────────────────

class ExtractIn(BaseModel):
    batch_size: int = 16


@router.post("/chapters/{chapter_id}/memes:extract")
def extract_memes(chapter_id: str, body: ExtractIn,
                  db: Session = Depends(get_db)) -> dict:
    """抽文化梗。字面义与实际用法脱节的表达 —— 直译必错的那一类。"""
    c = _chapter(db, chapter_id)
    try:
        return meme_pipe.extract_memes(db, c, batch_size=body.batch_size).as_dict()
    except PipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class RenderIn(BaseModel):
    limit: int = 40


@router.post("/transforms/{transform_id}/memes:render")
def render_memes(transform_id: str, body: RenderIn,
                 db: Session = Depends(get_db)) -> dict:
    """为目标圈层定每个梗的呈现方式（九档策略）。"""
    t = db.get(WorldTransform, transform_id)
    if t is None:
        raise HTTPException(status_code=404, detail="transform not found")
    try:
        return meme_pipe.render_memes(db, t, limit=body.limit).as_dict()
    except PipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/novels/{novel_id}/memes")
def list_memes(novel_id: str, transform_id: str | None = None,
               db: Session = Depends(get_db)) -> dict:
    """梗表。带 transform_id 时一并给出该圈层的呈现方式。"""
    memes = list(db.execute(
        select(MemeEntry).where(MemeEntry.novel_id == novel_id)
        .order_by(MemeEntry.occurrences.desc())
    ).scalars())
    renders: dict[str, MemeRendering] = {}
    if transform_id:
        t = db.get(WorldTransform, transform_id)
        if t is not None:
            renders = {
                r.meme_id: r
                for r in db.execute(
                    select(MemeRendering).where(
                        MemeRendering.world_profile_id == t.target_profile_id
                    )
                ).scalars()
            }
    items = []
    for m in memes:
        r = renders.get(m.id)
        items.append({
            "id": m.id, "surface": m.surface, "register": m.register.value,
            "literal_gloss": m.literal_gloss, "actual_use": m.actual_use,
            "origin": m.origin, "circle": m.circle, "platform": m.platform,
            "volatility": m.volatility.value, "plot_load": m.plot_load.value,
            "occurrences": m.occurrences, "locked": m.locked,
            "rendering": None if r is None else {
                "id": r.id, "strategy": r.strategy.value,
                "target_text": r.target_text, "gloss_text": r.gloss_text,
                "rationale": r.rationale, "candidates": r.candidates_json or [],
                "target_volatility": (
                    r.target_volatility.value if r.target_volatility else None
                ),
                "status": r.status.value, "locked": r.locked,
            },
        })
    return {
        "total": len(items),
        "unrendered": sum(1 for i in items if not i["rendering"]),
        "high_risk": sum(
            1 for i in items if i["plot_load"] in ("setup", "pivot")
        ),
        "items": items,
    }


class RenderPatch(BaseModel):
    strategy: str | None = None
    target_text: str | None = None
    gloss_text: str | None = None
    locked: bool | None = None


@router.patch("/meme-renderings/{rendering_id}")
def update_rendering(rendering_id: str, body: RenderPatch,
                     db: Session = Depends(get_db)) -> dict:
    """人工定稿一条梗的呈现。改过即锁。"""
    r = db.get(MemeRendering, rendering_id)
    if r is None:
        raise HTTPException(status_code=404, detail="rendering not found")
    if body.strategy is not None:
        try:
            r.strategy = DeviceStrategy(body.strategy)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail=f"未知策略 {body.strategy}"
            ) from exc
    if body.target_text is not None:
        r.target_text = body.target_text.strip() or None
    if body.gloss_text is not None:
        r.gloss_text = body.gloss_text.strip() or None
    r.status = ReviewStatus.approved
    r.locked = True if body.locked is None else body.locked
    db.flush()
    return {"id": r.id, "strategy": r.strategy.value,
            "target_text": r.target_text, "gloss_text": r.gloss_text,
            "locked": r.locked}


# ── 文化差异审查 ──────────────────────────────────────────────────────────────

class CultureReviewIn(BaseModel):
    batch_size: int = 12
    #: 覆盖档位。不传按 purpose 默认（culture_review → critical）
    tier: str | None = None


@router.post("/chapters/{chapter_id}/culture-review/{lang}:run")
def run_culture_review(chapter_id: str, lang: str, body: CultureReviewIn,
                       db: Session = Depends(get_db)) -> dict:
    """跑文化差异审查。出报表，不改译文 —— 落地要等人裁决。"""
    c = _chapter(db, chapter_id)
    t = _transform(db, c.novel_id, lang)
    try:
        return cr_pipe.run_review(
            db, c, t, batch_size=body.batch_size, tier=body.tier
        ).as_dict()
    except PipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/chapters/{chapter_id}/culture-reviews")
def list_reviews(chapter_id: str, db: Session = Depends(get_db)) -> dict:
    _chapter(db, chapter_id)
    rows = list(db.execute(
        select(CultureReview).where(CultureReview.chapter_id == chapter_id)
        .order_by(CultureReview.created_at.desc()).limit(20)
    ).scalars())
    return {"items": [
        {"id": r.id, "status": r.status.value, "tier": r.tier, "model": r.model,
         "fidelity_score": r.fidelity_score, "findings": r.findings_total,
         "resolved": r.resolved_total, "by_kind": r.by_kind_json or {},
         "summary": r.verdict_summary,
         "created_at": r.created_at.isoformat() if r.created_at else None}
        for r in rows
    ]}


@router.get("/culture-reviews/{review_id}")
def get_review(review_id: str, db: Session = Depends(get_db)) -> dict:
    """报表全文：每条差异 + 模型方案 + 当前裁决。"""
    r = db.get(CultureReview, review_id)
    if r is None:
        raise HTTPException(status_code=404, detail="review not found")
    rows = list(db.execute(
        select(CultureFinding).where(CultureFinding.review_id == review_id)
        .order_by(CultureFinding.severity.desc())
    ).scalars())
    return {
        "id": r.id, "chapter_id": r.chapter_id, "transform_id": r.transform_id,
        "status": r.status.value, "tier": r.tier, "model": r.model,
        "fidelity_score": r.fidelity_score, "summary": r.verdict_summary,
        "by_kind": r.by_kind_json or {},
        "findings_total": r.findings_total, "resolved_total": r.resolved_total,
        "pending": sum(1 for x in rows if x.verdict is Verdict.pending),
        "findings": [
            {
                "id": f.id, "block_id": f.block_id, "kind": f.kind.value,
                "severity": f.severity,
                "source": f.source_excerpt, "target": f.target_excerpt,
                "source_effect": f.source_effect, "target_effect": f.target_effect,
                "gap": f.gap_explain,
                "proposal": f.proposal, "proposed_text": f.proposed_text,
                "fix_channel": f.fix_channel,
                "verdict": f.verdict.value, "human_text": f.human_text,
                "human_note": f.human_note, "applied": f.applied,
            }
            for f in rows
        ],
    }


class VerdictIn(BaseModel):
    verdict: str = Field(description="accepted | modified | supplemented | rejected")
    human_text: str | None = None
    human_note: str | None = None


@router.patch("/culture-findings/{finding_id}")
def judge(finding_id: str, body: VerdictIn, db: Session = Depends(get_db)) -> dict:
    """人工裁决一条。

    modified / supplemented 必须给 human_text —— 没有文本的「已修改」
    在应用时会被静默跳过，人却以为改上去了。
    """
    f = db.get(CultureFinding, finding_id)
    if f is None:
        raise HTTPException(status_code=404, detail="finding not found")
    try:
        v = Verdict(body.verdict)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"裁决只能是 {[x.value for x in Verdict]}"
        ) from exc
    if v in (Verdict.modified, Verdict.supplemented) and not (
        body.human_text or "").strip():
        raise HTTPException(
            status_code=400,
            detail=f"裁决为 {v.value} 时必须给出 human_text，否则应用时无文本可用",
        )
    f.verdict = v
    if body.human_text is not None:
        f.human_text = body.human_text.strip() or None
    if body.human_note is not None:
        f.human_note = body.human_note.strip() or None
    db.flush()
    return {"id": f.id, "verdict": f.verdict.value,
            "human_text": f.human_text, "applied": f.applied}


class ApplyIn(BaseModel):
    finding_ids: list[str] = Field(default_factory=list)


@router.post("/culture-reviews/{review_id}:apply")
def apply_review(review_id: str, body: ApplyIn,
                 db: Session = Depends(get_db)) -> dict:
    """把裁决过的方案落到译文。锁定的块不覆盖。"""
    r = db.get(CultureReview, review_id)
    if r is None:
        raise HTTPException(status_code=404, detail="review not found")
    return cr_pipe.apply_verdicts(db, r, only_ids=body.finding_ids or None)
