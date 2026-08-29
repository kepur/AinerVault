"""译本二次审核 —— 规则闸抓不到的那类漏洞交给模型。

规则闸（validator）只能抓「词表里有、译文里没有」这一种情况。
真正致命的是词表外的漏洞：

    主角「林凡」在旧时代英伦世界应当叫 Mason，译文却写成 Lin Fan —— 音译，
    等于没转译；他用的「刀剑」在英伦对应 sword/blade，身份「剑客」对应
    swordsman，译文若保留 dao/jian 或直译成 sword guest，整段就出戏。

这些词不在名物词表里（词表几百条，覆盖不了全书），规则无从判断。
所以要模型按目标世界观逐段过一遍，找出：
    音译残留 / 文化转译缺失 / 身份称谓不符 / 语体错位 / 时代不符 / 源文化残留

审核产出统一进 world_violations，与规则闸的告警同池，人工只看一个面板。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Chapter, DocStatus, EntityWorldName, ScriptBlock, ScriptDoc, TranslationBlock,
    WorldEntity, WorldLexicon, WorldProfile, WorldTransform,
)
from app.pipelines.base import PipelineError, chat_json, as_items
from app.worldview import preflight as pf
from app.worldview.naming import contains_han, contains_pinyin
from app.worldview.validator import Violation

log = logging.getLogger(__name__)

#: 模型可报的问题类型 → world_violations 的 kind
ISSUE_KIND: dict[str, str] = {
    "transliteration": "name_drift",
    "untranslated_culture": "lexicon_miss",
    "identity_mismatch": "social_norm_conflict",
    "era_mismatch": "era_conflict",
    "wrong_register": "register_conflict",
    "source_residue": "forbidden_token",
}

REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["issues"],
    "properties": {
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["block_id", "issue_type", "detected", "severity",
                             "explanation"],
                "properties": {
                    "block_id": {"type": "string"},
                    "issue_type": {"type": "string",
                                   "enum": list(ISSUE_KIND.keys())},
                    "detected": {"type": "string"},
                    "expected": {"type": "string"},
                    "severity": {"type": "string",
                                 "enum": ["low", "medium", "high"]},
                    "explanation": {"type": "string"},
                },
            },
        }
    },
}

REVIEW_SYSTEM = """你是跨文化改编的审校。逐段检查译文是否真正落进了目标世界观。

要找的问题：

transliteration      人名/地名用了音译而非文化等效名。
                     「林凡」在旧英伦世界应是 Mason 这类本土名，
                     写成 Lin Fan 就是音译，等于没转译。
untranslated_culture 器物、职官、建筑、货币、度量没按目标文化转译。
                     「刀剑」在英伦是 sword/blade，保留 dao/jian 或
                     直译成 knife-sword 都算失败。
identity_mismatch    身份、职业、称谓不符目标世界。
                     「剑客」在英伦是 swordsman/blademaster，
                     不是 sword guest 这类字面直译。
era_mismatch         出现了目标年代不该有的东西。
wrong_register       语体与目标世界观不符（该古雅的写成现代口语等）。
source_residue       残留源语言文字、拼音或源文化专名。

判断准则：
1. 只报确实有问题的段落。没问题就不要报 —— 报满一屏假问题，
   真问题会被淹没。
2. detected 引用译文里出问题的原词，expected 给出应该怎么写。
3. severity：改了就出戏填 high，影响观感填 medium，可接受填 low。
4. explanation 一句话说明为什么在这个世界观里不成立。
5. 已在【固定译名】里的人名是审核通过的，不要报。"""


@dataclass
class ReviewResult:
    reviewed_blocks: int = 0
    issues_found: int = 0
    recorded: int = 0
    rule_prescreen: int = 0
    by_type: dict[str, int] = field(default_factory=dict)
    by_severity: dict[str, int] = field(default_factory=dict)
    samples: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "reviewed_blocks": self.reviewed_blocks,
            "issues_found": self.issues_found, "recorded": self.recorded,
            "rule_prescreen": self.rule_prescreen,
            "by_type": self.by_type, "by_severity": self.by_severity,
            "samples": self.samples,
        }


def prescreen(text: str, language: str) -> list[str]:
    """规则预筛：拉丁语系目标下的汉字残留与疑似拼音，几乎必然是漏译。

    先标出来一并交给模型，既省 token 也提高命中率。
    """
    hits: list[str] = []
    if not text:
        return hits
    lang = language[:2].lower()
    if lang != "zh" and contains_han(text):
        hits.append("残留汉字")
    if lang not in {"zh", "ja", "ko"}:
        pin = contains_pinyin(text)
        if pin:
            hits.append(f"疑似音译 {pin[:3]}")
    return hits


def review_translation(
    db: Session,
    chapter: Chapter,
    transform: WorldTransform,
    *,
    batch_size: int = 12,
    max_blocks: int | None = None,
) -> ReviewResult:
    """对一章译文做二次审核。"""
    from app.pipelines.prose import active_prose_doc

    doc = active_prose_doc(db, chapter.id) or db.execute(
        select(ScriptDoc).where(
            ScriptDoc.chapter_id == chapter.id,
            ScriptDoc.status == DocStatus.active,
        )
    ).scalars().first()
    if doc is None:
        raise PipelineError("该章节还没有分块，请先执行 prose:build")

    lang = transform.target_language_code
    src_profile = db.get(WorldProfile, transform.source_profile_id)
    tgt_profile = db.get(WorldProfile, transform.target_profile_id)

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
        (b, trans[b.id]) for b in blocks
        if b.id in trans and (trans[b.id].translated_text or "").strip()
    ]
    if max_blocks:
        pairs = pairs[:max_blocks]
    if not pairs:
        raise PipelineError("该章节还没有译文可审")

    locked_names = {
        e.display_name: n.target_name
        for n, e in db.execute(
            select(EntityWorldName, WorldEntity)
            .join(WorldEntity, WorldEntity.id == EntityWorldName.entity_id)
            .where(EntityWorldName.transform_id == transform.id)
        ).all()
    }
    lexicon_sample = [
        f"{r.source_term}→{r.target_term}"
        for r in db.execute(
            select(WorldLexicon).where(
                WorldLexicon.transform_id == transform.id,
                WorldLexicon.target_term != "",
            ).limit(40)
        ).scalars()
    ]

    result = ReviewResult(reviewed_blocks=len(pairs))
    violations: list[Violation] = []

    for chunk in _chunks(pairs, batch_size):
        segments = []
        for block, tb in chunk:
            flags = prescreen(tb.translated_text or "", lang)
            if flags:
                result.rule_prescreen += 1
            segments.append({
                "block_id": block.id, "type": block.block_type.value,
                "speaker": block.speaker_tag, "source": block.source_text,
                "translation": tb.translated_text, "rule_flags": flags,
            })

        context = (
            f"【源世界观】{src_profile.display_name if src_profile else '?'}\n"
            f"【目标世界观】{tgt_profile.display_name if tgt_profile else '?'}\n"
            f"【目标语言】{lang}\n"
            f"【年代】{(tgt_profile.axes_json or {}).get('era_span') if tgt_profile else ''}\n"
            f"【固定译名】{_dump_pairs(locked_names)}\n"
            f"【名物词表节选】{', '.join(lexicon_sample) or '（无）'}\n"
        )
        try:
            data, _ = chat_json(
                db,
                [
                    {"role": "system", "content": REVIEW_SYSTEM},
                    {"role": "user",
                     "content": context + "\n【待审段落】\n" + _dump(segments)},
                ],
                REVIEW_SCHEMA,
                purpose="review",
                novel_id=chapter.novel_id, chapter_id=chapter.id,
                ref_kind="translation_review", ref_id=chapter.id,
            )
        except PipelineError as exc:
            log.warning("译本审核批次失败: %s", exc)
            continue

        valid_ids = {b.id for b, _ in chunk}
        reported = {
            str(i.get("block_id") or "") for i in (data.get("issues") or [])
        }
        # 规则兜底：预筛命中却没被模型报出来的，按规则结论直接记。
        # 模型漏报的代价是漏洞流到下游，而汉字残留、拼音残留是确定性事实，
        # 不该依赖模型的判断。
        for block, tb in chunk:
            if block.id in reported:
                continue
            flags = prescreen(tb.translated_text or "", lang)
            if not flags:
                continue
            residue = "残留汉字" in flags
            violations.append(Violation(
                kind="forbidden_token" if residue else "name_drift",
                severity="high",
                detected=(tb.translated_text or "")[:120],
                expected=None,
                suggested_fix=(
                    "译文仍含源语言文字，该段落未真正翻译" if residue
                    else f"译文含音译片段（{'、'.join(flags)}），应改用文化等效名"
                ),
                evidence={"block_id": block.id, "source": "rule_fallback",
                          "flags": flags},
            ))
            issue_type = "source_residue" if residue else "transliteration"
            result.issues_found += 1
            result.by_type[issue_type] = result.by_type.get(issue_type, 0) + 1
            result.by_severity["high"] = result.by_severity.get("high", 0) + 1
            if len(result.samples) < 8:
                result.samples.append({
                    "block_id": block.id, "issue_type": issue_type,
                    "severity": "high", "detected": (tb.translated_text or "")[:60],
                    "expected": None, "explanation": f"规则判定：{'、'.join(flags)}",
                    "source": "rule_fallback",
                })

        for item in as_items(data, "issues"):
            bid = str(item.get("block_id") or "")
            issue_type = str(item.get("issue_type") or "")
            kind = ISSUE_KIND.get(issue_type)
            if bid not in valid_ids or kind is None:
                continue
            severity = str(item.get("severity") or "medium")
            if severity not in {"low", "medium", "high"}:
                severity = "medium"

            result.issues_found += 1
            result.by_type[issue_type] = result.by_type.get(issue_type, 0) + 1
            result.by_severity[severity] = result.by_severity.get(severity, 0) + 1
            violations.append(Violation(
                kind=kind, severity=severity,
                detected=str(item.get("detected") or "")[:500],
                expected=str(item.get("expected") or "") or None,
                suggested_fix=str(item.get("explanation") or "") or None,
                evidence={"block_id": bid, "source": "llm_review",
                          "issue_type": issue_type},
            ))
            if len(result.samples) < 8:
                result.samples.append({
                    "block_id": bid, "issue_type": issue_type,
                    "severity": severity, "detected": item.get("detected"),
                    "expected": item.get("expected"),
                    "explanation": item.get("explanation"),
                })

    for v in violations:
        result.recorded += pf.record_violations(
            db, transform.id, [v], ref_id=str(v.evidence.get("block_id") or "")
        )
    db.flush()
    return result


def _chunks(items: Sequence[Any], size: int):
    for i in range(0, len(items), size):
        yield list(items[i : i + size])


def _dump(payload: Any) -> str:
    import json
    return json.dumps(payload, ensure_ascii=False, indent=1)


def _dump_pairs(mapping: dict[str, str]) -> str:
    return "、".join(f"{k}={v}" for k, v in list(mapping.items())[:30]) or "（无）"
