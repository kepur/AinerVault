"""叙事装置抽离 —— 把「为什么好笑/动人」抽成机制。

跨文化改编真正会丢的东西不是词，是效果。逐句翻译能保住情节，保不住笑点：
中文的谐音、成语、语体反差换成英文就是一句平淡的陈述。

所以这一层抽的是机制而非文本：

    原文   我不是针对你，我是说在座的各位都是垃圾
    机制   扬抑反转 —— 先做出缓和姿态，再把打击面扩大到全场
    依赖   低（不依赖中文特有的语言现象）
    策略   preserve，直接在目标语言里重铸同样的结构

而谐音梗这类文化依赖高的，标记为 substitute 或 compensate ——
硬翻只会得到一句莫名其妙的话，不如在目标文化里换一个等效的。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ids import new_id
from app.models import (
    strategy_brief,
    Chapter, CulturalLoad, DeviceEffect, DeviceStrategy, DeviceType,
    NarrativeDevice, ScriptBlock, ScriptDoc, StoryBeat,
)
from app.models.script import DocStatus
from app.pipelines.base import PipelineError, chat_json, as_text
from app.worldview import idiom_rules as ir

log = logging.getLogger(__name__)

DEVICE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["devices"],
    "properties": {
        "devices": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["block_id", "device_type", "effect", "source_text",
                             "mechanism", "cultural_load", "intensity"],
                "properties": {
                    "block_id": {"type": "string"},
                    "device_type": {"type": "string",
                                    "enum": [d.value for d in DeviceType]},
                    "effect": {"type": "string",
                               "enum": [e.value for e in DeviceEffect]},
                    "source_text": {"type": "string"},
                    "mechanism": {"type": "string"},
                    "setup": {"type": "string"},
                    "punch": {"type": "string"},
                    "cultural_load": {"type": "string",
                                      "enum": [c.value for c in CulturalLoad]},
                    "intensity": {"type": "integer"},
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                },
            },
        }
    },
}

DEVICE_SYSTEM = """你是跨文化改编的叙事分析师。找出这一章里所有「换成别的语言就会失效」的地方。

要找的是**装置**，不是句子。装置是让读者产生特定反应的结构性手法：
笑点、泪点、反转、伏笔、语体反差、成语双关、文化典故。

每处装置必须说清三件事：

1. mechanism —— **为什么会产生这个效果**，用不依赖中文的话解释。
   写「先做出缓和姿态，再把打击面扩大到全场」这种结构描述，
   不要写「因为这句话很好笑」。重写的人只看 mechanism 就能在
   另一种语言里重造出同样的效果。

2. cultural_load —— 这个装置多依赖中文特有的东西：
   low     机制通用，任何语言都能重造（反转、夸张、并置）
   medium  需要换一个目标文化的等价物（俗语、身份称谓的反差）
   high    深度绑定中文（谐音、拆字、方言、只有中文读者懂的典故）

3. intensity 1–5 —— 这处丢了对读者体验的损失有多大。

判断准则：
- 只报真有效果的地方。平铺直叙的叙述不是装置。
- 一段里可以有多个装置，也可以一个都没有。
- setup 与 punch 分开写：铺垫在哪、爆点在哪。丢了铺垫，爆点就哑了。
- depends_on 列出读者必须知道什么才能 get（如「中文里『妻』与『欺』同音」）。"""


@dataclass
class DeviceResult:
    devices: int = 0
    by_type: dict[str, int] = field(default_factory=dict)
    by_load: dict[str, int] = field(default_factory=dict)
    high_load: list[dict] = field(default_factory=list)
    #: 成语表推翻模型判断的记录。为空说明两者一致
    rule_corrections: list[dict] = field(default_factory=list)
    #: 本章查表命中的成语与俗语
    idioms_found: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "devices": self.devices, "by_type": self.by_type,
            "by_load": self.by_load, "high_load": self.high_load,
            "rule_corrections": self.rule_corrections,
            "idioms_found": self.idioms_found,
        }


#: 文化依赖度 → 默认策略。high 的硬翻必然失效。
_DEFAULT_STRATEGY = {
    CulturalLoad.low: DeviceStrategy.preserve,
    CulturalLoad.medium: DeviceStrategy.substitute,
    CulturalLoad.high: DeviceStrategy.compensate,
}


def extract_devices(
    db: Session, chapter: Chapter, *, batch_size: int = 14
) -> DeviceResult:
    """抽离一章的叙事装置。重跑覆盖整章 —— 装置是对全章的解读。"""
    doc = db.execute(
        select(ScriptDoc).where(
            ScriptDoc.chapter_id == chapter.id, ScriptDoc.status == DocStatus.active
        ).order_by(ScriptDoc.version.desc())
    ).scalars().first()
    if doc is None:
        raise PipelineError("该章节还没有分块，请先执行 prose:build 或 script:generate")

    blocks = list(
        db.execute(
            select(ScriptBlock).where(ScriptBlock.script_doc_id == doc.id)
            .order_by(ScriptBlock.seq_no)
        ).scalars()
    )
    if not blocks:
        raise PipelineError("剧本没有内容块")

    beats = {
        b.order_no: b
        for b in db.execute(
            select(StoryBeat).where(StoryBeat.chapter_id == chapter.id)
        ).scalars()
    }

    for old in db.execute(
        select(NarrativeDevice).where(NarrativeDevice.chapter_id == chapter.id)
    ).scalars().all():
        db.delete(old)
    db.flush()

    result = DeviceResult()
    valid = {b.id for b in blocks}

    for i in range(0, len(blocks), batch_size):
        chunk = blocks[i : i + batch_size]
        payload = [
            {"block_id": b.id, "type": b.block_type.value,
             "speaker": b.speaker_tag, "text": b.source_text}
            for b in chunk
        ]
        # 成语先查表挑出来。它们的 cultural_load 必是 high、
        # device_type 必是 idiom —— 这两件事查表就能确定，
        # 不必让模型再花力气去认。模型只需判它在这一处起什么作用。
        hits = ir.find_in_text("\n".join(b.source_text or "" for b in chunk))
        for word, _kind in hits:
            if word not in result.idioms_found:
                result.idioms_found.append(word)
        idiom_brief = ir.brief_for_prompt(hits)
        system = (
            f"{DEVICE_SYSTEM}\n\n{idiom_brief}" if idiom_brief else DEVICE_SYSTEM
        )
        try:
            data, _ = chat_json(
                db,
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": _dump(payload)},
                ],
                DEVICE_SCHEMA,
                purpose="devices",
                novel_id=chapter.novel_id, chapter_id=chapter.id,
                ref_kind="devices", ref_id=chapter.id,
            )
        except PipelineError as exc:
            log.warning("装置抽离批次失败: %s", exc)
            continue

        for item in data.get("devices") or []:
            bid = str(item.get("block_id") or "")
            if bid not in valid:
                continue
            try:
                dtype = DeviceType(item.get("device_type"))
                effect = DeviceEffect(item.get("effect"))
                load = CulturalLoad(item.get("cultural_load") or "medium")
            except ValueError:
                continue
            source_text = as_text(item.get("source_text"))
            mechanism = as_text(item.get("mechanism"))
            if not source_text or not mechanism:
                continue

            intensity = max(1, min(int(item.get("intensity") or 3), 5))
            # 查表命中的成语：文化依赖度与装置类型都是确定的，
            # 模型判低了就纠正 —— 判成 low 会让它走 preserve 直接照搬，
            # 而「破釜沉舟」照搬过去只剩「打破锅、沉掉船」。
            hit = ir.classify(source_text.strip())
            if hit is not None and hit.decisive:
                if load is not CulturalLoad.high:
                    result.rule_corrections.append({
                        "text": source_text[:40], "model_said": load.value,
                        "rule_says": "high", "why": hit.reason,
                    })
                    load = CulturalLoad.high
                dtype = DeviceType.idiom

            db.add(NarrativeDevice(
                id=new_id("nd"), chapter_id=chapter.id, block_id=bid,
                device_type=dtype, effect=effect, cultural_load=load,
                strategy=_DEFAULT_STRATEGY[load],
                source_text=source_text[:2000], mechanism=mechanism[:2000],
                setup=as_text(item.get("setup")) or None,
                punch=as_text(item.get("punch")) or None,
                intensity=intensity,
                depends_on=[str(x) for x in (item.get("depends_on") or [])] or None,
            ))
            result.devices += 1
            result.by_type[dtype.value] = result.by_type.get(dtype.value, 0) + 1
            result.by_load[load.value] = result.by_load.get(load.value, 0) + 1
            if load == CulturalLoad.high and len(result.high_load) < 10:
                result.high_load.append({
                    "device_type": dtype.value, "effect": effect.value,
                    "source_text": source_text[:60], "mechanism": mechanism[:100],
                    "intensity": intensity,
                    "depends_on": item.get("depends_on") or [],
                })

    db.flush()
    return result


def build_device_brief(
    db: Session, block_ids: list[str], target_display: str
) -> str:
    """把该批文本涉及的装置整理成给写作者的说明。

    重写时附在 prompt 里 —— 让模型知道这一段哪里有笑点、
    机制是什么、该保留还是该换一个。
    """
    if not block_ids:
        return ""
    rows = list(
        db.execute(
            select(NarrativeDevice).where(NarrativeDevice.block_id.in_(block_ids))
            .order_by(NarrativeDevice.intensity.desc())
        ).scalars()
    )
    if not rows:
        return ""

    lines = ["【叙事装置】这一段有以下效果必须在译文中重现，重现方式见「策略」："]
    for d in rows[:12]:
        plan = strategy_brief(d.strategy, target_display)
        lines.append(
            f"  · [{d.device_type.value}／{d.effect.value}／强度{d.intensity}] "
            f"「{d.source_text[:40]}」\n"
            f"    机制：{d.mechanism[:120]}\n"
            f"    策略：{plan}"
        )
        if d.depends_on:
            lines.append(f"    依赖：{'、'.join(str(x) for x in d.depends_on[:3])}")
    return "\n".join(lines)


def _dump(payload: Any) -> str:
    import json
    return json.dumps(payload, ensure_ascii=False, indent=1)
