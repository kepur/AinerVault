"""无词典新词发现 —— 挖掘未被词表覆盖的名物候选。

固定滑窗会切出「他推开客」「栈的门」这类碎片，送给 LLM 判定纯属浪费 token。
三个条件同时约束才能筛出真词：
  频次     至少出现 min_freq 次
  凝固度   整体出现概率显著高于内部拆分后各部分独立出现的乘积
  邻接熵   左右邻字足够多样，说明它不是某个更长固定搭配的一截

产出的候选再交给 survey 的 LLM 层判定语义与译法 —— 统计负责去碎片，LLM 负责懂文化。
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


def mine_candidates(
    texts: Iterable[str],
    covered_forms: set[str],
    *,
    min_freq: int = 3,
    min_entropy: float = 0.8,
    min_cohesion: float = 3.0,
    max_len: int = 4,
    limit: int = 60,
) -> list[tuple[str, int]]:
    """无词典新词发现：频次 + 凝固度 + 左右邻接熵。

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
