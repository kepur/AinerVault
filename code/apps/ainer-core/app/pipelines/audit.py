"""全书一致性审计 —— 单章看不出的问题，跨章才现形。

三类只有全书视角才能发现的漏洞：

    译名漂移   主角在第 1 章叫 Mason，第 7 章又变回 Lin Fan。
               逐章审核时每章内部都自洽，看不出问题。
    名物分歧   同一个「客栈」，前面译 inn，后面译 tavern。
    音译残留   全书零散分布的拼音词，单章只有一两处不显眼，
               汇总起来才看得出哪个专名从头到尾就没转译过。

审计不调 LLM —— 一致性是可枚举的事实，用规则查更快也更准。
"""
from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import (
    Chapter, DocMode, DocStatus, EntityWorldName, ScriptBlock, ScriptDoc,
    TranslationBlock, WorldEntity, WorldLexicon, WorldProfile, WorldTransform,
)
from app.pipelines.base import PipelineError
from app.worldview.matcher import LexiconMatcher
from app.worldview.naming import contains_han, contains_pinyin
from app.worldview.validator import contains_token

log = logging.getLogger(__name__)

_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z'\-]*")


@dataclass
class AuditFinding:
    kind: str
    severity: str
    subject: str
    detail: str
    chapters: list[str] = field(default_factory=list)
    samples: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "severity": self.severity, "subject": self.subject,
            "detail": self.detail, "chapters": self.chapters,
            "samples": self.samples[:4],
        }


@dataclass
class AuditReport:
    chapters_scanned: int = 0
    blocks_scanned: int = 0
    findings: list[AuditFinding] = field(default_factory=list)
    name_coverage: dict[str, Any] = field(default_factory=dict)
    lexicon_coverage: dict[str, Any] = field(default_factory=dict)
    residue: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        by_sev: Counter = Counter(f.severity for f in self.findings)
        return {
            "chapters_scanned": self.chapters_scanned,
            "blocks_scanned": self.blocks_scanned,
            "findings": [f.as_dict() for f in self.findings],
            "summary": {
                "total": len(self.findings),
                "high": by_sev.get("high", 0),
                "medium": by_sev.get("medium", 0),
                "low": by_sev.get("low", 0),
            },
            "name_coverage": self.name_coverage,
            "lexicon_coverage": self.lexicon_coverage,
            "residue": self.residue,
            "passed": by_sev.get("high", 0) == 0,
        }


def _collect(db: Session, transform: WorldTransform) -> list[tuple[Chapter, ScriptBlock, str]]:
    """取全书的 (章节, 原文块, 译文)。"""
    lang = transform.target_language_code
    rows = db.execute(
        select(Chapter, ScriptBlock, TranslationBlock)
        .join(ScriptDoc, ScriptDoc.chapter_id == Chapter.id)
        .join(ScriptBlock, ScriptBlock.script_doc_id == ScriptDoc.id)
        .join(
            TranslationBlock,
            (TranslationBlock.script_block_id == ScriptBlock.id)
            & (TranslationBlock.transform_id == transform.id),
        )
        .where(
            Chapter.novel_id == transform.novel_id,
            ScriptDoc.status == DocStatus.active,
        )
        .order_by(Chapter.order_no, ScriptBlock.seq_no)
    ).all()
    return [
        (ch, blk, tb.translated_text or "")
        for ch, blk, tb in rows if (tb.translated_text or "").strip()
    ]


def audit_novel(db: Session, transform: WorldTransform) -> AuditReport:
    """全书审计。"""
    data = _collect(db, transform)
    if not data:
        raise PipelineError("全书还没有译文可审计")

    report = AuditReport(blocks_scanned=len(data))
    report.chapters_scanned = len({ch.id for ch, _b, _t in data})
    lang = transform.target_language_code
    profile = db.get(WorldProfile, transform.target_profile_id)

    _audit_names(db, transform, data, report)
    _audit_lexicon(db, transform, data, report)
    _audit_residue(data, lang, report)
    _audit_forbidden(profile, data, report)

    report.findings.sort(
        key=lambda f: {"high": 0, "medium": 1, "low": 2}.get(f.severity, 3)
    )
    return report


def _audit_names(
    db: Session, transform: WorldTransform,
    data: list[tuple[Chapter, ScriptBlock, str]], report: AuditReport,
) -> None:
    """译名漂移：原文出现某实体，译文却没用锁定译名。

    称呼变体各自对自己的目标形式负责：原文写「小天」时该出现的是 Tom，
    不是全名 Thomas Ashford。若按本名一把尺子量，正确的亲昵译法反而被判成漂移，
    而真正的问题（亲昵称呼被拍平成全名）一条都查不出来。
    """
    rows = db.execute(
        select(EntityWorldName, WorldEntity)
        .join(WorldEntity, WorldEntity.id == EntityWorldName.entity_id)
        .where(EntityWorldName.transform_id == transform.id)
    ).all()
    if not rows:
        report.name_coverage = {"entities": 0, "note": "尚未建立人名映射"}
        return

    from app.models import EntityAppellation

    #: 字面 → (实体名, 期望译法, 是否为称呼变体)
    surfaces: dict[str, tuple[str, str, bool]] = {}
    for name_row, entity in rows:
        for s in [entity.display_name, *(entity.aliases_json or [])]:
            s = str(s or "").strip()
            if s:
                surfaces[s] = (entity.display_name, name_row.target_name, False)

    # 称呼变体覆盖同名字面 —— 它们有更精确的期望值
    entity_ids = [e.id for _n, e in rows]
    if entity_ids:
        by_entity = {e.id: n.target_name for n, e in rows}
        display = {e.id: e.display_name for _n, e in rows}
        for a in db.execute(
            select(EntityAppellation).where(
                EntityAppellation.entity_id.in_(entity_ids),
                or_(
                    EntityAppellation.transform_id == transform.id,
                    EntityAppellation.transform_id.is_(None),
                ),
                EntityAppellation.target_surface.is_not(None),
            )
        ).scalars():
            surface = str(a.source_surface or "").strip()
            if not surface or a.entity_id not in by_entity:
                continue
            surfaces[surface] = (display[a.entity_id], a.target_surface, True)

    miss: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"chapters": set(), "samples": [], "expected": "", "hits": 0,
                 "surface": "", "appellation": False}
    )
    total_hits = 0
    for ch, blk, text in data:
        for surface, (canonical, target, is_appellation) in surfaces.items():
            if surface not in (blk.source_text or ""):
                continue
            total_hits += 1
            if contains_token(text, target):
                continue
            key = f"{canonical}／{surface}" if is_appellation else canonical
            slot = miss[key]
            slot["expected"] = target
            slot["surface"] = surface
            slot["appellation"] = is_appellation
            slot["hits"] += 1
            slot["chapters"].add(ch.id)
            if len(slot["samples"]) < 4:
                slot["samples"].append({
                    "chapter": ch.title, "block_id": blk.id,
                    "source": (blk.source_text or "")[:60],
                    "translation": text[:80],
                })

    for canonical, slot in miss.items():
        chapters = sorted(slot["chapters"])
        if slot.get("appellation"):
            report.findings.append(AuditFinding(
                kind="appellation_flattened",
                severity="medium",
                subject=canonical,
                detail=(
                    f"原文用称呼「{slot['surface']}」{slot['hits']} 处，"
                    f"译文未用对应形式「{slot['expected']}」，涉及 {len(chapters)} 章。"
                    f"多半被拍平成了全名 —— 信息还在，亲疏关系没了"
                ),
                chapters=chapters, samples=slot["samples"],
            ))
            continue
        report.findings.append(AuditFinding(
            kind="name_drift",
            severity="high" if len(chapters) > 1 else "medium",
            subject=canonical,
            detail=(
                f"原文出现「{canonical}」{slot['hits']} 处，译文未使用锁定译名"
                f"「{slot['expected']}」，涉及 {len(chapters)} 章"
            ),
            chapters=chapters, samples=slot["samples"],
        ))

    report.name_coverage = {
        "entities": len(rows),
        "source_hits": total_hits,
        "drifted_entities": len(miss),
        "clean": total_hits - sum(s["hits"] for s in miss.values()),
    }


def _audit_lexicon(
    db: Session, transform: WorldTransform,
    data: list[tuple[Chapter, ScriptBlock, str]], report: AuditReport,
) -> None:
    """名物分歧：同一 canonical_key 在不同章节译法不一致，或整条从未生效。"""
    entries = list(
        db.execute(
            select(WorldLexicon).where(
                WorldLexicon.transform_id == transform.id,
                WorldLexicon.target_term != "",
            )
        ).scalars()
    )
    if not entries:
        report.lexicon_coverage = {"terms": 0, "note": "尚未导入名物词表"}
        return

    matcher = LexiconMatcher(
        {r.source_term: (r.source_aliases or []) for r in entries},
        measure_terms=[
            r.source_term for r in entries if r.category.value == "measure"
        ],
    )
    index = {r.source_term: r for r in entries}

    miss: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"chapters": set(), "samples": [], "hits": 0, "target": ""}
    )
    total_hits = 0
    for ch, blk, text in data:
        for hit in matcher.find(blk.source_text or ""):
            row = index.get(hit.key)
            if row is None:
                continue
            total_hits += 1
            if contains_token(text, row.target_term):
                continue
            if row.target_reading and contains_token(text, row.target_reading):
                continue
            slot = miss[row.source_term]
            slot["target"] = row.target_term
            slot["hits"] += 1
            slot["chapters"].add(ch.id)
            if len(slot["samples"]) < 3:
                slot["samples"].append({
                    "chapter": ch.title, "block_id": blk.id,
                    "source": (blk.source_text or "")[:60],
                    "translation": text[:80],
                })

    for term, slot in miss.items():
        chapters = sorted(slot["chapters"])
        report.findings.append(AuditFinding(
            kind="lexicon_drift",
            severity="high" if len(chapters) > 1 and slot["hits"] >= 3 else "medium",
            subject=term,
            detail=(
                f"「{term}」在原文出现 {slot['hits']} 处未按词表译为"
                f"「{slot['target']}」，涉及 {len(chapters)} 章"
            ),
            chapters=chapters, samples=slot["samples"],
        ))

    report.lexicon_coverage = {
        "terms": len(entries), "source_hits": total_hits,
        "drifted_terms": len(miss),
        "clean": total_hits - sum(s["hits"] for s in miss.values()),
    }


def _audit_residue(
    data: list[tuple[Chapter, ScriptBlock, str]], language: str, report: AuditReport,
) -> None:
    """音译与源文字残留：汇总全书才看得出哪个专名从头到尾没转译过。"""
    lang = language[:2].lower()
    han_blocks: list[dict] = []
    pinyin: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "chapters": set(), "samples": []}
    )

    for ch, blk, text in data:
        if lang != "zh" and contains_han(text):
            if len(han_blocks) < 6:
                han_blocks.append({
                    "chapter": ch.title, "block_id": blk.id,
                    "translation": text[:80],
                })
        if lang in {"zh", "ja", "ko"}:
            continue
        for token in dict.fromkeys(contains_pinyin(text)):
            slot = pinyin[token]
            slot["count"] += 1
            slot["chapters"].add(ch.id)
            if len(slot["samples"]) < 3:
                slot["samples"].append({
                    "chapter": ch.title, "block_id": blk.id,
                    "translation": text[:80],
                })

    if han_blocks:
        report.findings.append(AuditFinding(
            kind="source_script_residue", severity="high",
            subject="源文字残留",
            detail=f"{len(han_blocks)} 处译文仍含汉字，说明这些段落根本没译",
            samples=han_blocks,
        ))

    for token, slot in sorted(pinyin.items(), key=lambda kv: -kv[1]["count"])[:12]:
        chapters = sorted(slot["chapters"])
        report.findings.append(AuditFinding(
            kind="transliteration_residue",
            severity="high" if slot["count"] >= 3 else "medium",
            subject=token,
            detail=(
                f"「{token}」疑似音译，全书出现 {slot['count']} 处，"
                f"涉及 {len(chapters)} 章 —— 该专名可能从未做文化转译"
            ),
            chapters=chapters, samples=slot["samples"],
        ))

    report.residue = {
        "han_blocks": len(han_blocks),
        "transliteration_tokens": len(pinyin),
        "top_tokens": [
            {"token": t, "count": s["count"]}
            for t, s in sorted(pinyin.items(), key=lambda kv: -kv[1]["count"])[:10]
        ],
    }


def _audit_forbidden(
    profile: WorldProfile | None,
    data: list[tuple[Chapter, ScriptBlock, str]], report: AuditReport,
) -> None:
    """世界观禁用词：整本书扫一遍。"""
    if profile is None:
        return
    tokens = (profile.language_json or {}).get("forbidden_tokens") or []
    if not tokens:
        return
    found: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "chapters": set(), "samples": []}
    )
    for ch, blk, text in data:
        for token in tokens:
            if contains_token(text, str(token)):
                slot = found[str(token)]
                slot["count"] += 1
                slot["chapters"].add(ch.id)
                if len(slot["samples"]) < 3:
                    slot["samples"].append({
                        "chapter": ch.title, "block_id": blk.id,
                        "translation": text[:80],
                    })
    for token, slot in found.items():
        report.findings.append(AuditFinding(
            kind="forbidden_token", severity="high", subject=token,
            detail=(
                f"「{token}」被目标世界观列为禁用词，全书出现 {slot['count']} 处"
            ),
            chapters=sorted(slot["chapters"]), samples=slot["samples"],
        ))
