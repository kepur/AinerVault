"""译本分块 —— 把章节原文切成可翻译单元，不调 LLM、不切场景。

先产出一个符合目标世界观的译本小说，把人名、名物、身份称谓校对锁定，
再谈剧本与分镜。译本这一层做扎实了，后面才有可信的地基。

与 script_build 的分工：
    prose      纯规则按段落切，秒级完成、零成本，产出的是可读译本
    screenplay LLM 拆场景与镜头单元，供分镜编译消费

两者产出同一套 ScriptBlock，所以翻译、占位符、三道闸全部复用；
译本校对锁定的译文，升级到剧本模式时能直接继承。
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
    BlockType, Chapter, DocMode, DocStatus, ScriptBlock, ScriptDoc,
    TranslationBlock,
)
from app.pipelines.base import PipelineError, fingerprint

log = logging.getLogger(__name__)

#: 成对引号。中文小说的对白形式很杂，全都认。
_QUOTE_PAIRS = (("「", "」"), ("『", "』"), ("“", "”"), ('"', '"'), ("‘", "’"))

#: 「李格非从里屋走出：」这类前置说话人 —— 冒号前整段先抓下来，再裁掉叙述部分
_SPEAKER_PREFIX = re.compile(r"^(?P<who>[^:：\n]{1,20})\s*[:：]\s*(?P<rest>.+)$")
#: 「……」小二迎上来 —— 引号后紧跟的称呼，且其后必须是叙述动词。
#: 不验证动词的话，「『打尖。』她解下腰间长剑」会把「她解下腰间长」当成说话人。
_SPEAKER_SUFFIX = re.compile(
    r"[」』”\"]\s*[，,]?\s*(?P<who>[一-龥A-Za-z·]{2,6}?)"
    r"(?:说道|说|道|问道|问|答道|答|喊道|喊|叫道|叫|笑道|笑|叹道|叹"
    r"|迎上|走上|接口|开口|低声|高声|应道|回道)"
)
#: 代词不指向具体角色，不能当说话人
_PRONOUNS = frozenset({
    "他", "她", "它", "我", "你", "您", "他们", "她们", "它们",
    "我们", "你们", "众人", "有人", "旁人",
})
#: 出现这些字说明这段是叙述而非称呼，用于把「李格非从里屋走出」裁成「李格非」
_VERB_MARKERS = (
    "说", "道", "问", "答", "喊", "叫", "笑", "叹", "走", "推", "站", "坐",
    "从", "在", "了", "抬", "转", "看", "望", "迎", "低", "高", "接", "续",
)


def trim_speaker(who: str) -> str | None:
    """把「李格非从里屋走出」裁成「李格非」。

    取最早出现的动词位置切断 —— 按动词表顺序找会先命中靠后的字，
    裁出「李格非从里屋」这种半截。裁完少于 2 字就当没识别到。
    """
    w = (who or "").strip().strip("「」『』“”\"')( ")
    if not w:
        return None
    cuts = [w.find(v) for v in _VERB_MARKERS if w.find(v) >= 2]
    if cuts:
        w = w[: min(cuts)]
    w = w.strip()
    if w in _PRONOUNS or not (2 <= len(w) <= 8):
        return None
    return w
#: 章节标题行
_HEADING = re.compile(
    r"^\s*(?:第\s*[0-9零一二三四五六七八九十百千万两]+\s*[章回节卷篇]"
    r"|Chapter\s+\d+|序章|楔子|尾声|后记|番外)"
)


@dataclass
class ProseResult:
    script_doc_id: str = ""
    version: int = 0
    blocks: int = 0
    dialogue: int = 0
    narration: int = 0
    heading: int = 0
    speakers: list[str] = field(default_factory=list)
    reused: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "script_doc_id": self.script_doc_id, "version": self.version,
            "mode": "prose", "blocks": self.blocks,
            "dialogue": self.dialogue, "narration": self.narration,
            "heading": self.heading, "speakers": self.speakers,
            "reused": self.reused,
        }


def _extract_quoted(text: str) -> list[str]:
    """取出成对引号内的内容。"""
    out: list[str] = []
    for open_q, close_q in _QUOTE_PAIRS:
        if open_q == close_q:
            parts = text.split(open_q)
            if len(parts) >= 3:
                out.extend(p for i, p in enumerate(parts) if i % 2 == 1 and p.strip())
            continue
        depth = 0
        buf: list[str] = []
        for ch in text:
            if ch == open_q:
                depth += 1
                if depth == 1:
                    buf = []
                    continue
            elif ch == close_q and depth > 0:
                depth -= 1
                if depth == 0 and "".join(buf).strip():
                    out.append("".join(buf))
                continue
            if depth > 0:
                buf.append(ch)
    return out


def classify_paragraph(para: str) -> tuple[BlockType, str, str | None]:
    """判定段落类型，返回 (类型, 文本, 说话人)。

    只做规则判定 —— 这一层的目标是快和稳，语义理解留给译本审核。
    """
    text = para.strip()
    if not text:
        return BlockType.narration, "", None

    if _HEADING.match(text) and len(text) <= 60:
        return BlockType.heading, text, None

    quoted = _extract_quoted(text)
    if not quoted:
        return BlockType.narration, text, None

    speaker: str | None = None
    quote_at_start = text[0] in {q for pair in _QUOTE_PAIRS for q in pair}

    m = _SPEAKER_PREFIX.match(text)
    prefix_dialogue = False
    if m and any(q in m.group("rest") for pair in _QUOTE_PAIRS for q in pair):
        # 冒号后紧跟引号 —— 「某某说：『…』」的形式
        rest = m.group("rest").lstrip()
        if rest and rest[0] in {q for pair in _QUOTE_PAIRS for q in pair}:
            prefix_dialogue = True
            speaker = trim_speaker(m.group("who"))

    if speaker is None:
        m2 = _SPEAKER_SUFFIX.search(text)
        if m2:
            speaker = trim_speaker(m2.group("who"))

    # 用引号位置而非占比判定：句首引号是对白，句中引号是叙述里的引用。
    # 占比判不准 ——「『打尖。』她解下长剑」引号只占三成，却是对白；
    # 「所谓『人在江湖』大抵如此」占比相近，却是叙述。
    if quote_at_start or prefix_dialogue:
        return BlockType.dialogue, text, speaker
    # 叙述段落没有说话人 —— 段中的引用不是谁在讲话
    return BlockType.narration, text, None


def build_prose(
    db: Session, chapter: Chapter, *, activate: bool = True, force: bool = False
) -> ProseResult:
    """把一章切成译本块。指纹未变时复用已有版本，不重复建。"""
    content = (chapter.content or "").strip()
    if not content:
        raise PipelineError("章节正文为空")

    fp = fingerprint(content, "prose")
    prev = db.execute(
        select(ScriptDoc).where(
            ScriptDoc.chapter_id == chapter.id,
            ScriptDoc.doc_mode == DocMode.prose,
            ScriptDoc.status == DocStatus.active,
        )
    ).scalars().first()
    if prev is not None and prev.input_fingerprint == fp and not force:
        counts = _count(db, prev.id)
        return ProseResult(
            script_doc_id=prev.id, version=prev.version, reused=True, **counts
        )

    version = int(
        db.execute(
            select(ScriptDoc.version).where(ScriptDoc.chapter_id == chapter.id)
            .order_by(ScriptDoc.version.desc()).limit(1)
        ).scalar() or 0
    ) + 1

    doc = ScriptDoc(
        id=new_id("sd"), chapter_id=chapter.id, version=version,
        status=DocStatus.draft, doc_mode=DocMode.prose,
        language_source=_source_language(db, chapter),
        input_fingerprint=fp,
        generator_meta={"mode": "prose", "engine": "rule", "llm_calls": 0},
    )
    db.add(doc)
    db.flush()

    result = ProseResult(script_doc_id=doc.id, version=version)
    seq = 0
    seen_speakers: list[str] = []

    for para in re.split(r"\n\s*\n|\n", content):
        block_type, text, speaker = classify_paragraph(para)
        if not text:
            continue
        seq += 1
        db.add(ScriptBlock(
            id=new_id("sb"), script_doc_id=doc.id, scene_id=None, seq_no=seq,
            block_type=block_type, source_text=text, speaker_tag=speaker,
        ))
        result.blocks += 1
        if block_type == BlockType.dialogue:
            result.dialogue += 1
        elif block_type == BlockType.heading:
            result.heading += 1
        else:
            result.narration += 1
        if speaker and speaker not in seen_speakers:
            seen_speakers.append(speaker)

    if result.blocks == 0:
        raise PipelineError("切分后没有任何内容块")

    result.speakers = seen_speakers
    doc.stats_json = result.as_dict()

    if activate:
        for old in db.execute(
            select(ScriptDoc).where(
                ScriptDoc.chapter_id == chapter.id,
                ScriptDoc.doc_mode == DocMode.prose,
                ScriptDoc.status == DocStatus.active,
                ScriptDoc.id != doc.id,
            )
        ).scalars():
            old.status = DocStatus.archived
        doc.status = DocStatus.active

    db.flush()
    return result


def _count(db: Session, doc_id: str) -> dict[str, Any]:
    blocks = list(
        db.execute(
            select(ScriptBlock).where(ScriptBlock.script_doc_id == doc_id)
        ).scalars()
    )
    speakers: list[str] = []
    for b in blocks:
        if b.speaker_tag and b.speaker_tag not in speakers:
            speakers.append(b.speaker_tag)
    return {
        "blocks": len(blocks),
        "dialogue": sum(1 for b in blocks if b.block_type == BlockType.dialogue),
        "narration": sum(1 for b in blocks if b.block_type == BlockType.narration),
        "heading": sum(1 for b in blocks if b.block_type == BlockType.heading),
        "speakers": speakers,
    }


def _source_language(db: Session, chapter: Chapter) -> str:
    from app.models import Novel

    novel = db.get(Novel, chapter.novel_id)
    return novel.source_language_code if novel else "zh-CN"


def active_prose_doc(db: Session, chapter_id: str) -> ScriptDoc | None:
    return db.execute(
        select(ScriptDoc).where(
            ScriptDoc.chapter_id == chapter_id,
            ScriptDoc.doc_mode == DocMode.prose,
            ScriptDoc.status == DocStatus.active,
        )
    ).scalars().first()


def render_translated(
    db: Session, chapter: Chapter, language: str, *, with_source: bool = False
) -> dict[str, Any]:
    """渲染译本。这是译本线的最终产出，可直接阅读或送 TTS。"""
    doc = active_prose_doc(db, chapter.id)
    if doc is None:
        raise PipelineError("该章节还没有译本分块，请先执行 prose:build")

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
                TranslationBlock.target_language_code == language,
            )
        ).scalars()
    }

    paragraphs: list[dict[str, Any]] = []
    translated = locked = 0
    for b in blocks:
        t = trans.get(b.id)
        if t and t.translated_text:
            translated += 1
        if t and t.locked:
            locked += 1
        item = {
            "block_id": b.id, "seq_no": b.seq_no, "type": b.block_type.value,
            "speaker": b.speaker_tag,
            "text": (t.translated_text if t else None) or "",
            "status": t.status.value if t else None,
            "locked": bool(t and t.locked),
        }
        if with_source:
            item["source"] = b.source_text
        paragraphs.append(item)

    return {
        "chapter_id": chapter.id,
        "chapter_title": chapter.title,
        "language": language,
        "paragraphs": paragraphs,
        "stats": {
            "blocks": len(blocks), "translated": translated, "locked": locked,
            "coverage": round(translated / len(blocks), 4) if blocks else 0.0,
        },
    }
