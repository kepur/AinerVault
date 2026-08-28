"""文化差异审查：模型出报表，人来拍板。

和 review.py 的分工：那套查**违规**（音译残留、名物没换、锁定译名没用上），
能机器判定对错，所以可以自动修。这套查**差异** —— 原文的读者会笑、
译文的读者不会；「师父」二字带的敬意 Master 承载不了。这些没有对错只有判断，
所以只提方案不落地，等人裁决。

审查的问法很关键：不问「翻得对不对」，问**「两边的读者各自得到了什么」**。
问对不对，模型会去比对字面，然后告诉你「忠实准确」；
问读者得到什么，它才会去想那句话在两个文化里各自激起什么反应 ——
落差就是要找的东西。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ids import new_id
from app.models import (
    Chapter, CultureFinding, CultureReview, GapKind, ReviewRunStatus, ScriptBlock,
    TranslationBlock, Verdict, WorldProfile, WorldTransform,
)
from app.pipelines.base import PipelineError, chat_json
from app.pipelines.prose import active_prose_doc

log = logging.getLogger(__name__)

FIX_CHANNELS = ("lexicon", "appellation", "meme", "device", "retranslate", "manual")

SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["findings", "fidelity_score", "summary"],
    "properties": {
        "fidelity_score": {"type": "integer"},
        "summary": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["block_id", "kind", "severity", "source_effect",
                             "target_effect", "gap_explain"],
                "properties": {
                    "block_id": {"type": "string"},
                    "kind": {"type": "string", "enum": [k.value for k in GapKind]},
                    "severity": {"type": "integer"},
                    "source_effect": {"type": "string"},
                    "target_effect": {"type": "string"},
                    "gap_explain": {"type": "string"},
                    "proposal": {"type": "string"},
                    "proposed_text": {"type": "string"},
                    "fix_channel": {"type": "string", "enum": list(FIX_CHANNELS)},
                },
            },
        },
    },
}

SYSTEM = """你是跨文化改编的终审。你要回答的不是「翻得对不对」，
而是**「两边的读者各自得到了什么，差在哪」**。

对每个段落，先分别想清楚两件事：
  source_effect  中文读者读到这一句，得到什么？笑？紧张？听出言外之意？
                 感到亲近或轻蔑？还是只是接收了一条信息？
  target_effect  目标读者读到译文，实际得到什么？
落差就是 finding。两边一样就不要写 —— 报表里塞满「翻译准确」等于没审。

十二类差异：
  humor_lost           笑点没了
  emotion_flattened    情绪被抹平，信息在、感觉没了
  register_mismatch    语体错位，该庄重的口语化了或反之
  relation_lost        人物关系的亲疏没传达出来
  subtext_lost         言外之意丢失，只剩字面
  allusion_opaque      典故目标读者读不懂，成了一句没来由的话
  meme_untranslated    梗直译了，字面通顺但没人 get
  cultural_assumption  依赖源文化常识，目标读者缺前提
  anachronism          用了目标世界观年代不该有的词或物
  taboo_shift          禁忌尺度错位，源文可说的在目标文化里冒犯
  pacing_shift         节奏变了，长句拖垮了原文的短促
  overtranslation      过度解释，把该留白的说破了

severity 1–5：
  5 目标读者会明显觉得不对劲，或直接读错意思
  3 体验有损但不至于出戏
  1 吹毛求疵

**overtranslation 要认真查。** 大多数审查只会说「不够充分」，
于是每一轮都加解释，几轮下来译文比原文长一半，全是把留白说破的句子。
原文没说的话，译文也不该说。

每条给 proposal（怎么改）和 proposed_text（改完那句长什么样，可直接采用）。
proposal 不要写「建议优化表达」这种没有信息量的话 ——
要说清楚改什么、为什么这样改能补回那个落差。

fix_channel 指出该由哪条管线去修：
  lexicon 名物词表　appellation 称呼表　meme 梗表
  device 叙事装置　retranslate 整段重译　manual 只能人工

fidelity_score 0–100：不是翻译准确度，是「目标读者拿到的阅读体验」
相对原文的还原度。准确但味同嚼蜡的译本应该低分。"""


@dataclass
class ReviewOut:
    review_id: str = ""
    findings: int = 0
    fidelity_score: int | None = None
    summary: str = ""
    by_kind: dict[str, int] = field(default_factory=dict)
    top: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "review_id": self.review_id, "findings": self.findings,
            "fidelity_score": self.fidelity_score, "summary": self.summary,
            "by_kind": self.by_kind, "top": self.top,
        }


def run_review(
    db: Session, chapter: Chapter, transform: WorldTransform, *,
    batch_size: int = 12, tier: str | None = None,
) -> ReviewOut:
    """对一章跑文化差异审查。"""
    doc = active_prose_doc(db, chapter.id)
    if doc is None:
        raise PipelineError("该章节还没有译本分块")

    src = db.get(WorldProfile, transform.source_profile_id)
    tgt = db.get(WorldProfile, transform.target_profile_id)
    if src is None or tgt is None:
        raise PipelineError("world profile 缺失")

    blocks = list(
        db.execute(
            select(ScriptBlock).where(ScriptBlock.script_doc_id == doc.id)
            .order_by(ScriptBlock.seq_no)
        ).scalars()
    )
    trans = {
        t.script_block_id: t
        for t in db.execute(
            select(TranslationBlock).where(
                TranslationBlock.script_block_id.in_([b.id for b in blocks]),
                TranslationBlock.transform_id == transform.id,
            )
        ).scalars()
    }
    pairs = [
        (b, trans[b.id].translated_text)
        for b in blocks
        if b.id in trans and (trans[b.id].translated_text or "").strip()
    ]
    if not pairs:
        raise PipelineError("这一章还没有译文，先翻译再审查")

    review = CultureReview(
        id=new_id("cv"), chapter_id=chapter.id, transform_id=transform.id,
        tier=tier or "critical",
    )
    db.add(review)
    db.flush()

    out = ReviewOut(review_id=review.id)
    scores: list[int] = []
    summaries: list[str] = []

    try:
        for i in range(0, len(pairs), batch_size):
            batch = pairs[i : i + batch_size]
            data, task = chat_json(
                db,
                [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": (
                        f"【源世界观】{src.display_name}\n"
                        f"【目标世界观】{tgt.display_name}"
                        f"（{(tgt.axes_json or {}).get('era_span')}）\n"
                        f"【目标语言】{transform.target_language_code}\n\n"
                        + json.dumps(
                            {"pairs": [
                                {"block_id": b.id, "type": b.block_type.value,
                                 "speaker": b.speaker_tag,
                                 "source": b.source_text, "target": t}
                                for b, t in batch
                            ]}, ensure_ascii=False, indent=1)
                    )},
                ],
                SCHEMA,
                purpose="culture_review", tier=tier,
                novel_id=chapter.novel_id, chapter_id=chapter.id,
                ref_kind="culture_review", ref_id=review.id,
            )
            review.model = task.model or review.model
            if isinstance(data.get("fidelity_score"), int):
                scores.append(int(data["fidelity_score"]))
            if data.get("summary"):
                summaries.append(str(data["summary"]))
            _absorb(db, review, batch, data.get("findings") or [], out)
    except Exception as exc:
        review.status = ReviewRunStatus.failed
        review.error_json = {"message": str(exc)[:500]}
        db.flush()
        raise

    review.status = ReviewRunStatus.completed
    review.findings_total = out.findings
    review.by_kind_json = out.by_kind
    review.fidelity_score = round(sum(scores) / len(scores)) if scores else None
    review.verdict_summary = "\n".join(summaries)[:4000] or None
    out.fidelity_score = review.fidelity_score
    out.summary = review.verdict_summary or ""
    out.top = sorted(out.top, key=lambda x: -x["severity"])[:10]
    db.flush()
    return out


def _absorb(
    db: Session, review: CultureReview, batch: list, items: list[dict],
    out: ReviewOut,
) -> None:
    valid = {b.id for b, _ in batch}
    for item in items:
        bid = str(item.get("block_id") or "")
        if bid not in valid:
            continue
        try:
            kind = GapKind(item.get("kind") or "")
        except ValueError:
            continue
        gap = str(item.get("gap_explain") or "").strip()
        if not gap:
            continue
        sev = max(1, min(5, int(item.get("severity") or 3)))
        block, target = next((b, t) for b, t in batch if b.id == bid)
        channel = str(item.get("fix_channel") or "")
        db.add(CultureFinding(
            id=new_id("cf"), review_id=review.id, block_id=bid, kind=kind,
            severity=sev,
            source_excerpt=(block.source_text or "")[:600],
            target_excerpt=(target or "")[:600],
            source_effect=(item.get("source_effect") or "").strip()[:1000] or None,
            target_effect=(item.get("target_effect") or "").strip()[:1000] or None,
            gap_explain=gap[:2000],
            proposal=(item.get("proposal") or "").strip()[:2000] or None,
            proposed_text=(item.get("proposed_text") or "").strip()[:2000] or None,
            fix_channel=channel if channel in FIX_CHANNELS else None,
            verdict=Verdict.pending,
        ))
        out.findings += 1
        out.by_kind[kind.value] = out.by_kind.get(kind.value, 0) + 1
        out.top.append({
            "kind": kind.value, "severity": sev,
            "source": (block.source_text or "")[:50],
            "gap": gap[:100],
        })


def apply_verdicts(
    db: Session, review: CultureReview, *, only_ids: list[str] | None = None,
) -> dict[str, Any]:
    """把裁决过的方案落到译文。

    只处理 accepted / modified / supplemented，且 applied 为假的。
    driven 由人的裁决决定用哪段文本：
        accepted      用模型的 proposed_text
        modified      用人写的 human_text —— 人改过就以人为准
        supplemented  也用 human_text，人补充后的完整版本
    没有可用文本的（比如只写了意见没写句子）跳过并报出来 ——
    静默略过会让人以为改上去了。
    """
    q = select(CultureFinding).where(
        CultureFinding.review_id == review.id,
        CultureFinding.applied.is_(False),
        CultureFinding.verdict.in_(
            [Verdict.accepted, Verdict.modified, Verdict.supplemented]
        ),
    )
    if only_ids:
        q = q.where(CultureFinding.id.in_(only_ids))
    rows = list(db.execute(q).scalars())
    if not rows:
        return {"applied": 0, "skipped": [], "locked": 0}

    blocks = {
        t.script_block_id: t
        for t in db.execute(
            select(TranslationBlock).where(
                TranslationBlock.script_block_id.in_(
                    [r.block_id for r in rows if r.block_id]
                ),
                TranslationBlock.transform_id == review.transform_id,
            )
        ).scalars()
    }

    applied = locked = 0
    skipped: list[dict] = []
    for r in rows:
        text = (
            r.proposed_text if r.verdict is Verdict.accepted
            else (r.human_text or r.proposed_text)
        )
        text = (text or "").strip()
        if not text:
            skipped.append({"finding_id": r.id, "reason": "没有可用的替换文本"})
            continue
        tb = blocks.get(r.block_id or "")
        if tb is None:
            skipped.append({"finding_id": r.id, "reason": "找不到对应译文块"})
            continue
        if tb.locked:
            # 锁定的块是人工校对过的，审查方案不该越过它
            locked += 1
            skipped.append({"finding_id": r.id, "reason": "该块已锁定，未覆盖"})
            continue
        tb.translated_text = text
        note = (r.human_note or r.proposal or "").strip()
        if note:
            tb.translation_notes = f"[文化审查] {note}"[:2000]
        r.applied = True
        applied += 1

    review.resolved_total = (review.resolved_total or 0) + applied
    db.flush()
    return {"applied": applied, "skipped": skipped, "locked": locked}
