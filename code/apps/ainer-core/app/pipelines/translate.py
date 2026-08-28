"""翻译 pipeline —— 世界观四层在这里汇合。

一个块的完整旅程：
  1  闸一   实体名替换成占位符，人名根本不进 LLM，也就无从漂移
  2  注入   世界观声明 + 称谓 + 名物 + 禁用词 四段进 system prompt（v1 断链的修复点）
  3  翻译   走 capability text.translate，逐段对齐返回
  4  还原   占位符换回锁定的目标译名
  5  闸二   反向校验：禁用词 / 名物漏译 / 人名漂移
  6  重译   strict 模式下带违规反馈重试一次，仍失败才落告警

已 locked 的译文块永不被覆盖 —— 人工校对过的内容不该被批量任务吃掉。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.capability.schemas import Capability
from app.capability.service import submit_task
from app.ids import new_id
from app.models import (
    Chapter, DocStatus, GlossaryTerm, NovelTranslationSettings, ScriptBlock, ScriptDoc,
    TaskStatus, TermStatus, TranslationBlock, TranslationBlockStatus, WorldProfile,
    WorldTransform,
)
from app.models.script import TRANSLATABLE_TYPES
from app.pipelines.base import PipelineError
from app.pipelines.entities import (
    apply_placeholders, placeholder_map, restore_placeholders,
)
from app.pipelines.devices import build_device_brief
from app.worldview import injector, preflight as pf, validator

log = logging.getLogger(__name__)


@dataclass
class TranslateResult:
    translated: int = 0
    skipped_locked: int = 0
    retried: int = 0
    violations: int = 0
    missing_names: list[str] = field(default_factory=list)
    blocks: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "translated": self.translated,
            "skipped_locked": self.skipped_locked,
            "retried": self.retried,
            "violations": self.violations,
            "missing_names": self.missing_names,
            "blocks": self.blocks,
        }


def _active_doc(db: Session, chapter_id: str) -> ScriptDoc:
    doc = db.execute(
        select(ScriptDoc).where(
            ScriptDoc.chapter_id == chapter_id, ScriptDoc.status == DocStatus.active
        )
    ).scalars().first()
    if doc is None:
        raise PipelineError("该章节还没有 active 剧本，请先生成剧本")
    return doc


def _glossary_lines(db: Session, novel_id: str, lang: str, limit: int = 60) -> str:
    rows = db.execute(
        select(GlossaryTerm).where(
            GlossaryTerm.novel_id == novel_id,
            GlossaryTerm.target_language_code == lang,
            GlossaryTerm.status == TermStatus.approved,
        ).limit(limit)
    ).scalars().all()
    return "\n".join(f"  {r.source_term} → {r.target_term}" for r in rows)


def _settings(db: Session, novel_id: str, lang: str) -> NovelTranslationSettings | None:
    return db.execute(
        select(NovelTranslationSettings).where(
            NovelTranslationSettings.novel_id == novel_id,
            NovelTranslationSettings.target_language_code == lang,
        )
    ).scalars().first()


#: 改编模式的写作指令。这是 literal 与 adaptive 的分野 ——
#: 前者逐句转换，后者按骨架重写，允许调整句式与顺序以保住效果。
ADAPTIVE_BRIEF = """【改编模式】你不是在逐句翻译，是在为目标世界观的读者重写这一段。

必须守住的（不可增删）：
  · 情节事实：谁做了什么、导致了什么，一个都不能少也不能加
  · 出场人物与他们的态度
  · 这一段要让读者产生的情绪

可以调整的：
  · 句式、语序、断句 —— 按目标语言的自然写法来
  · 修辞手法 —— 中文的排比换成英文更顺的结构是对的
  · 笑点与情绪的实现方式 —— 见下方「叙事装置」

判断标准不是「像不像原文」，是**目标文化的读者读到这里，
反应是否与中文读者读原文时相同**。
读着像翻译腔，即使字字对应，也是失败的。"""


def translate_chapter(
    db: Session,
    chapter: Chapter,
    transform: WorldTransform,
    *,
    batch_size: int = 10,
    only_missing: bool = True,
    strict: bool | None = None,
    mode: str = "literal",
) -> TranslateResult:
    """翻译一章。四层世界观全部生效。

    mode:
      literal   逐块对应翻译，保守稳妥，适合已定稿的内容
      adaptive  按叙事骨架与装置重写，允许调整句式以保住笑点与情绪 ——
                跨文化改编要的是效果对等，不是字面对等
    """
    lang = transform.target_language_code
    doc = _active_doc(db, chapter.id)
    src_profile = db.get(WorldProfile, transform.source_profile_id)
    tgt_profile = db.get(WorldProfile, transform.target_profile_id)
    lang_cfg = tgt_profile.language_json or {}

    policy = transform.policy_json or {}
    if strict is None:
        strict = str(policy.get("lexicon_policy") or "strict") == "strict"

    blocks = [
        b for b in db.execute(
            select(ScriptBlock).where(ScriptBlock.script_doc_id == doc.id)
            .order_by(ScriptBlock.seq_no)
        ).scalars()
        if b.block_type in TRANSLATABLE_TYPES and (b.source_text or "").strip()
    ]
    if not blocks:
        raise PipelineError("该章节没有可翻译的块（action / scene_break 不进翻译线）")

    existing = {
        t.script_block_id: t
        for t in db.execute(
            select(TranslationBlock).where(
                TranslationBlock.script_block_id.in_([b.id for b in blocks]),
                TranslationBlock.transform_id == transform.id,
            )
        ).scalars()
    }

    result = TranslateResult()
    pending: list[ScriptBlock] = []
    for b in blocks:
        cur = existing.get(b.id)
        if cur is not None and cur.locked:
            result.skipped_locked += 1
            continue
        if only_missing and cur is not None and cur.translated_text:
            continue
        pending.append(b)
    if not pending:
        return result

    # ── 闸一：占位符 ──
    s2p, p2t, missing = placeholder_map(db, chapter.novel_id, transform.id, lang)
    result.missing_names = missing
    locked_names = {
        surface: p2t[ph] for surface, ph in s2p if ph in p2t
    }

    settings = _settings(db, chapter.novel_id, lang)
    style_prompt = settings.style_prompt if settings else None
    glossary = _glossary_lines(db, chapter.novel_id, lang)
    profile_forbidden = lang_cfg.get("forbidden_tokens") or []

    for chunk in _chunks(pending, batch_size):
        masked = {b.id: apply_placeholders(b.source_text, s2p) for b in chunk}
        joined = "\n".join(masked.values())

        # ── 注入：本批命中的名物 ──
        hits = pf.hits_for_text(db, transform.id, joined)
        system_prompt = injector.compose_system_prompt(
            source_display=src_profile.display_name,
            target_display=tgt_profile.display_name,
            target_language=lang,
            hits=hits,
            target_axes=tgt_profile.axes_json,
            language_cfg=lang_cfg,
            glossary_lines=glossary,
            style_prompt=style_prompt,
        )
        if mode == "adaptive":
            # 骨架与装置只在改编模式注入 —— 逐句模式给了也用不上，
            # 反而会诱导模型自由发挥
            parts = [system_prompt, ADAPTIVE_BRIEF]
            spine = _beat_brief(db, chapter, [b.id for b in chunk])
            if spine:
                parts.append(spine)
            brief = build_device_brief(
                db, [b.id for b in chunk], tgt_profile.display_name
            )
            if brief:
                parts.append(brief)
            # 梗对照两个模式都注入 —— 它不是「发挥空间」而是硬约定：
            # 「破防了」直译成 defences breached 在逐句模式下也是错的
            memes = _meme_brief(db, transform, [b.source_text or "" for b in chunk])
            if memes:
                parts.append(memes)
            system_prompt = "\n\n".join(parts)
        else:
            memes = _meme_brief(db, transform, [b.source_text or "" for b in chunk])
            if memes:
                system_prompt = f"{system_prompt}\n\n{memes}"

        segments = [
            {
                "id": b.id,
                "text": masked[b.id],
                "kind": b.block_type.value,
                "speaker": b.speaker_tag or None,
            }
            for b in chunk
        ]
        translated = _call_translate(
            db, transform, segments, system_prompt, chapter,
        )

        for b in chunk:
            raw = translated.get(b.id, "")
            if not raw:
                continue
            text = restore_placeholders(raw, p2t)

            # ── 闸二：反向校验 ──
            block_hits = pf.hits_for_text(db, transform.id, b.source_text)
            vs = validator.check_translation(
                translated_text=text, hits=block_hits,
                profile_forbidden=profile_forbidden,
                locked_names=locked_names, source_text=b.source_text,
                block_id=b.id,
            )

            # ── 重译：strict 下带反馈重试一次 ──
            if vs and strict and any(v.severity == "high" for v in vs):
                feedback = validator.build_retry_feedback(vs)
                retry = _call_translate(
                    db, transform,
                    [{"id": b.id, "text": masked[b.id],
                      "kind": b.block_type.value, "speaker": b.speaker_tag or None}],
                    system_prompt + "\n\n" + feedback, chapter,
                )
                retry_raw = retry.get(b.id, "")
                if retry_raw:
                    retry_text = restore_placeholders(retry_raw, p2t)
                    retry_vs = validator.check_translation(
                        translated_text=retry_text, hits=block_hits,
                        profile_forbidden=profile_forbidden,
                        locked_names=locked_names, source_text=b.source_text,
                        block_id=b.id,
                    )
                    result.retried += 1
                    if len(retry_vs) < len(vs):
                        text, vs = retry_text, retry_vs

            if vs:
                result.violations += pf.record_violations(
                    db, transform.id, vs, ref_id=b.id
                )

            row = existing.get(b.id)
            if row is None:
                row = TranslationBlock(
                    id=new_id("tb"), script_block_id=b.id,
                    transform_id=transform.id,
                    target_language_code=lang, translated_text=text,
                    status=TranslationBlockStatus.draft,
                )
                db.add(row)
                existing[b.id] = row
            else:
                row.translated_text = text
                row.status = TranslationBlockStatus.draft
            row.lexicon_hits_json = [
                {"source": h.source_term, "target": h.target_term} for h in block_hits
            ]
            row.model_meta_json = {"transform_id": transform.id,
                                   "violations": len(vs)}
            result.translated += 1
            result.blocks.append({
                "block_id": b.id, "seq_no": b.seq_no,
                "source": b.source_text, "target": text,
                "violations": len(vs),
            })

    db.flush()
    return result


_STRATEGY_CN = {
    "preserve": "照搬", "substitute": "换等价说法", "transplant": "换目标文化的梗",
    "naturalize": "按目标习惯重写", "gloss_inline": "行内轻注（不加括号）",
    "footnote": "正文保留＋脚注", "compensate": "此处认赔、就近补偿",
    "relocate": "移到别处实现", "omit": "舍弃",
}


def _meme_brief(db: Session, transform: WorldTransform, texts: list[str]) -> str:
    """文化梗对照。只带这批文本里真出现的条目 —— 全量注入会淹掉真正相关的几条。"""
    from app.pipelines import memes as meme_pipe

    hits = meme_pipe.brief_for_blocks(db, transform, texts)
    if not hits:
        return ""
    lines = ["【文化梗处理表】这些说法的字面义不等于实际用法，直译必错。按下表处理："]
    for h in hits:
        line = f"  {h['surface']} → 【{_STRATEGY_CN.get(h['strategy'], h['strategy'])}】"
        if h.get("target_text"):
            line += f" {h['target_text']}"
        if h.get("gloss_text"):
            line += f"　注：{h['gloss_text']}"
        line += f"　（实际在说：{h['actual_use'][:60]}）"
        lines.append(line)
    lines.append("  标「舍弃」的直接不译，不要留一句字面翻译在那里。")
    return "\n".join(lines)


def _beat_brief(db: Session, chapter: Chapter, block_ids: list[str]) -> str:
    """本批涉及的情节点与情绪 —— 重写时必须命中的东西。"""
    from app.models import StoryBeat

    beats = list(
        db.execute(
            select(StoryBeat).where(StoryBeat.chapter_id == chapter.id)
            .order_by(StoryBeat.order_no)
        ).scalars()
    )
    if not beats:
        return ""
    lines = ["【叙事骨架】以下情节点与情绪必须在译文中原样保留："]
    for b in beats[:8]:
        bits = [f"  {b.order_no}. {b.title}"]
        if b.plot_point:
            bits.append(f"     情节：{b.plot_point}")
        if b.emotion:
            bits.append(f"     情绪：{b.emotion}（强度 {b.emotion_intensity}）")
        lines.append("\n".join(bits))
    return "\n".join(lines)


def _call_translate(
    db: Session, transform: WorldTransform, segments: list[dict],
    system_prompt: str, chapter: Chapter,
) -> dict[str, str]:
    """走 text.translate。契约要求逐段对齐返回，id 一一对应。"""
    src_profile = db.get(WorldProfile, transform.source_profile_id)
    source_lang = (src_profile.language_json or {}).get("code") or "zh-CN"

    task = submit_task(
        db, Capability.text_translate,
        {
            "source_language": source_lang,
            "target_language": transform.target_language_code,
            "segments": segments,
            "style_prompt": system_prompt,
            "glossary": [],
        },
        purpose="translate", sync=True,
        novel_id=chapter.novel_id, chapter_id=chapter.id,
        ref_kind="translation", ref_id=chapter.id,
    )
    if task.status != TaskStatus.succeeded:
        err = task.error_json or {}
        raise PipelineError(f"翻译失败 [{err.get('code')}]: {err.get('message')}")

    out = (task.result_json or {}).get("segments") or []
    mapped = {str(s.get("id")): str(s.get("text") or "") for s in out if s.get("id")}
    missing = [s["id"] for s in segments if s["id"] not in mapped]
    if missing:
        raise PipelineError(
            f"中间层未逐段对齐返回，缺 {len(missing)} 段（契约 §4.2 要求 id 一一对应）"
        )
    return mapped


def _chunks(items: Sequence[Any], size: int):
    for i in range(0, len(items), size):
        yield list(items[i : i + size])


def retranslate_affected(
    db: Session, transform: WorldTransform, *, lexicon_ids: list[str] | None = None,
) -> dict[str, Any]:
    """术语或名物改动后，只重译受影响的块。

    已 locked 的块不动 —— 人工校对过的内容不该被批量任务吃掉。
    """
    from app.models import WorldLexicon

    q = select(WorldLexicon).where(WorldLexicon.transform_id == transform.id)
    if lexicon_ids:
        q = q.where(WorldLexicon.id.in_(lexicon_ids))
    terms = [r.source_term for r in db.execute(q).scalars()]
    if not terms:
        return {"affected_chapters": [], "affected_blocks": 0}

    matcher, _ = pf.build_matcher(db, transform.id)
    docs = db.execute(
        select(ScriptDoc, Chapter)
        .join(Chapter, Chapter.id == ScriptDoc.chapter_id)
        .where(Chapter.novel_id == transform.novel_id,
               ScriptDoc.status == DocStatus.active)
    ).all()

    affected_blocks: list[str] = []
    affected_chapters: set[str] = set()
    target_terms = set(terms)

    for doc, chapter in docs:
        blocks = db.execute(
            select(ScriptBlock).where(ScriptBlock.script_doc_id == doc.id)
        ).scalars()
        for b in blocks:
            if not (b.source_text or "").strip():
                continue
            hit_keys = {h.key for h in matcher.find(b.source_text)}
            if hit_keys & target_terms:
                affected_blocks.append(b.id)
                affected_chapters.add(chapter.id)

    if affected_blocks:
        rows = db.execute(
            select(TranslationBlock).where(
                TranslationBlock.script_block_id.in_(affected_blocks),
                TranslationBlock.transform_id == transform.id,
            )
        ).scalars().all()
        cleared = 0
        for r in rows:
            if r.locked:
                continue
            r.translated_text = None
            r.status = TranslationBlockStatus.draft
            cleared += 1
        db.flush()
    else:
        cleared = 0

    return {
        "affected_chapters": sorted(affected_chapters),
        "affected_blocks": len(affected_blocks),
        "cleared": cleared,
        "locked_kept": len(affected_blocks) - cleared,
    }
