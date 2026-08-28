"""说话人归属：把剧本里的 speaker_tag 解析到稳定实体。

script_build 填的 speaker_tag 是原文里的称呼（「小二」「李掌柜」「他」），
刻意不做归一化 —— 归一化交给这一步，因为需要全书实体表才判得准。

不解析的后果很具体：对白绑不到角色的 voice 素材，全部落到旁白音色兜底，
一屋子人说话都是同一个嗓子。

三层匹配，先规则后模型：
  1 精确   display_name 或 aliases 命中
  2 归一化 去掉引号敬称后再比，「李掌柜」→「掌柜」
  3 模型   剩下的歧义项批量交 LLM 判定（「他」指谁要看上下文）
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Chapter, DocStatus, ScriptBlock, ScriptDoc, WorldEntity,
)
from app.models.script import BlockType
from app.pipelines.base import PipelineError, chat_json
from app.worldview.naming import cn_surname

log = logging.getLogger(__name__)

#: 需要剥离的敬称与修饰，用于归一化比对
_HONORIFIC_SUFFIX = (
    "先生", "小姐", "姑娘", "公子", "大人", "老爷", "少爷", "夫人", "娘子",
    "掌柜", "师父", "大夫", "郎中", "员外", "婆婆", "大娘", "大爷",
    "哥", "姐", "叔", "伯", "爷", "娘", "氏", "君", "桑",
)
_PREFIX = ("老", "小", "阿", "大")
_QUOTES = re.compile(r'[「」『』“”‘’"\'（）()\[\]【】]')

#: 无法指向具体人物的泛称，不参与匹配也不送 LLM
_PRONOUNS = frozenset({
    "他", "她", "它", "我", "你", "您", "他们", "她们", "我们", "你们",
    "众人", "众", "有人", "旁人", "路人", "群众", "画外音", "旁白",
})


def clean_tag(tag: str) -> str:
    """只去引号与语气尾字，保留称呼本体。"""
    t = _QUOTES.sub("", (tag or "")).strip()
    if len(t) > 2 and t.endswith("的"):
        t = t[:-1]
    return t.strip()


def tag_variants(tag: str) -> list[str]:
    """产出该称呼的所有可比对形式，按可信度从高到低。

    不赌单一归一化结果 —— 「老张」剥前缀得「张」是对的（姓氏），
    「小二」剥成「二」就错了（「小二」是整体称呼）。
    产出候选让调用方逐个试，命中实体表的才算数。
    """
    base = clean_tag(tag)
    if not base:
        return []
    out = [base]

    for suffix in sorted(_HONORIFIC_SUFFIX, key=len, reverse=True):
        if len(base) > len(suffix) and base.endswith(suffix):
            stem = base[: -len(suffix)].strip()
            if stem:
                out.append(stem)
            break

    for prefix in _PREFIX:
        if len(base) > 1 and base.startswith(prefix):
            stem = base[1:].strip()
            if stem:
                out.append(stem)
            break

    return list(dict.fromkeys(out))


def normalize_tag(tag: str) -> str:
    """主归一化形式。等价于 tag_variants 的最后一个候选。"""
    variants = tag_variants(tag)
    return variants[-1] if variants else ""


@dataclass
class ResolveResult:
    total_tags: int = 0
    resolved_exact: int = 0
    resolved_normalized: int = 0
    resolved_llm: int = 0
    blocks_updated: int = 0
    unresolved: list[str] = field(default_factory=list)
    pronouns_skipped: list[str] = field(default_factory=list)
    mapping: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_tags": self.total_tags,
            "resolved": {
                "exact": self.resolved_exact,
                "normalized": self.resolved_normalized,
                "llm": self.resolved_llm,
            },
            "blocks_updated": self.blocks_updated,
            "unresolved": self.unresolved,
            "pronouns_skipped": self.pronouns_skipped,
            "mapping": self.mapping,
        }


RESOLVE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["mappings"],
    "properties": {
        "mappings": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["speaker_tag", "entity_name"],
                "properties": {
                    "speaker_tag": {"type": "string"},
                    "entity_name": {"type": "string"},
                    "confidence": {"type": "number"},
                    "reason": {"type": "string"},
                },
            },
        }
    },
}

RESOLVE_SYSTEM = """你要把剧本里的说话人称呼对应到人物表中的具体人物。

规则：
1. entity_name 必须从【人物表】里逐字挑一个，不要生造。
2. 一个称呼确实无法确定是谁时，entity_name 填空字符串 —— 宁可留空，
   不要猜。猜错会让这个人全书都用错音色。
3. 职业称呼（掌柜、小二、差役）若上下文明确指向某个具体人物，就对应过去；
   若指的是路人甲，留空。
4. confidence 0–1，低于 0.6 的会被丢弃。
5. reason 一句话说明依据，引用原文线索。"""


def resolve_speakers(
    db: Session,
    chapter: Chapter,
    *,
    use_llm: bool = True,
    min_confidence: float = 0.6,
    overwrite: bool = False,
) -> ResolveResult:
    """解析一章的说话人。已绑定的默认不动。"""
    doc = db.execute(
        select(ScriptDoc).where(
            ScriptDoc.chapter_id == chapter.id, ScriptDoc.status == DocStatus.active
        )
    ).scalars().first()
    if doc is None:
        raise PipelineError("该章节还没有 active 剧本")

    blocks = list(
        db.execute(
            select(ScriptBlock).where(ScriptBlock.script_doc_id == doc.id)
            .order_by(ScriptBlock.seq_no)
        ).scalars()
    )
    targets = [
        b for b in blocks
        if b.block_type == BlockType.dialogue and (b.speaker_tag or "").strip()
        and (overwrite or not b.speaker_entity_id)
    ]

    entities = list(
        db.execute(
            select(WorldEntity).where(WorldEntity.novel_id == chapter.novel_id)
        ).scalars()
    )
    result = ResolveResult()
    if not targets:
        return result
    if not entities:
        raise PipelineError("小说还没有实体，请先抽取实体")

    # 称呼表里有抽取时采下的全部叫法（砚儿、姓沈的、沈镖头），
    # 比 display_name + aliases 完整得多。不并进索引的话，
    # 这些称呼每次都要落到第 3 层去问模型 ——
    # 而答案早就在库里，只是没被查。
    from app.models import EntityAppellation

    appellations: dict[str, list[str]] = {}
    if entities:
        for a in db.execute(
            select(EntityAppellation).where(
                EntityAppellation.entity_id.in_([e.id for e in entities])
            )
        ).scalars():
            surface = str(a.source_surface or "").strip()
            if surface:
                appellations.setdefault(a.entity_id, []).append(surface)

    by_exact: dict[str, WorldEntity] = {}
    by_norm: dict[str, WorldEntity] = {}
    for e in entities:
        for surface in [
            e.display_name, *(e.aliases_json or []), *appellations.get(e.id, []),
        ]:
            s = str(surface or "").strip()
            if not s:
                continue
            by_exact.setdefault(s, e)
            for variant in tag_variants(s):
                by_norm.setdefault(variant, e)
        # 「李掌柜」这类：姓 + 职业称呼，也归到该姓氏的人物
        surname = cn_surname(e.display_name)
        if surname:
            by_norm.setdefault(surname, e)

    tags = sorted({str(b.speaker_tag).strip() for b in targets})
    result.total_tags = len(tags)
    mapping: dict[str, WorldEntity] = {}
    ambiguous: list[str] = []

    for tag in tags:
        clean = clean_tag(tag)
        if clean in _PRONOUNS or any(v in _PRONOUNS for v in tag_variants(clean)):
            result.pronouns_skipped.append(tag)
            continue
        hit = by_exact.get(clean)
        if hit is not None:
            mapping[tag] = hit
            result.resolved_exact += 1
            continue
        # 逐个候选试，命中实体表的才算数
        hit = next(
            (by_norm[v] for v in tag_variants(clean) if v in by_norm), None
        )
        if hit is not None:
            mapping[tag] = hit
            result.resolved_normalized += 1
            continue
        ambiguous.append(tag)

    # ── 第 3 层：剩下的交模型判定 ──
    if ambiguous and use_llm:
        by_name = {e.display_name: e for e in entities}
        samples: dict[str, list[str]] = {}
        for b in targets:
            tag = str(b.speaker_tag).strip()
            if tag in ambiguous and len(samples.get(tag, [])) < 2:
                idx = blocks.index(b)
                ctx = [
                    x.source_text for x in blocks[max(0, idx - 2): idx + 1]
                    if x.source_text
                ]
                samples.setdefault(tag, []).append(" / ".join(ctx)[:160])

        payload = {
            "entities": [
                {"name": e.display_name, "aliases": e.aliases_json or [],
                 "summary": (e.summary or "")[:60]}
                for e in entities if e.kind.value == "character"
            ],
            "unresolved": [
                {"speaker_tag": t, "context": samples.get(t, [])} for t in ambiguous
            ],
        }
        try:
            data, _ = chat_json(
                db,
                [
                    {"role": "system", "content": RESOLVE_SYSTEM},
                    {"role": "user", "content": _dump(payload)},
                ],
                RESOLVE_SCHEMA,
                purpose="extract",
                novel_id=chapter.novel_id, chapter_id=chapter.id,
                ref_kind="speaker_resolve", ref_id=chapter.id,
            )
        except PipelineError as exc:
            log.warning("说话人 LLM 判定失败，保留未解析: %s", exc)
            data = {}

        for item in data.get("mappings") or []:
            tag = str(item.get("speaker_tag") or "").strip()
            name = str(item.get("entity_name") or "").strip()
            conf = float(item.get("confidence") or 0)
            if not tag or not name or tag not in ambiguous:
                continue
            if conf < min_confidence:
                continue
            entity = by_name.get(name)
            if entity is None:
                continue
            mapping[tag] = entity
            result.resolved_llm += 1

    result.unresolved = [t for t in ambiguous if t not in mapping]
    result.mapping = {t: e.display_name for t, e in mapping.items()}

    for b in targets:
        entity = mapping.get(str(b.speaker_tag).strip())
        if entity is not None and b.speaker_entity_id != entity.id:
            b.speaker_entity_id = entity.id
            result.blocks_updated += 1

    db.flush()
    return result


def resolve_novel(
    db: Session, novel_id: str, *, use_llm: bool = True, overwrite: bool = False
) -> dict[str, Any]:
    """整本书逐章解析。"""
    chapters = list(
        db.execute(
            select(Chapter).where(Chapter.novel_id == novel_id)
            .order_by(Chapter.order_no)
        ).scalars()
    )
    total = ResolveResult()
    done = 0
    for chapter in chapters:
        try:
            r = resolve_speakers(db, chapter, use_llm=use_llm, overwrite=overwrite)
        except PipelineError:
            continue
        done += 1
        total.total_tags += r.total_tags
        total.resolved_exact += r.resolved_exact
        total.resolved_normalized += r.resolved_normalized
        total.resolved_llm += r.resolved_llm
        total.blocks_updated += r.blocks_updated
        total.unresolved.extend(t for t in r.unresolved if t not in total.unresolved)
        total.mapping.update(r.mapping)
    out = total.as_dict()
    out["chapters_processed"] = done
    return out


def _dump(payload: Any) -> str:
    import json
    return json.dumps(payload, ensure_ascii=False, indent=1)
