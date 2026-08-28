"""无词典新词发现 —— 挖掘未被词表覆盖的名物候选。

**两套算法，按源语言分流。**

不分词的语言（中日）走 n-gram 统计：固定滑窗会切出「他推开客」「栈的门」
这类碎片，送给 LLM 判定纯属浪费 token，所以要三个条件同时约束：
  频次     至少出现 min_freq 次
  凝固度   整体出现概率显著高于内部拆分后各部分独立出现的乘积
  邻接熵   左右邻字足够多样，说明它不是某个更长固定搭配的一截

用空格分词的语言（英西法葡俄阿孟印）根本没有切分问题 —— 词边界是现成的。
在这些语言上跑 n-gram 是把简单问题做复杂：真正要筛的是
「哪些词是名物而非普通词」，靠的是**低频高信息量**，
恰好与 CJK 的「高频高凝固」相反。所以另走一套：
停用词过滤 + 词频反选 + 多词术语（bigram/trigram）搭配强度。

产出的候选再交给 survey 的 LLM 层判定语义与译法 ——
统计负责去碎片和降噪，LLM 负责懂文化。
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Iterable

# 高频功能词。出现在候选词边界即判定为切分错误。
_STOPCHARS = frozenset(
    "的了是在我你他她它们这那有和就不都一个上去来说着过还要会到没很把被给对"
    "以及与或但因所之其为于而且则也又再从向如此який"
)
_PUNCT = frozenset("，。！？；：、「」『』“”‘’（）《》〈〉…—　 \n\r\t·．,.!?;:\"'()[]{}<>")
_CJK_CHAR = re.compile(r"[一-鿿]")
#: 日文假名。日语同样不用空格分词，走 n-gram 那条路。
_KANA = re.compile(r"[ぁ-ゖァ-ヺー]")

#: 用空格分词的语言。名单之外一律按不分词处理 ——
#: 判错方向的代价不对称：对 CJK 用空格切分会得到整段文本当一个「词」，
#: 而对空格语言用 n-gram 只是慢和吵，还能出结果。
_SPACED_LANGS = frozenset({
    "en", "es", "fr", "pt", "ru", "de", "it", "nl", "pl", "tr",
    "id", "vi", "sw", "ar", "hi", "bn", "fa", "ur",
})

#: 空格语言的停用词。不求全 —— 挡住功能词与叙事高频动词即可，
#: 剩下的噪声交给 LLM 层判语义，那本来就是它的职责。
#: 想在这里挡尽所有动词是徒劳的，还会误伤名物（"draw" 在织物语境是抽纱）。
_STOPWORDS = frozenset("""
a an the and or but if then than that this these those of in on at to for from by with
without into onto upon over under about above below between among through during before
after since until while as is are was were be been being am do does did done have has had
having will would shall should can could may might must not no nor so such very too also
he she it they them his her its their our your my me him us we you i one two do
de la el los las un una y o que en por para con del al se es son era eran como más pero
le les des du au aux et ou qui que dans sur pour par avec sans est sont était être
out up down off away back again here there now then once still just only even ever never
said says say told tell asked ask replied answered went come came go goes going gone
saw see seen look looked looking make made makes take took taken get got give gave given
know knew known think thought turn turned put set let leave left keep kept find found
felt feel seem seemed become became bring brought hold held stand stood sit sat
her him his hers ours yours theirs mine what when where which who whom whose why how
all any both each few more most other some own same
upon toward towards against beneath behind beside within across along around
o os as um uma e ou que em por para com do da no na se é são
и в на с по для от до из за не что как это был была были быть его её их
""".split())


def _segments(text: str, covered_forms: set[str]) -> list[str]:
    """按标点与已覆盖词切开，得到不含已知词的连续汉字片段。"""
    for form in sorted(covered_forms, key=len, reverse=True):
        if form:
            text = text.replace(form, "\x00")
    out: list[str] = []
    buf: list[str] = []
    for ch in text:
        if ch in _PUNCT or ch == "\x00" or not _CJK_CHAR.match(ch):
            if buf:
                out.append("".join(buf))
                buf = []
        else:
            buf.append(ch)
    if buf:
        out.append("".join(buf))
    return out


def _entropy(counter: Counter) -> float:
    """邻接字的信息熵。熵高说明该串能出现在多种语境里，更可能是独立的词。"""
    total = sum(counter.values())
    if total <= 0:
        return 0.0
    acc = 0.0
    for n in counter.values():
        p = n / total
        acc -= p * math.log(p, 2)
    return acc


def uses_spaces(language_code: str | None) -> bool:
    """该语言是否用空格分词。"""
    if not language_code:
        return False
    return str(language_code).split("-")[0].split("_")[0].lower() in _SPACED_LANGS


def mine_candidates(
    texts: Iterable[str],
    covered_forms: set[str],
    *,
    language_code: str | None = None,
    min_freq: int = 3,
    min_entropy: float = 0.8,
    min_cohesion: float = 3.0,
    max_len: int = 4,
    limit: int = 60,
) -> list[tuple[str, int]]:
    """按源语言分流到两套算法。

    language_code 为空时按内容嗅探：含汉字或假名走 n-gram，否则走空格分词。
    嗅探而不是硬报错，是因为老数据的 source_language_code 可能没填，
    而挖不出候选词的表现是「LLM 层静默返回 0 条」—— 排查起来毫无线索。
    """
    texts = [t for t in texts if t]
    if not texts:
        return []
    blob = "\n".join(texts)
    spaced = (
        uses_spaces(language_code) if language_code
        else not (_CJK_CHAR.search(blob) or _KANA.search(blob))
    )
    if spaced:
        return _mine_spaced(texts, covered_forms, min_freq=min_freq, limit=limit)
    return _mine_ngram(
        texts, covered_forms, min_freq=min_freq, min_entropy=min_entropy,
        min_cohesion=min_cohesion, max_len=max_len, limit=limit,
    )


_WORD = re.compile(r"[^\W\d_]+(?:['\u2019-][^\W\d_]+)*", re.UNICODE)


def _mine_spaced(
    texts: list[str], covered_forms: set[str], *,
    min_freq: int = 2, limit: int = 60,
) -> list[tuple[str, int]]:
    """空格语言的候选挖掘。

    这里的筛选方向与 CJK 相反。CJK 找的是「高频高凝固」——因为要先确定
    词边界在哪。空格语言词边界是现成的，要找的是「哪些词是名物」，
    而名物的特征恰恰是**相对低频但重复出现**：
    普通词（said、went、door）满篇都是，名物（palanquin、doublet、bailiff）
    出现几次但集中。所以按「出现过至少 min_freq 次、且不在最高频那一档」筛。

    多词术语（morning room、chaise and four）单看词频会被拆散，
    所以另收 bigram/trigram —— 判据是搭配强度而非绝对频次。
    """
    covered_low = {c.lower() for c in covered_forms if c}
    tokens_per_text: list[list[str]] = [
        [m.group(0) for m in _WORD.finditer(t)] for t in texts
    ]
    all_tokens = [w for seq in tokens_per_text for w in seq]
    if not all_tokens:
        return []

    freq: Counter[str] = Counter(w.lower() for w in all_tokens)
    # 原形优先保留首次出现的大小写，专名的大写本身是线索
    surface: dict[str, str] = {}
    for w in all_tokens:
        surface.setdefault(w.lower(), w)

    total = sum(freq.values())
    # 最高频的一档几乎全是功能词与叙事动词。切在 1% 是经验值：
    # 再低会漏掉常见名物（inn、sword），再高会放进大量 said/looked。
    hi_cut = max(min_freq * 4, total * 0.01)

    scored: list[tuple[str, int, float]] = []
    for w, n in freq.items():
        if n < min_freq or len(w) < 3:
            continue
        if w in _STOPWORDS or w in covered_low:
            continue
        if n > hi_cut:
            continue
        # 集中度：出现在越少的段落里、单段内越密集，越像专有名物
        in_texts = sum(1 for seq in tokens_per_text if any(x.lower() == w for x in seq))
        concentration = n / max(in_texts, 1)
        cap = surface[w][:1].isupper()
        scored.append((surface[w], n, n * concentration * (1.6 if cap else 1.0)))

    # 多词术语：相邻两词的搭配强度（共现 / 各自频次）
    bigrams: Counter[tuple[str, str]] = Counter()
    for seq in tokens_per_text:
        low = [x.lower() for x in seq]
        for a, b in zip(low, low[1:]):
            if a in _STOPWORDS or b in _STOPWORDS:
                continue
            if len(a) < 3 or len(b) < 3:
                continue
            bigrams[(a, b)] += 1
    for (a, b), n in bigrams.items():
        if n < min_freq:
            continue
        phrase = f"{surface[a]} {surface[b]}"
        if phrase.lower() in covered_low:
            continue
        strength = n * n / max(freq[a] * freq[b], 1)
        if strength < 0.05:
            continue
        scored.append((phrase, n, n * strength * 12))

    scored.sort(key=lambda r: (-r[2], -r[1]))
    # 被更优的多词术语完全包含的单词丢掉
    kept: list[tuple[str, int]] = []
    taken: list[str] = []
    for w, n, _ in scored:
        wl = w.lower()
        if any(wl in t and wl != t for t in taken):
            continue
        taken.append(wl)
        kept.append((w, n))
        if len(kept) >= limit:
            break
    return kept


def _mine_ngram(
    texts: list[str],
    covered_forms: set[str],
    *,
    min_freq: int = 3,
    min_entropy: float = 0.8,
    min_cohesion: float = 3.0,
    max_len: int = 4,
    limit: int = 60,
) -> list[tuple[str, int]]:
    """不分词语言（中日）的新词发现：频次 + 凝固度 + 左右邻接熵。

    固定滑窗会切出「他推开客」「栈的门」这类碎片；三个条件同时约束才能筛出真词：
      - 频次    ：至少出现 min_freq 次
      - 凝固度  ：整体出现概率显著高于内部拆分后各部分独立出现的乘积
      - 邻接熵  ：左右邻字足够多样，说明它不是某个更长固定搭配的一截
    """
    segs: list[str] = []
    for t in texts:
        if t:
            segs.extend(_segments(t, covered_forms))
    if not segs:
        return []

    char_freq: Counter[str] = Counter()
    gram_freq: Counter[str] = Counter()
    left_ctx: dict[str, Counter] = {}
    right_ctx: dict[str, Counter] = {}

    for seg in segs:
        char_freq.update(seg)
        n = len(seg)
        for size in range(2, max_len + 1):
            for i in range(n - size + 1):
                w = seg[i : i + size]
                gram_freq[w] += 1
                left_ctx.setdefault(w, Counter())[seg[i - 1] if i > 0 else "^"] += 1
                right_ctx.setdefault(w, Counter())[
                    seg[i + size] if i + size < n else "$"
                ] += 1

    total_chars = sum(char_freq.values()) or 1
    results: list[tuple[str, int, float]] = []

    for w, freq in gram_freq.items():
        if freq < min_freq:
            continue
        if w[0] in _STOPCHARS or w[-1] in _STOPCHARS:
            continue
        if w in covered_forms:
            continue

        # 凝固度：取所有二分切法中最保守的一个
        p_w = freq / total_chars
        cohesion = min(
            p_w / ((char_freq[w[:i]] if len(w[:i]) == 1 else gram_freq.get(w[:i], 0)) / total_chars
                   * (char_freq[w[i:]] if len(w[i:]) == 1 else gram_freq.get(w[i:], 0)) / total_chars)
            for i in range(1, len(w))
            if (char_freq[w[:i]] if len(w[:i]) == 1 else gram_freq.get(w[:i], 0))
            and (char_freq[w[i:]] if len(w[i:]) == 1 else gram_freq.get(w[i:], 0))
        ) if len(w) > 1 else 0.0
        if cohesion < min_cohesion:
            continue

        ent = min(_entropy(left_ctx[w]), _entropy(right_ctx[w]))
        if ent < min_entropy:
            continue

        results.append((w, freq, ent * cohesion))

    # 去掉被更优超集完全包含的碎片
    results.sort(key=lambda r: (-len(r[0]), -r[2]))
    kept: list[tuple[str, int, float]] = []
    for w, freq, score in results:
        if any(w in k and w != k and freq <= kf * 1.2 for k, kf, _ in kept):
            continue
        kept.append((w, freq, score))

    kept.sort(key=lambda r: (-r[2], -r[1]))
    return [(w, f) for w, f, _ in kept[:limit]]
