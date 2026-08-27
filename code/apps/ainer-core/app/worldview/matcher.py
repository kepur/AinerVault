"""名物词表扫描器。

Aho–Corasick 一次遍历找出文本中所有命中的词条。中文无空格，直接按字符扫；
重叠命中取最长匹配（「客栈」优先于「客」），这与占位符替换按长度倒序是同一个道理。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence

# 中文数词与阿拉伯数字 —— 单字量词（里/斤/尺）只在紧跟数量后才算命中
_NUMERIC = frozenset("0123456789０１２３４５６７８９零一二三四五六七八九十百千万两几半廿卅")
_CJK = re.compile(r"[一-鿿]")


def _is_cjk(ch: str) -> bool:
    return bool(_CJK.match(ch))

try:
    import ahocorasick
except ImportError:  # pragma: no cover
    ahocorasick = None


@dataclass(frozen=True, slots=True)
class Hit:
    term: str          # 实际命中的字面（可能是别名）
    key: str           # 词条标识（source_term）
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start


class LexiconMatcher:
    """把 (source_term, aliases) 编成一台自动机。

    构建一次，可反复扫描多个章节 —— 全书勘探时这一点很重要。
    """

    def __init__(
        self,
        terms: dict[str, Sequence[str]],
        *,
        measure_terms: Sequence[str] = (),
    ) -> None:
        """terms: {source_term: [别名...]}，别名与本名都会被匹配。

        measure_terms 列出度量单位类词条（里/斤/尺）—— 它们的单字匹配规则更严，
        必须紧跟数量词，否则「心里」「手里」全会被当成距离单位。
        """
        self._terms = terms
        self._measures = {str(m) for m in measure_terms}
        self._automaton = None
        self._fallback: list[tuple[str, str]] = []

        pairs: list[tuple[str, str]] = []
        for key, aliases in terms.items():
            for surface in {key, *(aliases or [])}:
                surface = str(surface or "").strip()
                if surface:
                    pairs.append((surface, key))

        if ahocorasick is not None and pairs:
            auto = ahocorasick.Automaton()
            for surface, key in pairs:
                # 同一字面可能对应多个词条，保留先到的
                if not auto.exists(surface):
                    auto.add_word(surface, (surface, key))
            auto.make_automaton()
            self._automaton = auto
        else:
            # 无 pyahocorasick 时退化为朴素扫描，长词优先
            self._fallback = sorted(pairs, key=lambda p: len(p[0]), reverse=True)

    def __bool__(self) -> bool:
        return bool(self._automaton or self._fallback)

    def find(self, text: str) -> list[Hit]:
        """返回去重叠后的命中，按出现位置升序。"""
        if not text or not self:
            return []
        raw = [
            h for h in self._find_raw(text)
            if _valid_single_char(text, h, h.key in self._measures)
        ]
        return _resolve_overlaps(raw)

    def _find_raw(self, text: str) -> list[Hit]:
        hits: list[Hit] = []
        if self._automaton is not None:
            for end_idx, (surface, key) in self._automaton.iter(text):
                start = end_idx - len(surface) + 1
                hits.append(Hit(term=surface, key=key, start=start, end=end_idx + 1))
        else:
            for surface, key in self._fallback:
                start = text.find(surface)
                while start != -1:
                    hits.append(Hit(surface, key, start, start + len(surface)))
                    start = text.find(surface, start + 1)
        return hits

    def count(self, texts: Iterable[str]) -> dict[str, int]:
        """统计各词条在多段文本中的命中次数，用于 hit_count 与覆盖率。"""
        totals: dict[str, int] = {}
        for text in texts:
            for hit in self.find(text):
                totals[hit.key] = totals.get(hit.key, 0) + 1
        return totals


def _valid_single_char(text: str, hit: Hit, is_measure: bool) -> bool:
    """单字词条的上下文约束。

    中文没有词边界，单字词条会疯狂误命中：
      「里」命中「心里」「手里」的里 —— 那不是距离单位
      「面」命中「扑面而来」的面 —— 那不是面条
    误报比漏报危害大得多：错误的对照会被注入 prompt，还会产生假的漏译违规。

    两类规则：
      度量单位（里/斤/尺）  必须紧跟数量词 —— 「三十里」成立，「心里」不成立
      普通名词（茶/酒/粥）  后面不是汉字即可 —— 「一碗粥。」成立，「粥铺」不成立
    """
    if len(hit.term) > 1:
        return True
    prev_ch = text[hit.start - 1] if hit.start > 0 else ""
    next_ch = text[hit.end] if hit.end < len(text) else ""

    if is_measure:
        return bool(prev_ch) and prev_ch in _NUMERIC
    if prev_ch and prev_ch in _NUMERIC:
        return True
    return not _is_cjk(next_ch)


def _resolve_overlaps(hits: list[Hit]) -> list[Hit]:
    """重叠时保留最长的那个。

    「客栈」与「客」同时命中同一位置，只应算「客栈」——
    否则会给译文注入一条无意义的单字规则，并污染 hit_count。
    """
    if not hits:
        return []
    # 先按 (起点升序, 长度降序) 排，再贪心取不重叠的
    ordered = sorted(hits, key=lambda h: (h.start, -h.length))
    kept: list[Hit] = []
    cursor = -1
    for hit in ordered:
        if hit.start >= cursor:
            kept.append(hit)
            cursor = hit.end
    return kept


def scan_forbidden(text: str, forbidden: Iterable[str]) -> list[str]:
    """闸二的反向校验：译文里出现了禁用词就是违规。

    拉丁词按单词边界匹配，避免 "inn" 命中 "beginning"；CJK 直接子串匹配。
    """
    import re

    found: list[str] = []
    if not text:
        return found
    lowered = text.lower()
    for word in forbidden:
        word = str(word or "").strip()
        if not word:
            continue
        if word.isascii():
            if re.search(rf"\b{re.escape(word.lower())}\b", lowered):
                found.append(word)
        elif word in text:
            found.append(word)
    return found
