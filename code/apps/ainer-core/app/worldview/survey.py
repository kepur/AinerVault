"""世界观勘探：翻译前找出所有需要转译的词，交给人审核。

三层递进，成本递增、覆盖递增：
  1 模板层  预置词表 Aho–Corasick 扫描，命中即高置信候选。零 LLM 成本
  2 挖掘层  统计新词发现筛出真词，再批量交 LLM 判定语义与译法
  3 RAG 层  前两层都不确定的，检索目标世界观 KB 补候选（P0.6 后续）

审核发生在这一层的产物上 —— 审几百条词表，管全书几十万字，
而不是审几万个翻译块。这是成本与心智的数量级差异。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ids import new_id
from app.models import (
    Chapter, LexiconCategory, LexiconSource, ReviewStatus, ScriptBlock, ScriptDoc,
    DocStatus, WorldLexicon, WorldLexiconTemplate, WorldProfile, WorldTransform, utcnow,
)
from app.pipelines.base import PipelineError, chat_json
from app.worldview.matcher import LexiconMatcher
from app.worldview.mining import mine_candidates

log = logging.getLogger(__name__)


# ── 导入预置模板 ───────────────────────────────────────────────────────────────

@dataclass
class ImportResult:
    created: int = 0
    skipped: int = 0
    pair_code: str = ""
    entries: list[str] = field(default_factory=list)


def import_template(
    db: Session, transform: WorldTransform, pair_code: str, *,
    status: ReviewStatus = ReviewStatus.candidate,
) -> ImportResult:
    """把预置词表导入到某个 transform。已存在的 source_term 跳过，不覆盖人工修改。"""
    tpl = db.execute(
        select(WorldLexiconTemplate)
        .where(WorldLexiconTemplate.pair_code == pair_code)
        .order_by(WorldLexiconTemplate.version.desc())
    ).scalars().first()
    if tpl is None:
        raise PipelineError(f"预置词表 {pair_code} 不存在")

    existing = {
        row.source_term
        for row in db.execute(
            select(WorldLexicon).where(WorldLexicon.transform_id == transform.id)
        ).scalars()
    }

    out = ImportResult(pair_code=pair_code)
    for entry in tpl.entries_json or []:
        src = entry.get("source_term")
        if not src or src in existing:
            out.skipped += 1
            continue
        try:
            category = LexiconCategory(entry.get("category") or "other")
        except ValueError:
            category = LexiconCategory.other

        db.add(WorldLexicon(
            id=new_id("lx"),
            transform_id=transform.id,
            canonical_key=entry.get("canonical_key") or f"other.{src}",
            category=category,
            source_term=src,
            source_aliases=entry.get("source_aliases") or [],
            target_term=entry.get("target_term") or "",
            target_reading=entry.get("target_reading"),
            forbidden_targets=entry.get("forbidden_targets") or [],
            status=status,
            confidence=0.95,
            rationale=entry.get("rationale") or None,
            source=LexiconSource.template,
            evidence_json={"template": pair_code},
        ))
        existing.add(src)
        out.created += 1
        out.entries.append(src)

    db.flush()
    return out


def default_pair_code(db: Session, transform: WorldTransform) -> str | None:
    src = db.get(WorldProfile, transform.source_profile_id)
    tgt = db.get(WorldProfile, transform.target_profile_id)
    if not src or not tgt:
        return None
    tpl = db.execute(
        select(WorldLexiconTemplate).where(
            WorldLexiconTemplate.source_profile_code == src.code,
            WorldLexiconTemplate.target_profile_code == tgt.code,
        )
    ).scalars().first()
    return tpl.pair_code if tpl else None


# ── 勘探 ──────────────────────────────────────────────────────────────────────

@dataclass
class SurveyResult:
    scanned_blocks: int = 0
    template_hits: dict[str, int] = field(default_factory=dict)
    mined_created: int = 0
    mined_terms: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "scanned_blocks": self.scanned_blocks,
            "template_hits": self.template_hits,
            "hit_terms": len(self.template_hits),
            "mined_created": self.mined_created,
            "mined_terms": self.mined_terms,
            "unresolved": self.unresolved,
        }


MINE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["terms"],
    "properties": {
        "terms": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["source_term", "category", "target_term", "rationale"],
                "properties": {
                    "source_term": {"type": "string"},
                    "canonical_key": {"type": "string"},
                    "category": {
                        "type": "string",
                        "enum": [c.value for c in LexiconCategory],
                    },
                    "target_term": {"type": "string"},
                    "target_reading": {"type": "string"},
                    "forbidden_targets": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "number"},
                    "rationale": {"type": "string"},
                },
            },
        }
    },
}

MINE_SYSTEM = """你是跨文化改编的名物考据专家。

任务：从原文中找出【名物词】—— 那些直译会破坏目标世界观真实感的词。

必须找的：
  场所(place)、职官(office)、头衔(title)、称谓(honorific)、服饰(garment)、
  饮食(food)、货币(currency)、兵器(weapon)、交通(vehicle)、建筑(architecture)、
  度量(measure)、风俗(custom)、礼仪(ritual)、势力(faction)

不要找的：
  人名、地名专名（这些走实体命名，不走名物词表）
  通用词（门、人、水、走、看）
  已在【已有词表】中出现的词

对每个词给出目标世界观下的地道说法，并说明依据。
关键原则：目标世界观里没有对应物时（如中世纪欧洲没有茶），
回退到功能等价的上位概念，而不是直译成一个时代外的词。

forbidden_targets 填「绝不能出现在译文里的错误译法」，
通常是直译词与原文词本身。"""


def _collect_blocks(db: Session, chapter: Chapter) -> list[ScriptBlock]:
    doc = db.execute(
        select(ScriptDoc).where(
            ScriptDoc.chapter_id == chapter.id, ScriptDoc.status == DocStatus.active
        )
    ).scalars().first()
    if doc is None:
        return []
    return list(
        db.execute(
            select(ScriptBlock)
            .where(ScriptBlock.script_doc_id == doc.id)
            .order_by(ScriptBlock.seq_no)
        ).scalars()
    )


def _candidate_tokens(texts: list[str], covered: set[str], top_n: int) -> list[tuple[str, int]]:
    """挑出送 LLM 判定的候选词。

    用统计新词发现（凝固度 + 左右邻接熵）而非朴素频次切分 ——
    朴素切分会产出「他推开客」「栈的门」这类碎片，送 LLM 纯属浪费 token。
    统计层负责去碎片，LLM 层负责判定语义与译法，各司其职。
    """
    return mine_candidates(texts, covered, min_freq=2, limit=top_n)


def survey_chapter(
    db: Session,
    transform: WorldTransform,
    chapter: Chapter,
    *,
    mine: bool = True,
    max_candidates: int = 40,
) -> SurveyResult:
    """勘探一章：模板扫描 + LLM 挖掘，产出待审核的候选词条。"""
    blocks = _collect_blocks(db, chapter)
    if not blocks:
        raise PipelineError(f"章节 {chapter.id} 还没有 active 剧本，请先生成剧本")

    texts = [b.source_text for b in blocks if b.source_text]
    result = SurveyResult(scanned_blocks=len(blocks))

    # ── 第 1 层：模板扫描 ──
    rows = list(
        db.execute(
            select(WorldLexicon).where(WorldLexicon.transform_id == transform.id)
        ).scalars()
    )
    by_term = {r.source_term: r for r in rows}
    matcher = LexiconMatcher(
        {r.source_term: (r.source_aliases or []) for r in rows},
        measure_terms=[r.source_term for r in rows
                       if r.category == LexiconCategory.measure],
    )
    if matcher:
        counts = matcher.count(texts)
        for term, n in counts.items():
            row = by_term.get(term)
            if row is not None:
                row.hit_count = (row.hit_count or 0) + n
                evidence = dict(row.evidence_json or {})
                chapters = set(evidence.get("chapter_ids") or [])
                chapters.add(chapter.id)
                evidence["chapter_ids"] = sorted(chapters)
                row.evidence_json = evidence
        result.template_hits = counts
        db.flush()

    if not mine:
        return result

    # ── 第 2 层：LLM 挖掘未覆盖词 ──
    covered: set[str] = set()
    for r in rows:
        covered.add(r.source_term)
        covered.update(r.source_aliases or [])

    candidates = _candidate_tokens(texts, covered, max_candidates)
    if not candidates:
        return result

    src_profile = db.get(WorldProfile, transform.source_profile_id)
    tgt_profile = db.get(WorldProfile, transform.target_profile_id)
    excerpt = "\n".join(texts)[:6000]
    known_sample = ", ".join(sorted(covered)[:60])

    data, _task = chat_json(
        db,
        [
            {"role": "system", "content": MINE_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"【源世界观】{src_profile.display_name if src_profile else '?'}\n"
                    f"【目标世界观】{tgt_profile.display_name if tgt_profile else '?'}\n"
                    f"【目标语言】{transform.target_language_code}\n\n"
                    f"【已有词表】{known_sample}\n\n"
                    f"【高频候选词】"
                    f"{', '.join(f'{t}({c})' for t, c in candidates)}\n\n"
                    f"【原文节选】\n{excerpt}"
                ),
            },
        ],
        MINE_SCHEMA,
        purpose="lexicon",
        novel_id=chapter.novel_id,
        chapter_id=chapter.id,
        ref_kind="lexicon",
        ref_id=transform.id,
    )

    for item in data.get("terms") or []:
        src = str(item.get("source_term") or "").strip()
        tgt = str(item.get("target_term") or "").strip()
        if not src or not tgt or src in covered:
            continue
        try:
            category = LexiconCategory(item.get("category") or "other")
        except ValueError:
            category = LexiconCategory.other

        db.add(WorldLexicon(
            id=new_id("lx"),
            transform_id=transform.id,
            canonical_key=item.get("canonical_key") or f"{category.value}.{src}",
            category=category,
            source_term=src,
            target_term=tgt,
            target_reading=item.get("target_reading") or None,
            forbidden_targets=item.get("forbidden_targets") or [src],
            status=ReviewStatus.candidate,
            confidence=float(item.get("confidence") or 0.6),
            rationale=item.get("rationale") or None,
            source=LexiconSource.mined,
            evidence_json={
                "chapter_ids": [chapter.id],
                "excerpt": _first_context(texts, src),
            },
            hit_count=sum(c for t, c in candidates if t == src),
        ))
        covered.add(src)
        result.mined_created += 1
        result.mined_terms.append(src)

    result.unresolved = [t for t, _ in candidates if t not in covered]
    db.flush()
    return result


def _first_context(texts: list[str], term: str, width: int = 40) -> str | None:
    """截取该词首次出现的上下文，供审核时判断语境。"""
    for text in texts:
        idx = text.find(term)
        if idx >= 0:
            start = max(0, idx - width)
            end = min(len(text), idx + len(term) + width)
            return ("…" if start > 0 else "") + text[start:end] + ("…" if end < len(text) else "")
    return None


# ── 覆盖率 ────────────────────────────────────────────────────────────────────

def seed_defaults(db: Session) -> dict[str, int]:
    """把预置世界观档案与词表模板灌进库。幂等，可反复调用。"""
    from app.seed.lexicon_templates import TEMPLATES
    from app.seed.world_profiles import PROFILES
    from app.models import ProfileRole, ProfileStatus

    created_p = created_t = 0

    for p in PROFILES:
        exists = db.execute(
            select(WorldProfile).where(
                WorldProfile.code == p["code"], WorldProfile.version == 1
            )
        ).scalars().first()
        if exists:
            continue
        db.add(WorldProfile(
            id=new_id("wp"),
            novel_id=None,
            code=p["code"],
            display_name=p["display_name"],
            role=ProfileRole(p["role"]),
            axes_json=p.get("axes"),
            visual_json=p.get("visual"),
            language_json=p.get("language"),
            version=1,
            status=ProfileStatus.active,
        ))
        created_p += 1

    for t in TEMPLATES:
        exists = db.execute(
            select(WorldLexiconTemplate).where(
                WorldLexiconTemplate.pair_code == t["pair_code"],
                WorldLexiconTemplate.version == 1,
            )
        ).scalars().first()
        if exists:
            continue
        db.add(WorldLexiconTemplate(
            id=new_id("lt"),
            pair_code=t["pair_code"],
            display_name=t["display_name"],
            source_profile_code=t["source_profile_code"],
            target_profile_code=t["target_profile_code"],
            entries_json=t["entries"],
            version=1,
            description=t.get("description"),
        ))
        created_t += 1

    db.flush()
    return {"profiles": created_p, "templates": created_t}
