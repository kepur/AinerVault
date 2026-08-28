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
from app.worldview import resolve
from app.pipelines.base import PipelineError, fingerprint

log = logging.getLogger(__name__)

#: 成对引号。中文小说的对白形式很杂，全都认。
_QUOTE_PAIRS = (("「", "」"), ("『", "』"), ("“", "”"), ('"', '"'), ("‘", "’"))

#: 「李格非从里屋走出：」这类前置说话人 —— 冒号前整段先抓下来，再裁掉叙述部分。
#: 上限给到 40 字：中文小说常写「三娘四十上下，手上捏着抹布，见人进门先笑：『…』」，
#: 卡在 20 字会把这类整段判成叙述，对白直接丢失。裁剪由 trim_speaker 负责，
#: 这里放宽不会引入错误 —— 裁不出合法称呼时它会返回 None。
_SPEAKER_PREFIX = re.compile(r"^(?P<who>[^:：\n]{1,40})\s*[:：]\s*(?P<rest>.+)$")
#: 「……」小二迎上来 —— 引号后紧跟的称呼，且其后必须是叙述动词。
#: 不验证动词的话，「『打尖。』她解下腰间长剑」会把「她解下腰间长」当成说话人。
_SPEAKER_SUFFIX = re.compile(
    r"[」』”\"]\s*[，,]?\s*(?P<who>[一-龥A-Za-z·]{2,6}?)"
    r"(?:说道|说|道|问道|问|答道|答|喊道|喊|叫道|叫|笑道|笑|叹道|叹"
    r"|迎上|走上|接口|开口|低声|高声|应道|回道"
    r"|打断|插话|摆手|点头|摇头|沉默|顿了|补了|又道|续道)"
)
#: 代词不指向具体角色，不能当说话人
_PRONOUNS = frozenset({
    "他", "她", "它", "我", "你", "您", "他们", "她们", "它们",
    "我们", "你们", "众人", "有人", "旁人",
    # 时间与语气词。切完标点后剩下的常常正是它们（「半晌，他说」「这时，门开了」），
    # 形状上完全像个称呼 —— 只能靠词表挡。
    "半晌", "片刻", "须臾", "良久", "这时", "那时", "随后", "接着",
    "忽然", "突然", "于是", "然后", "后来", "当下", "少顷", "一时",
})
#: 出现这些字说明这段是叙述而非称呼，用于把「李格非从里屋走出」裁成「李格非」
_VERB_MARKERS = (
    # 言说
    "说", "道", "问", "答", "喊", "叫", "笑", "叹", "应", "回", "唤", "骂",
    # 位移与体态
    "走", "推", "站", "坐", "起", "来", "去", "进", "出", "上", "下", "回",
    "凑", "退", "转", "抬", "低", "高", "俯", "仰", "跪", "躺", "倒", "停",
    # 手部动作 —— 叙述句里最常紧跟在人名后面的一类
    "捏", "摸", "搓", "握", "端", "扔", "放", "拿", "拎", "杵", "勒", "掀",
    "剥", "拍", "指", "挥", "摆", "招", "拉", "拽", "按", "扶", "接", "递",
    "打", "解", "扣", "插", "拔", "收", "翻", "掏", "开", "关", "合",
    # 视听与神情
    "看", "望", "瞧", "盯", "瞟", "听", "皱", "眯", "咂", "嚼",
    "沉", "默", "顿", "愣", "怔", "缓",
    # 虚化的连接
    "从", "在", "了", "把", "被", "续", "又", "才", "就", "便", "却",
    "迎", "见", "带", "领", "让", "使", "对", "向", "跟", "同", "与",
)

#: 称呼里不可能出现的字：助词、介词、副词、否定词。
#: 单靠动词表切一刀是不够的 ——「总镖头把镖单推过来」里最早的动词是「推」，
#: 切完得到「总镖头把镖单」，看着像切干净了，其实还是半句话。
#: 而这种半句话比识别不出更糟：它会被当成一个角色写进实体表，
#: 还会分到一个 TTS 音色，下游全是它的污染。
_NON_NAME_CHARS = frozenset(
    "的地得把被将让使给对向往和跟同与及"
    "了着过就才又也还挺很更最太真"
    "正已曾即便却竟忽刚终于渐"
    "不没未别莫甭"
    "这那每某各另其此"
)

#: 二次切分的边界字。命中就从这里再切一刀，切不出合法称呼就放弃。
_SECOND_CUT = tuple(_NON_NAME_CHARS)

#: 数词。称呼里出现在第三字及之后必是叙述（「三娘四十上下」）——
#: 首字的数词是合法的（「三娘」「老六」），所以只从 index 2 起切。
_NUMERALS = frozenset("零一二三四五六七八九十百千万两半几多0123456789")


def trim_speaker(who: str) -> str | None:
    """把「李格非从里屋走出」裁成「李格非」，裁不干净就返回 None。

    两刀：先按动词切，再按助词/副词切。两刀之后仍不像称呼就放弃 ——
    **宁可没有说话人，也不要一个错的**。缺失可以由后面的
    speakers:resolve 用 LLM 补上（那一步本来就是干这个的），
    而错的说话人会一路污染实体抽取、音色分配和分镜的对话指向，
    且沿途没有任何一处会报错。
    """
    w = (who or "").strip().strip("「」『』“”\"')( ")
    if not w:
        return None

    # 第零刀：标点。「半晌，他」这类先切到第一个标点 ——
    # 逗号后面通常是新的主语，跟前半截不是一个东西
    for punct in "，,。.；;：:！!？?、":
        idx = w.find(punct)
        if idx >= 0:
            w = w[:idx]
    w = w.strip()
    if not w:
        return None

    # 第一刀：动词
    cuts = [w.find(v) for v in _VERB_MARKERS if w.find(v) >= 2]
    if cuts:
        w = w[: min(cuts)]
    w = w.strip()

    # 第二刀：助词、介词、副词
    cuts2 = [w.find(c) for c in _SECOND_CUT if w.find(c) >= 0]
    if cuts2:
        pos = min(cuts2)
        # 出现在开头说明整段根本不是称呼（「把镖单推过来」）
        if pos < 2:
            return None
        w = w[:pos].strip()

    # 第三刀：数词。「三娘四十上下」第一刀第二刀都切不动，因为「四十」不是动词也不是虚词
    ncut = [w.find(c) for c in _NUMERALS if w.find(c) >= 2]
    if ncut:
        w = w[: min(ncut)].strip()

    if w in _PRONOUNS or not (2 <= len(w) <= 6):
        return None
    # 仍含残留虚词的一律作废
    if any(c in _NON_NAME_CHARS for c in w):
        return None
    # 叠字是副词/形容词的特征（慢悠悠、笑眯眯），称呼里几乎不出现在词尾。
    # 「老周慢悠悠」三刀都切不动，只有这条挡得住。
    if len(w) >= 4 and w[-1] == w[-2]:
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
    db: Session, chapter: Chapter, language: str, *,
    with_source: bool = False, transform_id: str | None = None,
) -> dict[str, Any]:
    """渲染译本。这是译本线的最终产出，可直接阅读或送 TTS。

    未指定 transform_id 时按语言回落 —— 同语言多版并存时 active 优先。
    """
    doc = active_prose_doc(db, chapter.id)
    if doc is None:
        raise PipelineError("该章节还没有译本分块，请先执行 prose:build")

    blocks = list(
        db.execute(
            select(ScriptBlock).where(ScriptBlock.script_doc_id == doc.id)
            .order_by(ScriptBlock.seq_no)
        ).scalars()
    )
    tf_ids = (
        [transform_id] if transform_id
        else resolve.transform_ids_for(db, chapter.novel_id, language)
    )
    trans: dict[str, Any] = {}
    if tf_ids:
        # 按 tf_ids 的优先序取，先到先得：active 那版的译文压住旧版
        rank = {tid: i for i, tid in enumerate(tf_ids)}
        for t in db.execute(
            select(TranslationBlock).where(
                TranslationBlock.script_block_id.in_([b.id for b in blocks]),
                TranslationBlock.transform_id.in_(tf_ids),
            )
        ).scalars():
            cur = trans.get(t.script_block_id)
            if cur is None or rank[t.transform_id] < rank[cur.transform_id]:
                trans[t.script_block_id] = t

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
