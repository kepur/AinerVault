"""小说导入与分章。

分章是用户接触系统的第一步，错了后面全错，所以这里用规则而非 LLM：
可预测、零成本、可复核。识别不了的情况宁可整篇作一章，也不瞎猜。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

#: 中文数字（含「两」与常见异体），用于把「第三十二章」转成 32
_CN_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9,
}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000}


def cn_to_int(text: str) -> int | None:
    """「三十二」→ 32；「一百零八」→ 108。纯阿拉伯数字直接返回。"""
    text = text.strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)

    total = 0
    section = 0
    number = 0
    for ch in text:
        if ch in _CN_DIGITS:
            number = _CN_DIGITS[ch]
        elif ch in _CN_UNITS:
            unit = _CN_UNITS[ch]
            if unit == 10000:
                section = (section + number) * unit
                total += section
                section = 0
            else:
                if number == 0:
                    number = 1   # 「十二」= 12
                section += number * unit
            number = 0
        else:
            return None
    result = total + section + number
    return result if result > 0 else None


#: 章节标题模式。按优先级排列 —— 越具体的越靠前。
_HEADING_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # 第一章 / 第1章 / 第三十二回 / 第 5 节
    ("cn_chapter", re.compile(
        r"^[\s　]{0,8}第\s*([0-9]{1,6}|[零〇一二两三四五六七八九十百千万]{1,12})\s*"
        r"[章回节卷篇折幕][\s　]*(.{0,60})$"
    )),
    # Chapter 12 / CHAPTER XII / Ch. 3
    ("en_chapter", re.compile(
        r"^[\s]{0,8}(?:chapter|chap\.?|ch\.)\s+([0-9]{1,6}|[ivxlcdm]{1,10})\s*[:.\-–—]?\s*(.{0,60})$",
        re.IGNORECASE,
    )),
    # markdown 标题
    ("markdown", re.compile(r"^#{1,3}\s+(.{1,80})$")),
    # 纯数字行 + 短标题：「12、初见」「12. 初见」
    ("numbered", re.compile(r"^[\s　]{0,8}([0-9]{1,4})\s*[、.．·]\s*(.{1,60})$")),
    # 楔子 / 序章 / 尾声 / 番外
    ("special", re.compile(
        r"^[\s　]{0,8}(楔子|序[章言幕]?|前言|引子|尾声|终章|后记|番外[一二三四五六七八九十0-9]{0,3})"
        r"[\s　]*(.{0,40})$"
    )),
)

_ROMAN = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}


def _roman_to_int(s: str) -> int | None:
    s = s.lower()
    if not s or any(c not in _ROMAN for c in s):
        return None
    total, prev = 0, 0
    for ch in reversed(s):
        val = _ROMAN[ch]
        total = total - val if val < prev else total + val
        prev = max(prev, val)
    return total or None


@dataclass(slots=True)
class ParsedChapter:
    order_no: int
    title: str
    content: str
    word_count: int = 0
    detected_by: str = "heuristic"
    heading_line: int | None = None


@dataclass(slots=True)
class IngestResult:
    chapters: list[ParsedChapter] = field(default_factory=list)
    pattern: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def total_words(self) -> int:
        return sum(c.word_count for c in self.chapters)


def count_words(text: str) -> int:
    """CJK 按字计，拉丁按词计 —— 混排时两者相加。"""
    cjk = len(re.findall(r"[一-鿿぀-ヿ가-힯]", text))
    latin = len(re.findall(r"[A-Za-z][A-Za-z'\-]*", text))
    return cjk + latin


def _match_heading(line: str) -> tuple[str, int | None, str] | None:
    """返回 (模式名, 序号或 None, 标题)。"""
    stripped = line.strip()
    if not stripped or len(stripped) > 80:
        return None

    for name, pat in _HEADING_PATTERNS:
        m = pat.match(stripped)
        if not m:
            continue
        if name == "markdown":
            return name, None, m.group(1).strip()
        if name == "special":
            tail = (m.group(2) or "").strip()
            title = f"{m.group(1)} {tail}".strip()
            return name, None, title
        raw_no = m.group(1)
        no = cn_to_int(raw_no) if not raw_no.isdigit() else int(raw_no)
        if no is None and name == "en_chapter":
            no = _roman_to_int(raw_no)
        tail = (m.group(2) or "").strip(" 　:：.-–—")
        title = stripped if not tail else f"{stripped}"
        return name, no, title
    return None


def split_chapters(
    text: str, *, min_chapter_words: int = 15, max_chapters: int = 5000
) -> IngestResult:
    """按标题行切分。

    只采用出现次数最多的那一种模式 —— 混用多种模式切出来的结果通常是误判
    （比如正文里偶然出现「第一次」被 numbered 命中）。
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")

    hits: list[tuple[int, str, int | None, str]] = []
    for idx, line in enumerate(lines):
        m = _match_heading(line)
        if m:
            hits.append((idx, m[0], m[1], m[2]))

    result = IngestResult()
    if not hits:
        body = text.strip()
        result.chapters = [
            ParsedChapter(1, "全文", body, count_words(body), detected_by="single")
        ]
        result.warnings.append("未识别到章节标题，已整篇作为一章。可手动拆分。")
        return result

    # 「楔子 / 序章 / 尾声 / 番外」始终与主模式共存，不参与竞争。
    # 它们独立成行时几乎不可能是正文，而「楔子 + 第一章 + 番外」是极常见的结构 ——
    # 若按出现次数二选一，第一章会被整个吃掉。
    special_hits = [h for h in hits if h[1] == "special"]
    rival_hits = [h for h in hits if h[1] != "special"]

    if rival_hits:
        counts: dict[str, int] = {}
        for _, name, _, _ in rival_hits:
            counts[name] = counts.get(name, 0) + 1
        pattern = max(counts, key=lambda k: counts[k])
        if len(counts) > 1:
            result.warnings.append(
                f"检测到多种标题格式 {counts}，采用出现最多的 {pattern}，忽略其余。"
            )
        marks = sorted(
            [h for h in rival_hits if h[1] == pattern] + special_hits,
            key=lambda h: h[0],
        )
        result.pattern = f"{pattern}+special" if special_hits else pattern
    else:
        pattern = "special"
        marks = special_hits
        result.pattern = pattern
    if len(marks) > max_chapters:
        result.warnings.append(f"标题行 {len(marks)} 个超过上限 {max_chapters}，已截断。")
        marks = marks[:max_chapters]

    # 首个标题之前的内容当作前言
    chapters: list[ParsedChapter] = []
    first_line = marks[0][0]
    preface = "\n".join(lines[:first_line]).strip()
    if count_words(preface) >= min_chapter_words:
        chapters.append(
            ParsedChapter(0, "前言", preface, count_words(preface), detected_by="preface")
        )

    for i, (line_idx, name, no, title) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(lines)
        body = "\n".join(lines[line_idx + 1:end]).strip()
        chapters.append(
            ParsedChapter(
                order_no=0,   # 稍后统一重排
                title=title or f"第 {no or i + 1} 章",
                content=body,
                word_count=count_words(body),
                detected_by=name,
                heading_line=line_idx,
            )
        )

    # 序号是否单调递增 —— 比字数强得多的信号。
    # 真章节标题编号连续；正文里偶然命中的（「第一次」「第三个人」）不会构成递增序列。
    # 分母只算带编号的模式：special（楔子/尾声/番外）本就无编号，不该拉低比例。
    numbered_marks = [h for h in marks if h[1] != "special"]
    numbers = [no for _, _, no, _ in numbered_marks if no is not None]
    numbering_is_sound = (
        len(numbers) >= 2
        and len(numbers) >= len(numbered_marks) * 0.8
        and all(b > a for a, b in zip(numbers, numbers[1:]))
    )

    if numbering_is_sound:
        # 编号可信：一律不因字数合并。最后一章本来就可能只有一句话。
        merged = chapters
    else:
        merged = []
        for ch in chapters:
            if (
                merged
                and ch.word_count < min_chapter_words
                # special 是明确的结构标记，无论多短都自成一章
                and ch.detected_by not in {"preface", "single", "special"}
            ):
                prev = merged[-1]
                prev.content = f"{prev.content}\n\n{ch.title}\n{ch.content}".strip()
                prev.word_count = count_words(prev.content)
                continue
            merged.append(ch)

        dropped_count = len(chapters) - len(merged)
        if dropped_count:
            result.warnings.append(
                f"{dropped_count} 处标题后内容不足 {min_chapter_words} 字，"
                f"且章节编号不连续，已并入上一章。"
            )

    if numbers and not numbering_is_sound and len(numbers) >= 2:
        result.warnings.append("章节编号不连续，切分结果请人工复核。")

    for i, ch in enumerate(merged, start=1):
        ch.order_no = i
    result.chapters = merged
    return result
