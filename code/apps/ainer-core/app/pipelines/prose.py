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
#: 只放**铁定不能入名**的字。之前塞了太多能入名的：
#: 「渐」（高渐离）、「正」「刚」「曾」「于」「莫」「真」「向」「同」
#: 都是常见的名字用字，把它们列进来会把真人名判成 None ——
#: 而误杀一个真人名比漏挡一个碎片更糟：漏挡的还有后面几道检查，
#: 误杀的直接就没了，且沿途不报错。
_NON_NAME_CHARS = frozenset(
    "的地得"          # 结构助词
    "把被"            # 处置与被动
    "了着过"          # 时态助词
    "就才又也还"      # 关联副词
    "挺很更最太"      # 程度副词
    "不没未甭"        # 否定（「别」「莫」是姓，不列）
    "这那每"          # 指示（「某」「各」「其」「此」可入名，不列）
)

#: 二次切分的边界字。命中就从这里再切一刀，切不出合法称呼就放弃。
_SECOND_CUT = tuple(_NON_NAME_CHARS)

#: **强动词**：不可能出现在姓名首字的动作字。整串以它开头即判定是动词短语。
#: 与 _VERB_MARKERS 分开是因为那张表里混着大量可作姓氏的字 ——
#: 高、来、向、从、在都在里面，按首字一刀切会把「高渐离」误杀。
_STRONG_VERBS = frozenset(
    "说道问答喊叫笑叹走推坐凑退站起进出捏摸搓握端扔放拿拎杵勒掀剥拍指挥摆招拉拽按扶"
    "递解扣插拔收翻掏看望瞧盯瞟听皱眯咂嚼沉顿愣怔"
)

#: 数词。称呼里出现在第三字及之后必是叙述（「三娘四十上下」）——
#: 首字的数词是合法的（「三娘」「老六」），所以只从 index 2 起切。
_NUMERALS = frozenset("零一二三四五六七八九十百千万两半几多0123456789")

#: 紧跟在人名后面的叙述副词。「沈砚忽然问：」这类三刀都切不动 ——
#: 「忽」「然」既不是动词也不是虚词更不是数词，可它们连起来是个副词。
#: 这是最常见的一种形式（人名 + 副词 + 动词），单字表拦不住，要按词拦。
_NARRATIVE_ADVERBS = (
    "忽然", "突然", "猛然", "陡然", "蓦地", "霍然", "骤然",
    "缓缓", "慢慢", "渐渐", "静静", "默默", "微微", "轻轻",
    "这才", "才又", "又再", "终于", "始终", "依旧", "仍旧", "早已",
    "分明", "居然", "竟然", "果然", "自然", "当即", "随即", "旋即",
    "低声", "高声", "大声", "轻声", "小声", "厉声", "沉声", "冷冷",
)


def trim_speaker(who: str) -> str | None:
    """把「李格非从里屋走出」裁成「李格非」，裁不干净就返回 None。

    两刀：先按动词切，再按助词/副词切。两刀之后仍不像称呼就放弃 ——
    **宁可没有说话人，也不要一个错的**。缺失可以由后面的
    speakers:resolve 用 LLM 补上（那一步本来就是干这个的），
    而错的说话人会一路污染实体抽取、音色分配和分镜的对话指向，
    且沿途没有任何一处会报错。
    """
    raw = (who or "").strip().strip("「」『』“”\"')( ")
    if not raw:
        return None

    # **只看第一个分句。** 冒号前有多个分句时，说话人可能在任何一句：
    #   「总镖头把镖单推过来，指节在桌上敲了两下」  在第一句
    #   「走到日头偏西，前头出现一片屋檐。老周勒住马」在最后一句
    # 逐句试会挑中错的 —— 第二例的第二句能产出「前头」，
    # 形状上完全合法，规则层面无从否定。「指节」同理。
    #
    # 所以宁可只认第一句：说话人不在第一句时返回 None，
    # 由后面的 speakers:resolve 用上下文补。漏一个可以补，错一个会一路传下去。
    return _trim_clause(re.split(r"[，,。.；;：:！!？?、]", raw)[0])


#: 动态助词。它们只跟在动词后面 —— 这是中文的硬语法，不是统计规律
_ASPECT = "着了过"


def _cut_by_grammar(w: str) -> str:
    """按语法结构切掉动词短语，不依赖动词表。

    「林昭撑着地站起来」→ 着在 index 3，说明 index 2 的「撑」是动词 → 林昭
    「老头点点头」→ 点点是叠字动词 → 老头

    只从 index 2 起判：两字名字整个是名字，里面的字不该被当成动词。
    切完不足两字就返回空串 —— 那说明整串本来就是个动词短语。

    叠字这一条要求**后面还有字**：「点点头」的点点是动词重叠，
    而「慢悠悠」的悠悠是 ABB 副词的尾巴 —— 后者交给第四刀整体处理，
    在这里切会剩下「老周慢」。
    """
    # 开头就是叠字 = 整串以动词重叠式开头（「摇摇头的老周」），
    # 那是个动词短语不是称呼。与 _STRONG_VERBS 的首字判断同一个道理，
    # 但不依赖认识哪个字
    if len(w) > 2 and w[0] == w[1]:
        return ""

    cuts: list[int] = []
    for i, ch in enumerate(w):
        if i >= 2 and ch in _ASPECT:
            cuts.append(i - 1)          # 助词前一个字是动词，从它切
        # 叠字动词要求**后面还有字**：「点点头」的点点是动词重叠，
        # 「慢悠悠」的悠悠是 ABB 副词的尾巴，切了会剩下「老周慢」。
        # 两者的区别就在于叠字之后还有没有内容
        if i >= 2 and i + 2 < len(w) and ch == w[i + 1]:
            cuts.append(i)
    if not cuts:
        return w
    out = w[: min(cuts)].strip()
    return out if len(out) >= 2 else ""


def _trim_clause(clause: str) -> str | None:
    """从单个分句里裁出称呼。裁不干净返回 None。"""
    w = clause.strip()
    if not w:
        return None

    # 整串以强动词开头 = 它是个动词短语，不是称呼。
    # 「走到日头偏西」的「走」、「摸出个油纸包」的「摸」都在这一档；
    # 而「高渐离」的「高」不在，因为那个字能当姓。
    if len(w) > 2 and w[0] in _STRONG_VERBS:
        return None

    # 第零刀：**按语法结构切，不按词表。**
    #
    # 动词表永远补不完 —— 「撑着地站起来」的撑、「点点头」的点、
    # 「试着按」的试，加一个漏一个。但中文有两条硬结构：
    #
    #   助词「着／了／过」前面**必是**动词
    #   叠字（点点、摇摇、笑笑）**必是**动词的重叠式
    #
    # 这两条不依赖认识哪个字，所以对没见过的动词一样管用。
    # 从 index 2 起找，两字名字（「苏晚」）不会被误伤。
    w = _cut_by_grammar(w)
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

    # 第四刀：ABB 式副词。「老周慢悠悠」的「慢悠悠」是一个词，
    # 按单字或 BB 切会切出「老周慢」这种半截。
    # 判据是叠尾：末两字相同且长度 ≥4，则末三字整体是 ABB。
    if len(w) >= 4 and w[-1] == w[-2]:
        cut = w[:-3].strip()
        # 切完不合法就整串作废 —— 「慢悠悠」本身不是称呼
        w = cut if len(cut) >= 2 else ""
        if not w:
            return None
    elif len(w) == 3 and w[-1] == w[-2]:
        # 「慢悠悠」这类整串就是 ABB 副词，切完什么都不剩
        return None

    # 第五刀：双字叙述副词。「沈砚忽然」前几刀全切不动 ——
    # 「忽」「然」单看都不在任何表里，连起来才是副词，所以要按词切。
    acut = [w.find(a) for a in _NARRATIVE_ADVERBS if w.find(a) >= 2]
    if acut:
        w = w[: min(acut)].strip()

    if w in _PRONOUNS or not (2 <= len(w) <= 6):
        return None
    # 仍含残留虚词的一律作废
    if any(c in _NON_NAME_CHARS for c in w):
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
