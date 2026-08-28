"""回译校验 —— 质量闭环的最后一环。

译文读着通顺不代表情节没丢。改编模式允许调整句式，这既是它的价值也是它的风险：
模型可能为了顺畅而悄悄抹掉一个情节点，或者把一处笑点译成平淡的陈述，
而译文本身毫无破绽。

唯一能查出来的办法是把成品**回译**成源语言，再与骨架逐点比对：
    情节点还在不在？
    装置的效果重铸成功了没有？
    情绪曲线对不对得上？

这一步不看译文写得好不好 —— 那是审校的事。它只回答一个问题：
**东西丢了没有。**
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ids import new_id
from app.models import (
    BackTranslationCheck, Chapter, DocStatus, NarrativeDevice, ScriptBlock,
    ScriptDoc, StoryBeat, TranslationBlock, WorldTransform,
)
from app.pipelines.base import PipelineError, chat_json

log = logging.getLogger(__name__)

CHECK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["beats", "devices", "verdict"],
    "properties": {
        "beats": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["order", "present"],
                "properties": {
                    "order": {"type": "integer"},
                    "present": {"type": "boolean"},
                    "note": {"type": "string"},
                    "emotion_match": {"type": "boolean"},
                },
            },
        },
        "devices": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["device_id", "landed"],
                "properties": {
                    "device_id": {"type": "string"},
                    "landed": {"type": "boolean"},
                    "note": {"type": "string"},
                },
            },
        },
        "added_content": {"type": "array", "items": {"type": "string"}},
        "verdict": {"type": "string"},
    },
}

CHECK_SYSTEM = """你在做回译校验。给你三样东西：原文的叙事骨架、抽出的叙事装置、
以及译文回译成中文的结果。

你要回答的**只有一个问题：东西丢了没有。**
不评价译文写得好不好，不评价用词是否优美 —— 那是别人的事。

逐项判断：

beats  骨架里的每个情节点，在回译文本里还在不在。
       present=false 只在该情节点**确实消失**时填。
       换了说法、换了顺序但事实还在 —— 算在。
       emotion_match 判断这一拍的情绪是否还对得上。

devices 每处装置，效果在回译文本里有没有重现。
       landed=true 表示目标文本用某种方式实现了同样的效果 ——
       **手法可以完全不同**，这正是改编该做的。
       一处笑点从谐音换成了情境反差，只要还好笑，就算 landed。
       landed=false 只在效果确实消失时填（比如原本的笑点变成了平铺直叙）。

added_content 列出回译文本里**原文没有**的情节或事实。
       改编可以改说法，不能加剧情。

verdict 一句话结论。"""


@dataclass
class CheckResult:
    beat_coverage: float = 0.0
    device_landing: float = 0.0
    emotion_match: float = 0.0
    passed: bool = False
    missing_beats: list[dict] = field(default_factory=list)
    lost_devices: list[dict] = field(default_factory=list)
    added_content: list[str] = field(default_factory=list)
    verdict: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "beat_coverage": self.beat_coverage,
            "device_landing": self.device_landing,
            "emotion_match": self.emotion_match,
            "passed": self.passed,
            "missing_beats": self.missing_beats,
            "lost_devices": self.lost_devices,
            "added_content": self.added_content,
            "verdict": self.verdict,
        }


def back_check(
    db: Session,
    chapter: Chapter,
    transform: WorldTransform,
    *,
    max_blocks: int | None = None,
    pass_threshold: float = 0.9,
) -> CheckResult:
    """回译并与骨架比对。"""
    lang = transform.target_language_code
    doc = db.execute(
        select(ScriptDoc).where(
            ScriptDoc.chapter_id == chapter.id, ScriptDoc.status == DocStatus.active
        ).order_by(ScriptDoc.version.desc())
    ).scalars().first()
    if doc is None:
        raise PipelineError("该章节还没有分块")

    blocks = list(
        db.execute(
            select(ScriptBlock).where(ScriptBlock.script_doc_id == doc.id)
            .order_by(ScriptBlock.seq_no)
        ).scalars()
    )
    trans = {
        t.script_block_id: t.translated_text or ""
        for t in db.execute(
            select(TranslationBlock).where(
                TranslationBlock.script_block_id.in_([b.id for b in blocks]),
                TranslationBlock.target_language_code == lang,
            )
        ).scalars()
    }
    pairs = [(b, trans[b.id]) for b in blocks if trans.get(b.id, "").strip()]
    if max_blocks:
        pairs = pairs[:max_blocks]
    if not pairs:
        raise PipelineError("该章节还没有译文")

    beats = list(
        db.execute(
            select(StoryBeat).where(StoryBeat.chapter_id == chapter.id)
            .order_by(StoryBeat.order_no)
        ).scalars()
    )
    devices = list(
        db.execute(
            select(NarrativeDevice).where(NarrativeDevice.chapter_id == chapter.id)
        ).scalars()
    )
    if not beats and not devices:
        raise PipelineError("还没有叙事骨架与装置，请先执行世界模型抽离与装置抽离")

    # ── 第一步：回译 ──
    source_lang = doc.language_source or "zh-CN"
    back = _back_translate(db, chapter, pairs, lang, source_lang)

    # ── 第二步：与骨架比对 ──
    payload = {
        "beats": [
            {"order": b.order_no, "title": b.title,
             "plot_point": b.plot_point or b.summary,
             "emotion": b.emotion, "intensity": b.emotion_intensity}
            for b in beats
        ],
        "devices": [
            {"device_id": d.id, "type": d.device_type.value,
             "effect": d.effect.value, "source_text": d.source_text[:120],
             "mechanism": d.mechanism[:160], "intensity": d.intensity}
            for d in devices
        ],
        "back_translation": back,
    }
    data, _ = chat_json(
        db,
        [
            {"role": "system", "content": CHECK_SYSTEM},
            {"role": "user", "content": _dump(payload)},
        ],
        CHECK_SCHEMA,
        purpose="review",
        novel_id=chapter.novel_id, chapter_id=chapter.id,
        ref_kind="back_check", ref_id=chapter.id,
    )

    result = CheckResult(verdict=str(data.get("verdict") or "")[:500])
    by_order = {b.order_no: b for b in beats}
    # 按 order 去重：模型可能对同一拍报多条，直接累加会算出 300% 这种数
    seen_kept: set[int] = set()
    seen_emo: set[int] = set()
    seen_missing: set[int] = set()
    for item in data.get("beats") or []:
        b = by_order.get(int(item.get("order") or 0))
        if b is None:
            continue
        if item.get("present"):
            seen_kept.add(b.order_no)
            if item.get("emotion_match", True):
                seen_emo.add(b.order_no)
        elif b.order_no not in seen_missing:
            seen_missing.add(b.order_no)
            result.missing_beats.append({
                "order": b.order_no, "title": b.title,
                "plot_point": b.plot_point, "note": item.get("note"),
            })
    # 同一拍既报在又报丢时，以「丢」为准 —— 存疑就当没保住
    seen_kept -= seen_missing
    seen_emo -= seen_missing
    result.beat_coverage = round(len(seen_kept) / len(beats), 4) if beats else 1.0
    result.emotion_match = round(len(seen_emo) / len(beats), 4) if beats else 1.0

    by_id = {d.id: d for d in devices}
    landed_ids: set[str] = set()
    lost_ids: set[str] = set()
    for item in data.get("devices") or []:
        d = by_id.get(str(item.get("device_id") or ""))
        if d is None or d.id in lost_ids:
            continue
        ok = bool(item.get("landed"))
        d.landed = ok
        d.landed_note = str(item.get("note") or "")[:500] or None
        if ok:
            landed_ids.add(d.id)
        else:
            lost_ids.add(d.id)
            landed_ids.discard(d.id)
            result.lost_devices.append({
                "device_id": d.id, "type": d.device_type.value,
                "effect": d.effect.value, "intensity": d.intensity,
                "source_text": d.source_text[:60],
                "mechanism": d.mechanism[:100], "note": item.get("note"),
            })
    result.device_landing = (
        round(len(landed_ids) / len(devices), 4) if devices else 1.0
    )
    result.added_content = [str(x)[:200] for x in (data.get("added_content") or [])]

    # 高强度装置丢失是硬否决 —— 那正是读者会察觉的东西
    hard_loss = any(x["intensity"] >= 4 for x in result.lost_devices)
    result.passed = (
        result.beat_coverage >= pass_threshold
        and result.device_landing >= pass_threshold
        and not hard_loss
        and not result.added_content
    )

    db.add(BackTranslationCheck(
        id=new_id("bc"), chapter_id=chapter.id, transform_id=transform.id,
        target_language_code=lang,
        beat_coverage=result.beat_coverage,
        device_landing=result.device_landing,
        emotion_match=result.emotion_match,
        missing_beats=result.missing_beats or None,
        lost_devices=result.lost_devices or None,
        added_content=result.added_content or None,
        notes=result.verdict, passed=result.passed,
    ))
    db.flush()
    return result


def _back_translate(
    db: Session, chapter: Chapter,
    pairs: Sequence[tuple[ScriptBlock, str]], lang: str, source_lang: str,
) -> str:
    """把译文回译成源语言。

    刻意**不给**原文 —— 给了模型会照抄原文，回译就失去了检测意义。
    """
    from app.capability.schemas import Capability
    from app.capability.service import submit_task
    from app.models import TaskStatus

    segments = [
        {"id": b.id, "text": text, "kind": b.block_type.value}
        for b, text in pairs
    ]
    task = submit_task(
        db, Capability.text_translate,
        {
            "source_language": lang,
            "target_language": source_lang,
            "segments": segments,
            "style_prompt": (
                "直译。逐句对应，不要润色、不要补充、不要解释。"
                "目的是检验原意是否完整保留，所以宁可生硬也不要美化。"
            ),
            "glossary": [],
        },
        purpose="translate", sync=True,
        novel_id=chapter.novel_id, chapter_id=chapter.id,
        ref_kind="back_check", ref_id=chapter.id,
    )
    if task.status != TaskStatus.succeeded:
        err = task.error_json or {}
        raise PipelineError(f"回译失败 [{err.get('code')}]: {err.get('message')}")
    out = (task.result_json or {}).get("segments") or []
    return "\n".join(str(s.get("text") or "") for s in out)


def _dump(payload: Any) -> str:
    import json
    return json.dumps(payload, ensure_ascii=False, indent=1)
