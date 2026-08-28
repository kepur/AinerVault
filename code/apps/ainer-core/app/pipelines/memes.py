"""文化梗抽取与渲染。

分两步是因为两件事的依据不同：
    抽取  只看原文 —— 这是什么梗、什么圈子、什么时候的、字面义与实际用法差多少
    渲染  才看目标 —— 到那个圈层里该怎么呈现

合成一步会逼模型在还没想清「这是什么」的时候就先想「怎么译」，
结果是直译一个它自己都没弄懂的东西。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.ids import new_id
from app.models import (
    Chapter, DeviceStrategy, DocStatus, MemeEntry, MemeRegister, MemeRendering,
    PlotLoad, ReviewStatus, ScriptBlock, ScriptDoc, Volatility, WorldProfile,
    WorldTransform, choose_strategy,
)
from app.models.narrative_device import CulturalLoad
from app.pipelines.base import PipelineError, chat_json

log = logging.getLogger(__name__)

EXTRACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["memes"],
    "properties": {
        "memes": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["surface", "register", "actual_use", "volatility"],
                "properties": {
                    "surface": {"type": "string"},
                    "register": {"type": "string", "enum": [r.value for r in MemeRegister]},
                    "literal_gloss": {"type": "string"},
                    "actual_use": {"type": "string"},
                    "origin": {"type": "string"},
                    "origin_year": {"type": "integer"},
                    "circle": {"type": "string"},
                    "platform": {"type": "string"},
                    "volatility": {"type": "string",
                                   "enum": [v.value for v in Volatility]},
                    "plot_load": {"type": "string",
                                  "enum": [p.value for p in PlotLoad]},
                    "cultural_load": {"type": "string",
                                      "enum": ["low", "medium", "high"]},
                    "block_id": {"type": "string"},
                    "evidence": {"type": "string"},
                },
            },
        }
    },
}

EXTRACT_SYSTEM = """你是文化梗的鉴定专家。从文本里找出「字面义不等于实际用法」的表达。

要找的是这些：
  网络流行语      yyds、破防了、栓Q、绝绝子、麻了
  社会现象词      内卷、躺平、鸡娃、社死、emo
  亚文化黑话      二次元、饭圈、游戏圈、职场的行话
  典故与成语      庄周梦蝶、破釜沉舟、塞翁失马
  方言词          瓷实、嘎哈呢、巴适
  品牌与作品指涉  老干妈、五菱宏光、某部剧的台词
  委婉与禁忌      骂人不带脏字的说法

不要找的是：普通词汇、专有名词（人名地名归实体抽取）、
以及虽然生动但字面义就是实际义的表达。

每条必须给：
1. literal_gloss —— 字面上说的是什么
2. actual_use —— 实际在表达什么、什么语气、褒还是贬
   这两条差得越远，直译越会出事。差不多的就别收了。
3. volatility 时效：
   evergreen 成语典故，几百年不变
   decade    一代人的记忆
   years     几年热度的流行语
   months    短命网络梗，明年就没人提
   判断依据是「五年后的读者还认识吗」，不是「现在火不火」。
4. plot_load 这个梗承载多少情节：
   none 纯修辞／flavor 塑造人物或氛围／setup 是伏笔后文有回扣／pivot 情节转折靠它
   看清楚再填 —— 伏笔被当成纯修辞舍掉，后文的回扣就落空了。
5. cultural_load 目标文化能不能理解：
   low 人类共通／medium 换个说法就行／high 深度绑定中文语境
6. origin 出处，说不清就留空，不要编。
7. evidence 摘原文一句。"""

RENDER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["renderings"],
    "properties": {
        "renderings": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["meme_id", "strategy", "rationale"],
                "properties": {
                    "meme_id": {"type": "string"},
                    "strategy": {"type": "string",
                                 "enum": [s.value for s in DeviceStrategy]},
                    "target_text": {"type": "string"},
                    "gloss_text": {"type": "string"},
                    "rationale": {"type": "string"},
                    "target_volatility": {"type": "string",
                                          "enum": [v.value for v in Volatility]},
                    "candidates": {"type": "array", "items": {"type": "string"}},
                },
            },
        }
    },
}

RENDER_SYSTEM = """你要决定每个梗在目标世界观里怎么呈现。

九档策略，代价递增。前四档读者读到的仍是故事：
  preserve    直接照搬。只有当这个说法在目标文化里同样成立时才用。
  substitute  换成目标文化里承担同样功能的说法。
  transplant  整体移植：换一个目标文化自己的梗，字面全变、效果对齐。
  naturalize  归化重写：按目标文化的表达习惯重写这句，不留源文痕迹。

中间两档要付出「读者意识到这是译文」的代价，慎用：
  gloss_inline 行内轻注：把必要背景自然编进句子，不加括号、不打断阅读。
  footnote     脚注：正文保留原样，注释单列。出戏最狠，
               只有当这个典故本身就是内容时才值得。

最后三档是止损：
  compensate  此处认赔，在附近补一个同效果的说法，总量守恒。
  relocate    移到别处实现。
  omit        舍弃。强行保留反而伤害阅读时才用。

判断顺序：
1. 先看 plot_load。setup 和 pivot 承载情节 —— **永远不能 omit**，
   宁可 gloss_inline 出戏，也不能让后文的回扣落空。
   读者不会想「这里少了个梗」，只会觉得「后面那段莫名其妙」。
2. 再看 volatility。months / years 的短命梗别费力考古 ——
   它在源文化里都快消失了，不值得目标读者付理解成本，直接 naturalize。
3. 最后看目标世界观的年代。给维多利亚英国配一个当代美国俚语，
   比不译更糟 —— 那是硬伤，读者一眼看出。

另外：
- 目标文化里也用网络梗时填 target_volatility。
  别拿一个明年就过期的目标梗去替一个中文的经典说法。
- rationale 要说清「为什么这个说法在目标文化里能达到同样效果」，
  不要写「这样更通顺」这种没有信息量的话。
- candidates 给 2–3 个备选，让人工能挑。"""


@dataclass
class MemeResult:
    memes: int = 0
    updated: int = 0
    by_register: dict[str, int] = field(default_factory=dict)
    by_volatility: dict[str, int] = field(default_factory=dict)
    high_risk: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "memes": self.memes, "updated": self.updated,
            "by_register": self.by_register, "by_volatility": self.by_volatility,
            "high_risk": self.high_risk,
        }


@dataclass
class RenderResult:
    rendered: int = 0
    skipped_locked: int = 0
    by_strategy: dict[str, int] = field(default_factory=dict)
    needs_review: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "rendered": self.rendered, "skipped_locked": self.skipped_locked,
            "by_strategy": self.by_strategy, "needs_review": self.needs_review,
        }


def _blocks(db: Session, chapter: Chapter) -> list[ScriptBlock]:
    doc = db.execute(
        select(ScriptDoc).where(
            ScriptDoc.chapter_id == chapter.id, ScriptDoc.status == DocStatus.active
        )
    ).scalars().first()
    if doc is None:
        raise PipelineError("该章节还没有 active 剧本，请先分块")
    return list(
        db.execute(
            select(ScriptBlock).where(ScriptBlock.script_doc_id == doc.id)
            .order_by(ScriptBlock.seq_no)
        ).scalars()
    )


def extract_memes(
    db: Session, chapter: Chapter, *, batch_size: int = 16
) -> MemeResult:
    """抽一章的文化梗。跨章累积 —— 同一个梗出现十次是一条，不是十条。"""
    blocks = [b for b in _blocks(db, chapter) if (b.source_text or "").strip()]
    if not blocks:
        raise PipelineError("章节没有正文")

    result = MemeResult()
    existing = {
        m.surface: m
        for m in db.execute(
            select(MemeEntry).where(MemeEntry.novel_id == chapter.novel_id)
        ).scalars()
    }

    for i in range(0, len(blocks), batch_size):
        batch = blocks[i : i + batch_size]
        payload = [{"block_id": b.id, "text": b.source_text} for b in batch]
        data, _ = chat_json(
            db,
            [
                {"role": "system", "content": EXTRACT_SYSTEM},
                {"role": "user", "content": json.dumps(
                    {"blocks": payload}, ensure_ascii=False)},
            ],
            EXTRACT_SCHEMA,
            purpose="memes",
            novel_id=chapter.novel_id, chapter_id=chapter.id,
            ref_kind="meme_extract", ref_id=chapter.id,
        )
        _absorb(db, chapter, data.get("memes") or [], existing, result)

    db.flush()
    return result


def _absorb(
    db: Session, chapter: Chapter, items: list[dict],
    existing: dict[str, MemeEntry], result: MemeResult,
) -> None:
    for item in items:
        surface = str(item.get("surface") or "").strip()
        use = str(item.get("actual_use") or "").strip()
        if not surface or not use:
            continue
        try:
            reg = MemeRegister(item.get("register") or "internet_slang")
        except ValueError:
            reg = MemeRegister.internet_slang
        try:
            vol = Volatility(item.get("volatility") or "evergreen")
        except ValueError:
            vol = Volatility.evergreen
        try:
            plot = PlotLoad(item.get("plot_load") or "none")
        except ValueError:
            plot = PlotLoad.none

        quote = str(item.get("evidence") or "").strip()
        row = existing.get(surface)
        if row is not None:
            if row.locked:
                continue
            row.occurrences = (row.occurrences or 0) + 1
            # 情节承载度取最高的那次 —— 一个梗在某章是伏笔，
            # 就不能因为它在别章只是修辞而被降级放弃
            if _plot_rank(plot) > _plot_rank(row.plot_load):
                row.plot_load = plot
            ev = list(row.evidence_json or [])
            if quote and not any(e.get("chapter_id") == chapter.id for e in ev):
                ev.append({"chapter_id": chapter.id, "quote": quote})
                row.evidence_json = ev[:6]
            result.updated += 1
            continue

        row = MemeEntry(
            id=new_id("mm"), novel_id=chapter.novel_id, surface=surface,
            register=reg, volatility=vol, plot_load=plot,
            literal_gloss=(item.get("literal_gloss") or "").strip() or None,
            actual_use=use[:2000],
            origin=(item.get("origin") or "").strip() or None,
            origin_year=item.get("origin_year") or None,
            circle=(item.get("circle") or "").strip() or None,
            platform=(item.get("platform") or "").strip() or None,
            occurrences=1,
            evidence_json=[{"chapter_id": chapter.id, "quote": quote}] if quote else None,
        )
        db.add(row)
        existing[surface] = row
        result.memes += 1
        result.by_register[reg.value] = result.by_register.get(reg.value, 0) + 1
        result.by_volatility[vol.value] = result.by_volatility.get(vol.value, 0) + 1
        # 承载情节 + 深度绑定中文，是最容易翻丢又最伤的组合
        if plot in (PlotLoad.setup, PlotLoad.pivot) and len(result.high_risk) < 12:
            result.high_risk.append({
                "surface": surface, "plot_load": plot.value,
                "volatility": vol.value, "actual_use": use[:80],
            })


def _plot_rank(p: PlotLoad) -> int:
    return {PlotLoad.none: 0, PlotLoad.flavor: 1,
            PlotLoad.setup: 2, PlotLoad.pivot: 3}[p]


#: 单次渲染的梗条数。每条要出目标文本、注释、理由、2–3 个候选，
#: 输出量是输入的好几倍 —— 一次塞太多必被截断。
_RENDER_BATCH = 8


def render_memes(
    db: Session, transform: WorldTransform, *, limit: int = 40,
) -> RenderResult:
    """为目标圈层定每个梗的呈现方式。"""
    profile = db.get(WorldProfile, transform.target_profile_id)
    if profile is None:
        raise PipelineError("目标世界观档案缺失")

    memes = list(
        db.execute(
            select(MemeEntry).where(
                MemeEntry.novel_id == transform.novel_id
            ).order_by(MemeEntry.occurrences.desc()).limit(limit)
        ).scalars()
    )
    if not memes:
        raise PipelineError("还没有抽到文化梗，请先执行 memes:extract")

    done = {
        r.meme_id: r
        for r in db.execute(
            select(MemeRendering).where(
                MemeRendering.world_profile_id == profile.id,
                MemeRendering.meme_id.in_([m.id for m in memes]),
            )
        ).scalars()
    }

    result = RenderResult()
    pending = []
    for m in memes:
        cur = done.get(m.id)
        if cur is not None and cur.locked:
            result.skipped_locked += 1
            continue
        pending.append(m)
    if not pending:
        return result

    axes = profile.axes_json or {}
    lang = profile.language_json or {}
    for i in range(0, len(pending), _RENDER_BATCH):
        _render_batch(db, transform, profile, axes, lang,
                      pending[i : i + _RENDER_BATCH], done, result)
    db.flush()
    return result


def _render_batch(
    db: Session, transform: WorldTransform, profile: WorldProfile,
    axes: dict, lang: dict, pending: list[MemeEntry],
    done: dict[str, MemeRendering], result: RenderResult,
) -> None:
    payload = [
        {
            "meme_id": m.id, "surface": m.surface,
            "register": m.register.value,
            "literal_gloss": m.literal_gloss or "",
            "actual_use": m.actual_use,
            "origin": m.origin or "", "circle": m.circle or "",
            "volatility": m.volatility.value,
            "plot_load": m.plot_load.value,
            "occurrences": m.occurrences,
            "evidence": [e.get("quote") for e in (m.evidence_json or [])][:2],
        }
        for m in pending
    ]
    data, _ = chat_json(
        db,
        [
            {"role": "system", "content": RENDER_SYSTEM},
            {"role": "user", "content": (
                f"【目标世界观】{profile.display_name}\n"
                f"【目标语言】{lang.get('code')}　语体 {lang.get('register')}\n"
                f"【年代】{axes.get('era_span')}　社会背景 {axes.get('social_context')}\n"
                f"【禁止出现】{(profile.visual_json or {}).get('visual_dont')}\n\n"
                f"【待定的梗】\n{json.dumps(payload, ensure_ascii=False, indent=1)}"
            )},
        ],
        RENDER_SCHEMA,
        purpose="memes",
        novel_id=transform.novel_id,
        ref_kind="meme_render", ref_id=transform.id,
    )

    by_id = {m.id: m for m in pending}
    for item in data.get("renderings") or []:
        m = by_id.get(str(item.get("meme_id") or ""))
        if m is None:
            continue
        try:
            strategy = DeviceStrategy(item.get("strategy") or "substitute")
        except ValueError:
            strategy = DeviceStrategy.substitute

        # 承载情节的梗不许舍。模型偶尔会为了句子干净把伏笔丢掉，
        # 那是读者三十页后才会撞上的坑，这里直接拦下。
        if strategy is DeviceStrategy.omit and m.plot_load in (
            PlotLoad.setup, PlotLoad.pivot
        ):
            log.warning("梗「%s」承载情节(%s)，拒绝 omit，改 gloss_inline",
                        m.surface, m.plot_load.value)
            strategy = DeviceStrategy.gloss_inline
            result.needs_review.append({
                "surface": m.surface, "reason": "模型建议舍弃，但它是伏笔，已改为行内轻注",
            })

        row = done.get(m.id)
        if row is None:
            row = MemeRendering(
                id=new_id("mr"), meme_id=m.id, world_profile_id=profile.id
            )
            db.add(row)
            done[m.id] = row
        row.strategy = strategy
        row.target_text = (item.get("target_text") or "").strip() or None
        row.gloss_text = (item.get("gloss_text") or "").strip() or None
        row.rationale = (item.get("rationale") or "").strip() or None
        row.candidates_json = [
            str(c) for c in (item.get("candidates") or []) if str(c).strip()
        ] or None
        try:
            row.target_volatility = (
                Volatility(item["target_volatility"])
                if item.get("target_volatility") else None
            )
        except ValueError:
            row.target_volatility = None
        row.status = ReviewStatus.candidate
        result.rendered += 1
        result.by_strategy[strategy.value] = result.by_strategy.get(strategy.value, 0) + 1

        # 用目标文化的短命梗去替换，等于把过期问题原样搬过去
        if row.target_volatility in (Volatility.months, Volatility.years):
            result.needs_review.append({
                "surface": m.surface, "target": row.target_text,
                "reason": f"目标说法时效为 {row.target_volatility.value}，几年后读者可能不认识",
            })


def brief_for_blocks(
    db: Session, transform: WorldTransform, texts: list[str],
) -> list[dict[str, Any]]:
    """给翻译提示词用的梗对照。只带这批文本里真正出现的，不做无谓的上下文膨胀。"""
    profile_id = transform.target_profile_id
    rows = list(db.execute(
        select(MemeEntry, MemeRendering)
        .join(MemeRendering, MemeRendering.meme_id == MemeEntry.id)
        .where(
            MemeEntry.novel_id == transform.novel_id,
            MemeRendering.world_profile_id == profile_id,
            or_(
                MemeRendering.target_text.is_not(None),
                MemeRendering.gloss_text.is_not(None),
            ),
        )
    ))
    blob = "\n".join(texts)
    out = []
    for m, r in rows:
        surfaces = [m.surface, *(m.aliases_json or [])]
        hit = next((s for s in surfaces if s and s in blob), None)
        if not hit:
            continue
        out.append({
            "surface": hit, "strategy": r.strategy.value,
            "actual_use": m.actual_use,
            "target_text": r.target_text, "gloss_text": r.gloss_text,
        })
    return out
