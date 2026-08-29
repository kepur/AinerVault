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
    Novel,
    Chapter, LexiconCategory, LexiconSource, ReviewStatus, ScriptBlock, ScriptDoc,
    DocStatus, WorldLexicon, WorldLexiconTemplate, WorldProfile, WorldTransform, utcnow,
)
from app.pipelines.base import PipelineError, chat_json, as_text, as_items
from app.worldview.matcher import LexiconMatcher
from app.worldview import lexicon_rules as lr
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
    #: 构词规则推翻模型的记录。为空说明两者判得一致
    rule_corrections: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "scanned_blocks": self.scanned_blocks,
            "template_hits": self.template_hits,
            "hit_terms": len(self.template_hits),
            "mined_created": self.mined_created,
            "mined_terms": self.mined_terms,
            "unresolved": self.unresolved,
            "rule_corrections": self.rule_corrections,
        }


MINE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["terms"],
    "properties": {
        "terms": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["source_term", "category", "target_term",
                             "no_equivalent", "rationale"],
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
                    "no_equivalent": {"type": "boolean"},
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

关键原则：
1. 目标世界观里没有对应物时（如中世纪欧洲没有茶），
   回退到功能等价的上位概念，而不是直译成一个时代外的词。
2. **年代必须对得上**。给的译法要属于目标世界观那个年代 ——
   给摄政英国配一个工业时代的词，比不译更糟：读者一眼看出穿帮，
   而且这种错藏在一个看似地道的英文词里，审校时最容易漏过。
   下面会给出该世界观「不存在的东西」清单，那些词一个都不能用。
3. 目标语言的书写系统要对。名物译法要用该世界观实际使用的文字，
   不是拉丁转写。

forbidden_targets 填「绝不能出现在译文里的错误译法」，
通常是直译词与原文词本身。

no_equivalent —— **读者要理解它，是否必须先知道一整套结构**。

判准不是「有没有译法」。实跑时你们把「筑基」判成了 false，
理由是它有译法 foundation establishment —— **译法有，概念没有**。
英语读者看到 foundation establishment，不知道它是九境里的第二境，
不知道它比「练气七层→八层」跨度大得多，更不知道过了这一境「人就不是人了」。

**词能译，体系不能译。**

  true   它是某个体系里的一环，读者要懂它必须先懂整个体系：
         修真的境界（练气／筑基／金丹／元婴）、宗门辈分、
         力量等级、自造的技术设定、灵石这类体系内的货币
  false  换个说法就懂：客栈→inn、腰刀→sabre、捕快→constable。
         读者不需要额外知识

这一栏决定它**要不要写进正文前的导读**。体系性的词有几十个，
每个都在正文里就地解释的话，读者每隔两页被打断一次，读的就不是小说了；
而换个说法就懂的词写进导读是浪费读者的耐心，
耐心是导读最稀缺的资源。

拿不准时问自己：**只看这一个词的译法，读者能不能知道它在体系里的位置？**
不能就是 true。"""


def _profile_constraints(profile: WorldProfile | None) -> str:
    """把档案里的硬约束摊给模型。

    这些字段一直存在库里却从没进过挖掘提示词 —— 于是模型只知道
    「中世纪欧洲」四个字，年代边界、禁止物、书写系统全靠它自己猜。
    v1 的 culture_packs_json 就是这么废掉的：存了，不用。
    """
    if profile is None:
        return ""
    axes = profile.axes_json or {}
    visual = profile.visual_json or {}
    lang = profile.language_json or {}
    lines: list[str] = []
    span = axes.get("era_span")
    if isinstance(span, list) and len(span) == 2:
        lines.append(f"【年代】{span[0]}–{span[1]}，此年代之后才有的事物一律不得使用")
    if axes.get("social_context"):
        lines.append(f"【社会背景】{axes['social_context']}")
    if axes.get("tech_level"):
        lines.append(f"【技术水平】{axes['tech_level']}")
    dont = visual.get("visual_dont") or []
    if dont:
        lines.append(
            "【该世界观不存在的东西】" + "、".join(str(x) for x in dont[:20])
            + " —— 译法里绝不能出现这些，也不能出现同年代之外的等价物"
        )
    do = visual.get("visual_do") or []
    if do:
        lines.append("【该世界观的典型事物】" + "、".join(str(x) for x in do[:20]))
    if lang.get("name_script"):
        lines.append(f"【书写系统】{lang['name_script']}")
    if lang.get("register"):
        lines.append(f"【文体层级】{lang['register']}")
    return "\n".join(lines) + "\n" if lines else ""


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


def _candidate_tokens(
    texts: list[str], covered: set[str], top_n: int,
    language_code: str | None = None,
) -> list[tuple[str, int]]:
    """挑出送 LLM 判定的候选词。

    统计层负责去碎片和降噪，LLM 层负责判定语义与译法，各司其职。
    按源语言分流两套算法：不分词的语言（中日）用凝固度 + 邻接熵，
    空格语言用词频反选 + 搭配强度 —— 后者根本没有切分问题，
    在它上面跑 n-gram 是把简单问题做复杂。
    """
    return mine_candidates(
        texts, covered, language_code=language_code, min_freq=2, limit=top_n
    )


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

    src_lang = None
    novel = db.get(Novel, chapter.novel_id) if chapter.novel_id else None
    if novel is not None:
        src_lang = novel.source_language_code
    if not src_lang:
        src_profile_early = db.get(WorldProfile, transform.source_profile_id)
        src_lang = (
            (src_profile_early.language_json or {}).get("code")
            if src_profile_early else None
        )
    src_profile = db.get(WorldProfile, transform.source_profile_id)
    tgt_profile = db.get(WorldProfile, transform.target_profile_id)
    known_sample = ", ".join(sorted(covered)[:60])

    # 混合源圈层：一章横跨两个世界时，挖出的词条要标明属于哪一个。
    # 不标的话，「先生」在古代场和现代场会争夺同一个 (映射, 源词) 键，
    # 后写的覆盖先写的 —— 而覆盖掉哪一个取决于挖掘顺序。
    #
    # **候选词也按圈层各算各的。** 用整章的候选去挖每一个世界，
    # 等于拿现代场的「PPT」去对着唐代的原文找译法 ——
    # 模型要么硬编一个，要么整批作废，两种都比不挖更糟。
    worlds = _blocks_by_world(db, transform, blocks)
    multi = len(worlds) > 1
    for world_id, world_texts in worlds:
        if not world_texts:
            continue
        # **已覆盖集合按圈层各算各的。**
        # 共享一个集合的话，古代场挖过「先生」之后，现代场的候选就把它排除了 ——
        # 而「同一个词在两个世界里译法不同」恰恰是这整套机制存在的理由。
        # 排除掉它，功能就是死的：库里永远不会出现需要消歧的词条。
        w_covered = (
            {r.source_term for r in rows
             if r.source_profile_id in (world_id, None)}
            | {a for r in rows if r.source_profile_id in (world_id, None)
               for a in (r.source_aliases or [])}
            if multi else covered
        )
        w_candidates = _candidate_tokens(
            world_texts, w_covered, max_candidates, src_lang)
        # 候选词是**降噪加速**手段，不是前置条件。
        # 短章节、新书开头、名物密度低的段落，统计层本来就给不出候选 ——
        # 此时若直接跳过，LLM 层根本不被调用，用户只看到「勘探完成，0 条」，
        # 完全不知道是没词还是没跑。所以退化为直接把原文交给模型找。
        direct = not w_candidates
        if direct:
            log.info("统计层无候选（语料 %d 字），转为直接从原文挖掘",
                     sum(len(t) for t in world_texts))
        # 原文节选压到 3000 字：每条词条的输出（译法 + 读音 + 禁用词 + 依据）
        # 是输入的好几倍，一次给太多原文，模型会试图把整章的名物一次列完，
        # 直接撞穿输出上限。宁可分章多跑几次 —— 词条是跨章累积的，不会丢。
        excerpt = "\n".join(world_texts)[:3000]
        # 分批送。**限流不够，必须分批** —— 上一版只是把原文压到 3000 字、
        # 候选压到 24 个，结果仍然两轮都被截断：每条词条的输出是候选词
        # 本身的几十倍，24 条就要生成上万 token。压输入解决不了输出爆炸。
        steps = [[]] if direct else [
            w_candidates[i : i + _MINE_BATCH]
            for i in range(0, len(w_candidates), _MINE_BATCH)
        ]
        for batch in steps:
            _mine_batch(db, transform, chapter, src_profile, tgt_profile,
                        batch, direct, excerpt, known_sample, w_covered,
                        result, world_texts, source_profile_id=world_id)
    db.flush()
    return result


def _blocks_by_world(
    db: Session, transform: WorldTransform, blocks: list,
) -> list[tuple[str | None, list[str]]]:
    """把一章的文本按源圈层分组。

    单圈层（绝大多数小说）返回一项 `(None, 全部文本)` —— None 的意思是
    「这条词条通用」，不挂圈层。挂上主源圈层反而有害：
    以后加第二个源圈层时，这些老条目会突然变成「只属于古代场」。

    多圈层时按场次所属分组，每组的词条挂上自己的圈层。
    """
    from app.pipelines.source_worlds import source_profiles

    if len(source_profiles(db, transform)) < 2:
        return [(None, [b.source_text for b in blocks if b.source_text])]

    from app.models import Scene

    scene_world: dict[str, str | None] = {}
    grouped: dict[str | None, list[str]] = {}
    for b in blocks:
        if not b.source_text:
            continue
        world = None
        if b.scene_id:
            if b.scene_id not in scene_world:
                sc = db.get(Scene, b.scene_id)
                scene_world[b.scene_id] = sc.source_profile_id if sc else None
            world = scene_world[b.scene_id]
        grouped.setdefault(world, []).append(b.source_text)
    return sorted(grouped.items(), key=lambda kv: (kv[0] is None, kv[0] or ""))


#: 单次挖掘的候选词上限。词条的输出量是候选词的几十倍。
_MINE_BATCH = 10


def _mine_batch(
    db: Session, transform: WorldTransform, chapter: Chapter,
    src_profile: WorldProfile | None, tgt_profile: WorldProfile | None,
    candidates: list[tuple[str, int]], direct: bool,
    excerpt: str, known_sample: str, covered: set[str],
    result: SurveyResult, texts: list[str],
    source_profile_id: str | None = None,
) -> None:
    data, _task = chat_json(
        db,
        [
            {"role": "system",
             "content": f"{MINE_SYSTEM}\n\n{lr.brief_for_prompt()}"},
            {
                "role": "user",
                "content": (
                    f"【源世界观】{src_profile.display_name if src_profile else '?'}\n"
                    f"【目标世界观】{tgt_profile.display_name if tgt_profile else '?'}\n"
                    f"{_profile_constraints(tgt_profile)}"
                    f"【目标语言】{transform.target_language_code}\n\n"
                    f"【已有词表】{known_sample}\n\n"
                    + (
                        "【候选词】统计层未能给出候选（语料太短或名物分散），"
                        "请直接通读原文找名物词。"
                        # 不设上限时模型会试图把整章的名物一次列完，
                        # 每条又带译法/读音/禁用词/依据，输出直接撞穿上限。
                        # 分批在这条路径上不起作用 —— 它没有候选可分。
                        f"**本次最多给 {_MINE_BATCH} 条**，"
                        "挑出现频率高、对场景最关键的；漏掉的下一章还会遇到，"
                        "词条是跨章累积的。\n\n"
                        if direct else
                        f"【高频候选词】"
                        f"{', '.join(f'{t}({c})' for t, c in candidates)}\n"
                        "这是统计层筛出的高频词，仅供参考 —— "
                        "原文里的名物不限于此表，看到别的也要收。\n\n"
                    )
                    + f"【原文节选】\n{excerpt}"
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

    for item in as_items(data, "terms"):
        src = as_text(item.get("source_term"))
        tgt = as_text(item.get("target_term"))
        if not src or not tgt or src in covered:
            continue
        try:
            category = LexiconCategory(item.get("category") or "other")
        except ValueError:
            category = LexiconCategory.other

        # 构词规则复核。category 决定这条词在提示词里怎么呈现、
        # 审计时怎么比对 —— 让模型判「腰刀」是什么类，
        # 换个模型就可能判成 other，而那会让它彻底失去类别约束。
        cv = lr.classify(src)
        if cv is not None and cv.decisive and cv.category is not category:
            result.rule_corrections.append({
                "term": src, "model_said": category.value,
                "rule_says": cv.category.value, "why": cv.reason,
            })
            category = cv.category

        db.add(WorldLexicon(
            id=new_id("lx"),
            transform_id=transform.id,
            canonical_key=item.get("canonical_key") or f"{category.value}.{src}",
            category=category,
            source_term=src,
            target_term=tgt,
            target_reading=item.get("target_reading") or None,
            forbidden_targets=item.get("forbidden_targets") or [src],
            # 目标文化里有没有对应物。**导读的选材全靠这一栏** ——
            # 有对应物的词写进导读是浪费读者的耐心，而耐心是导读最稀缺的资源
            no_equivalent=bool(item.get("no_equivalent")),
            # 这条属于哪个源圈层。单圈层时为 None（通用）——
            # 挂上主源圈层反而有害：以后加第二个源圈层时，
            # 这些老条目会突然变成「只属于第一个世界」
            source_profile_id=source_profile_id,
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

    # 分批累积而非覆盖 —— 每批各有自己没认出来的词
    result.unresolved.extend(t for t, _ in candidates if t not in covered)
    db.flush()


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

def promote_to_template(
    db: Session, transform: WorldTransform, *,
    min_status: ReviewStatus = ReviewStatus.approved,
    overwrite: bool = False,
) -> dict[str, Any]:
    """把这个映射下审定的词条沉淀成可复用模板。

    「客栈 → inn」这个结论只取决于**源圈层 × 目标圈层**，与是哪本小说无关。
    不沉淀的话，每本新书都要重挖一遍：烧钱，而且两次结果可能不一致 ——
    同一个工作室的两本书里客栈译法不同，读者是会发现的。

    25 个圈层两两配对有 600 种组合，不可能预置。所以路径是反的：
    先挖，审定后沉淀，下一本书直接导入。用得越多，冷启动成本越低。

    只收 approved 及以上的词条 —— candidate 是模型的猜测，
    把没审过的东西沉淀成「模板」，等于把错误固化成标准。
    """
    src = db.get(WorldProfile, transform.source_profile_id)
    tgt = db.get(WorldProfile, transform.target_profile_id)
    if src is None or tgt is None:
        raise PipelineError("world profile 缺失")

    order = {ReviewStatus.candidate: 0, ReviewStatus.approved: 1, ReviewStatus.locked: 2}
    rows = [
        r for r in db.execute(
            select(WorldLexicon).where(WorldLexicon.transform_id == transform.id)
        ).scalars()
        if r.target_term and order.get(r.status, 0) >= order[min_status]
    ]
    if not rows:
        raise PipelineError(
            f"没有达到 {min_status.value} 的词条可沉淀。"
            f"模板是给别的书当起点用的 —— 未审的猜测沉淀进去等于固化错误。"
        )

    pair_code = f"{src.code}__{tgt.code}"
    entries = [
        {
            "source_term": r.source_term,
            "source_aliases": r.source_aliases or [],
            "category": r.category.value,
            "canonical_key": r.canonical_key,
            "target_term": r.target_term,
            "target_reading": r.target_reading,
            "forbidden_targets": r.forbidden_targets or [],
            "rationale": r.rationale,
        }
        for r in rows
    ]

    existing = db.execute(
        select(WorldLexiconTemplate)
        .where(WorldLexiconTemplate.pair_code == pair_code)
        .order_by(WorldLexiconTemplate.version.desc())
    ).scalars().first()

    if existing is not None and not overwrite:
        # 合并而非替换：别的书审出来的词条同样有效，不该被这一本覆盖掉。
        # 冲突时保留已有的 —— 先到的那条经历过更多轮审校。
        by_term = {e["source_term"]: e for e in existing.entries_json or []}
        added = 0
        for e in entries:
            if e["source_term"] not in by_term:
                by_term[e["source_term"]] = e
                added += 1
        existing.entries_json = sorted(by_term.values(), key=lambda x: x["source_term"])
        db.flush()
        return {
            "template_id": existing.id, "pair_code": pair_code,
            "action": "merged", "added": added,
            "total": len(existing.entries_json),
        }

    version = (existing.version + 1) if existing is not None else 1
    tpl = WorldLexiconTemplate(
        id=new_id("lt"), pair_code=pair_code,
        display_name=f"{src.display_name} → {tgt.display_name}",
        source_profile_code=src.code, target_profile_code=tgt.code,
        entries_json=sorted(entries, key=lambda x: x["source_term"]),
        version=version,
        description=f"由《{transform.novel_id}》的审定词条沉淀，{len(entries)} 条",
    )
    db.add(tpl)
    db.flush()
    return {
        "template_id": tpl.id, "pair_code": pair_code,
        "action": "created", "version": version, "total": len(entries),
    }


def seed_defaults(db: Session) -> dict[str, int]:
    """把预置世界观档案与词表模板灌进库。幂等，可反复调用。"""
    from app.seed.director_profiles import DIRECTOR_PROFILES
    from app.seed.lexicon_templates import TEMPLATES
    from app.seed.culture_packs import CULTURE_PACKS
    from app.seed.world_profiles import PROFILES
    from app.models import DirectorProfile, ProfileRole, ProfileStatus

    created_p = created_t = created_d = updated_p = 0

    # PROFILES 是最早那批源/目标档案，CULTURE_PACKS 是按语言圈层铺开的那批。
    # 两者结构相同，合起来灌 —— 分成两个文件只是为了各自能独立维护。
    for p in [*PROFILES, *CULTURE_PACKS]:
        exists = db.execute(
            select(WorldProfile).where(
                WorldProfile.code == p["code"], WorldProfile.version == 1
            )
        ).scalars().first()
        if exists:
            # 只补空缺，不覆盖 —— 用户改过的档案不能被重灌种子吃掉。
            # 需要这条是因为 language.code 是后加的字段：早先建的档案没有它，
            # 纯「已存在就跳过」会让它们永远缺，而缺了就选不出 TTS 音色。
            lang = dict(exists.language_json or {})
            changed = False
            for k, v in (p.get("language") or {}).items():
                if v not in (None, "", {}, []) and not lang.get(k):
                    lang[k] = v
                    changed = True
            if changed:
                exists.language_json = lang
                updated_p += 1
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

    for d in DIRECTOR_PROFILES:
        exists = db.execute(
            select(DirectorProfile).where(
                DirectorProfile.code == d["code"], DirectorProfile.version == 1
            )
        ).scalars().first()
        if exists:
            continue
        db.add(DirectorProfile(
            id=new_id("dp"), code=d["code"], display_name=d["display_name"],
            summary=d.get("summary"), camera_json=d.get("camera"),
            editing_json=d.get("editing"), composition_json=d.get("composition"),
            lighting_json=d.get("lighting"), avoid_json=d.get("avoid"),
            version=1, status="active",
        ))
        created_d += 1

    db.flush()
    return {"profiles": created_p, "profiles_updated": updated_p,
            "templates": created_t, "director_profiles": created_d}
