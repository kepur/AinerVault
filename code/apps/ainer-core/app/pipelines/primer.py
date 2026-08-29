"""生成导读篇 —— 把体系一次讲完，好让正文直接用原物。

## 它解决的是节奏，不是信息

信息层面，逐处脚注也能把「筑基」讲清楚。问题在**节奏**：
一本仙侠里这类术语有几十个，每个第一次出现都停下来解释一段，
读者每隔两页被打断一次，读的就不是小说了。

导读把这几十个术语的**结构**一次讲完 —— 结构才是关键：
读者需要知道的不是「筑基是什么」，而是「筑基比练气高、比金丹低」。
那是个体系，逐点解释永远拼不出来。

## 讲什么，不讲什么

只讲**目标读者不会的**。「客栈」译成 inn 就够了，不必进导读；
「筑基」没有任何对应物，必须进。判断依据是名物词表里那些
**没有等价物、只能音译**的条目，以及装置表里文化依赖度高的那些。

讲得太多和太少一样糟：太长没人读，读者直接跳过去，等于没写。
所以有字数上限，超了要砍，砍的顺序是按重要度倒着来。

## covers 是导读与正文的接口

导读讲过的词条落进 covers_json，翻译时以此把 gloss_inline 降为 preserve。
不落库的话导读写了也白写 —— 正文照样逐处解释，
读者读完导读又被解释一遍。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ids import new_id
from app.models import (
    Chapter, CulturalLoad, Fidelity, NarrativeDevice, PrimerKind, ReviewStatus,
    LexiconCategory, WorldLexicon, WorldPrimer, WorldProfile, WorldTransform,
)
from app.pipelines.base import PipelineError, as_items, as_list, as_text, chat_json
from app.worldview import profile_resolve

log = logging.getLogger(__name__)

#: 导读的字数上限（目标语词数）。**超了就没人读** ——
#: 没人读的导读比没有导读更糟：正文按「已经讲过」来写，
#: 而读者并没有读到。
MAX_WORDS = 900
#: 低于这个数说明没讲清楚。一套境界体系讲不到两百词，
#: 多半只是把词列了一遍，没讲它们之间的关系
MIN_WORDS = 180

#: 哪几档力度需要导读。
#: 存真档**必须**有 —— 它的整个前提就是「术语原样保留，读者靠导读挂靠」。
#: 移植档不需要：体系已经换成目标文化的了，没有新东西要交代。
NEEDS_PRIMER = {Fidelity.preserve_world: "required",
                Fidelity.anchored: "recommended",
                Fidelity.transplant_world: "unnecessary"}

PRIMER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["title", "sections"],
    "properties": {
        "title": {"type": "string"},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["kind", "heading", "body", "covers"],
                "properties": {
                    "kind": {"type": "string",
                             "enum": [k.value for k in PrimerKind]},
                    "heading": {"type": "string"},
                    "body": {"type": "string"},
                    "covers": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "rationale": {"type": "string"},
    },
}

PRIMER_SYSTEM = """你要为一本译作写**正文前的导读**，用目标语言写。

## 为什么要有它

原著里有一批目标读者完全没有对应概念的东西 —— 修真的境界体系、
自造的技术设定、宗门辈分。就地解释的话，这类词有几十个，
每个第一次出现都停下来讲一段，读者每隔两页被打断一次，读的就不是小说了。

导读把这些**一次讲完**，正文里就可以直接用，读者已经有挂靠点。

## 讲结构，不讲词条

读者需要知道的不是「筑基是什么」，而是**「筑基比练气高、比金丹低」**。
那是个体系，逐点解释永远拼不出来。

  ✓ 「修行分九境，前三境（练气、筑基、金丹）是凡人可及的，
     第四境元婴之后寿命大幅延长 —— 所以书里说某人『还没结丹』，
     意思是他还是个普通人。」
  ✗ 「练气：修行的第一个阶段。筑基：修行的第二个阶段。」
     —— 这是词汇表，不是导读。读者读完仍然不知道差距有多大

## 只讲目标读者不会的

有对应物的不要讲。「客栈」译成 inn 就够了，写进导读是浪费读者的耐心。
判断标准：这个词在目标语里**只能音译**，或者它的分量／关系
在目标文化里对不上号。

## 字数

全篇不超过 %d 个词。超了没人读，而没人读的导读比没有导读更糟 ——
正文会按「已经讲过」来写，可读者并没有读到。
讲不满 %d 词多半是只列了词没讲关系，那样等于没写。

## covers

每一节列出它**讲清楚了哪些词条**，用给你的 canonical_key 原样填。
这一栏决定正文里这些词能不能直接用原物，填错会让正文重复解释。

## 语气

这是给读者读的，不是给编辑看的说明书。用叙述的语气，
可以带一点这本书的味道，但不要剧透情节。"""


@dataclass
class PrimerResult:
    primer_id: str = ""
    sections: int = 0
    covers: int = 0
    word_count: int = 0
    trimmed: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "primer_id": self.primer_id, "sections": self.sections,
            "covers": self.covers, "word_count": self.word_count,
            "trimmed": self.trimmed, "warnings": self.warnings,
        }


def fidelity_of(transform: WorldTransform) -> Fidelity:
    """这次映射的力度档。policy 里没写就按折中 ——
    默认最稳：存真档没配导读会让读者撞上一堆生词，
    移植档会把原著体系抹掉，两头都是「选错了很难看出来」。"""
    raw = str((transform.policy_json or {}).get("fidelity") or "").strip()
    try:
        return Fidelity(raw)
    except ValueError:
        return Fidelity.anchored


#: 这几类名物最常没有对应物。用作**回落判据** ——
#: no_equivalent 是词表挖掘该填的，存量数据没填，
#: 而「没填」不该表现为「导读里什么都没有」
_LIKELY_UNIQUE = (LexiconCategory.custom, LexiconCategory.ritual,
                  LexiconCategory.title, LexiconCategory.honorific)
#: rationale 里出现这些词，说明当初判过它没有等价物
_NO_EQ_HINT = ("音译", "无对应", "没有对应", "无等价", "造词", "transliterat")


def _untranslatable(db: Session, transform_id: str) -> list[WorldLexicon]:
    """目标文化里没有对应物的词条 —— 导读要讲的就是这些。

    有等价物的不进导读：写进去是浪费读者的耐心，
    而耐心是导读最稀缺的资源。

    优先看 no_equivalent（词表挖掘时判的）。存量词表没有这一栏，
    所以回落到两条线索：类别（风俗／礼仪／称号最常没有对应物）
    与当初的判断理由。**回落只是回落** —— 它会漏也会多，
    所以走这条路时报一句，让人知道该去补词表而不是怪导读没讲全。
    """
    rows = list(db.execute(
        select(WorldLexicon).where(WorldLexicon.transform_id == transform_id)
    ).scalars())
    marked = [r for r in rows if r.no_equivalent]
    if marked:
        return marked
    return [
        r for r in rows
        if r.category in _LIKELY_UNIQUE
        or any(h in (r.rationale or "") for h in _NO_EQ_HINT)
    ]


def _device_terms(db: Session, novel_id: str) -> list[NarrativeDevice]:
    """文化依赖度高的装置。它们是导读的另一半来源 ——
    词表管名物，装置管典故与体系性的说法。"""
    return list(db.execute(
        select(NarrativeDevice)
        .join(Chapter, NarrativeDevice.chapter_id == Chapter.id)
        .where(Chapter.novel_id == novel_id,
               NarrativeDevice.cultural_load == CulturalLoad.high)
        .limit(40)
    ).scalars())


def generate_primer(
    db: Session, transform: WorldTransform, *, force: bool = False,
) -> PrimerResult:
    """写一篇导读。"""
    profile = db.get(WorldProfile, transform.target_profile_id)
    if profile is None:
        raise PipelineError("目标世界观档案缺失")
    fid = fidelity_of(transform)
    result = PrimerResult()
    if NEEDS_PRIMER[fid] == "unnecessary":
        result.warnings.append(
            "移植档不需要导读 —— 体系已经换成目标文化的了，没有新东西要交代。"
            "仍然生成了一份，但多半用不上")

    existing = db.execute(
        select(WorldPrimer).where(WorldPrimer.transform_id == transform.id)
        .order_by(WorldPrimer.version.desc())
    ).scalars().first()
    if existing is not None and not force:
        if existing.locked or existing.edited_by_human:
            raise PipelineError("已有人工改过或锁定的导读，重写请传 force")

    lex = _untranslatable(db, transform.id)
    if lex and not any(r.no_equivalent for r in lex):
        result.warnings.append(
            "词表里没有一条标了「无对应物」，导读的选材是按类别与理由**猜**的 —— "
            "会漏也会多。跑一次词表挖掘把这一栏填上，导读的选材才准")
    devices = _device_terms(db, transform.novel_id)
    if not lex and not devices:
        raise PipelineError(
            "没有需要导读的东西 —— 名物词表里没有音译条目，"
            "装置表里也没有高文化依赖项。先跑词表挖掘与装置抽取")

    resolved = profile_resolve.resolve(db, profile)
    lang = resolved.get("language") or {}
    axes = resolved.get("axes") or {}

    terms = "\n".join(
        f"  {r.canonical_key}｜{r.source_term} → {r.target_term}"
        + (f"（{r.rationale[:60]}）" if r.rationale else "")
        for r in lex[:60]
    )
    dev = "\n".join(
        f"  {d.surface}（{d.device_type.value}）{(d.mechanism or '')[:80]}"
        for d in devices[:20]
    )
    chain = " ← ".join(p["display_name"] for p in resolved["chain"])
    user = (
        f"【写给谁】{profile.display_name}"
        + (f"（虚构圈层，语言与常识底座：{chain}）" if profile.is_fictional else "")
        + f"\n【语域】{lang.get('register') or '未定'}"
          f"　【年代背景】{axes.get('era_span') or ''}"
        + f"\n【转译力度】{fid.value} —— "
        + ("术语原样保留，读者全靠这篇导读挂靠，务必讲清体系"
           if fid is Fidelity.preserve_world else
           "体系保留但关键处会给目标文化的锚点，导读讲结构即可")
        + ("\n\n【只能音译的名物条目】\n" + terms if terms else "")
        + ("\n\n【文化依赖度高的说法】\n" + dev if dev else "")
    )

    data, task = chat_json(
        db,
        [{"role": "system", "content": PRIMER_SYSTEM % (MAX_WORDS, MIN_WORDS)},
         {"role": "user", "content": user}],
        PRIMER_SCHEMA, purpose="devices", novel_id=transform.novel_id,
        ref_kind="world_primer", ref_id=transform.id, max_tokens=8192,
    )

    sections = []
    for item in as_items(data, "sections"):
        kind = as_text(item.get("kind")).strip()
        if kind not in {k.value for k in PrimerKind}:
            kind = PrimerKind.system.value
        body = as_text(item.get("body")).strip()
        if not body:
            continue
        sections.append({
            "kind": kind,
            "heading": as_text(item.get("heading")).strip()[:200],
            "body": body,
            "covers": [c for c in as_list(item.get("covers")) if c][:40],
        })
    if not sections:
        raise PipelineError("模型没有给出任何导读章节")

    sections, trimmed = _trim(sections)
    result.trimmed = trimmed

    body = "\n\n".join(
        (f"## {s['heading']}\n\n" if s["heading"] else "") + s["body"]
        for s in sections
    )
    covers = list(dict.fromkeys(c for s in sections for c in s["covers"]))
    words = _words(body)

    row = existing if (existing is not None and force) else None
    if row is None:
        row = WorldPrimer(
            id=new_id("wp"), transform_id=transform.id,
            version=(existing.version + 1) if existing else 1,
        )
        db.add(row)
    row.title = as_text(data.get("title")).strip()[:256] or None
    row.sections_json = sections
    row.body = body
    row.covers_json = covers or None
    row.word_count = words
    row.model = task.model
    row.rationale = as_text(data.get("rationale")).strip()[:1000] or None
    row.status = ReviewStatus.candidate
    db.flush()

    if words < MIN_WORDS:
        result.warnings.append(
            f"只有 {words} 词 —— 多半只是把词列了一遍，没讲清它们之间的关系。"
            f"读者读完仍然不知道「筑基」比「练气」高多少")
    if fid is Fidelity.preserve_world and not covers:
        result.warnings.append(
            "存真档但导读没有覆盖任何词条 —— 正文会照旧逐处解释，"
            "读者读完导读又被解释一遍")

    result.primer_id = row.id
    result.sections = len(sections)
    result.covers = len(covers)
    result.word_count = words
    return result


def _words(text: str) -> int:
    """目标语词数。CJK 按字算，拉丁按空格分词 ——
    两种文字的「一个词」不是一回事，混着数会得出没有意义的数字。"""
    latin = len([w for w in text.replace("\n", " ").split(" ") if w.strip()])
    cjk = sum(1 for ch in text if "㐀" <= ch <= "鿿")
    return cjk if cjk > latin else latin


def _trim(sections: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """超长就砍，从最后一节砍起。

    **不是按比例压缩每一节。** 压缩会把每节都讲成半截，
    而半截的体系说明比没有更糟 —— 读者以为自己懂了。
    整节砍掉至少留下的是完整的。

    砍的顺序按 PrimerKind 的重要度倒着来：体系最要紧，类型约定最次要。
    """
    order = {k.value: i for i, k in enumerate(PrimerKind)}
    ranked = sorted(range(len(sections)),
                    key=lambda i: (order.get(sections[i]["kind"], 99), i))
    keep: list[int] = []
    total = 0
    dropped: list[str] = []
    for i in ranked:
        w = _words(sections[i]["body"])
        if total + w > MAX_WORDS and keep:
            dropped.append(sections[i]["heading"] or sections[i]["kind"])
            continue
        keep.append(i)
        total += w
    return [sections[i] for i in sorted(keep)], dropped


def covered_terms(db: Session, transform: WorldTransform) -> set[str]:
    """导读讲过的词条**表层文字**，供翻译时判 explained。

    返回的是 source_term 而不是 canonical_key —— 装置表里存的是原文片段，
    两边要能对上。covers 里存的是 canonical_key（那是词表的稳定标识），
    所以这里查一次词表把它翻成表层。

    只认已审核通过的导读：候选状态的导读还可能被改，
    按它把正文的解释去掉，改完就对不上了。
    """
    row = db.execute(
        select(WorldPrimer).where(
            WorldPrimer.transform_id == transform.id,
            WorldPrimer.status.in_([ReviewStatus.approved, ReviewStatus.locked]),
        ).order_by(WorldPrimer.version.desc())
    ).scalars().first()
    keys = list((row.covers_json or [])) if row is not None else []
    if not keys:
        return set()
    rows = db.execute(
        select(WorldLexicon).where(
            WorldLexicon.transform_id == transform.id,
            WorldLexicon.canonical_key.in_(keys),
        )
    ).scalars()
    out: set[str] = set()
    for r in rows:
        out.add(r.source_term)
        out.update(str(a) for a in (r.source_aliases or []))
    return out
