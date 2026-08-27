"""导入与分章。

分章优先用文本自身的章节标记；识别不到再按长度切分。
不调用 LLM —— 这一步纯规则，快且免费。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# 常见章节标题形态。按特异性排序，先匹配更具体的。
_CHAPTER_PATTERNS: tuple[re.Pattern[str], ...] = (
    # 第一章 / 第1章 / 第一回 / 第 001 节
    re.compile(r"^[ \t　]*第\s*[0-9零一二三四五六七八九十百千万两]+\s*[章回节卷篇折]"
               r"[ \t　]*[:：、.\-—]?[ \t　]*(?P<title>.*)$"),
    # Chapter 12 / CHAPTER XII
    re.compile(r"^[ \t]*(?:chapter|CHAPTER|Chapter)\s+(?:[0-9]+|[IVXLCDM]+)"
               r"[ \t]*[:.\-—]?[ \t]*(?P<title>.*)$"),
    # 卷首 / 楔子 / 序章 / 尾声 / 番外
    re.compile(r"^[ \t　]*(?P<title>楔子|序章|序幕|引子|尾声|终章|后记|番外[^\n]{0,20})[ \t　]*$"),
    # 纯数字行作标题：  12  /  12、标题
    re.compile(r"^[ \t　]*(?P<num>[0-9]{1,4})[ \t　]*[、.,:：]?[ \t　]*(?P<title>.{0,40})$"),
)

_MD_HEADING = re.compile(r"^(#{1,3})\s+(?P<title>.+?)\s*$")


@dataclass
class ParsedChapter:
    order_no: int
    title: str | None
    content: str
    word_count: int = 0
    detected_by: str = "length"

    def __post_init__(self) -> None:
        self.word_count = count_words(self.content)


@dataclass
class IngestResult:
    chapters: list[ParsedChapter] = field(default_factory=list)
    strategy: str = "length"
    detected_headings: int = 0

    @property
    def total_words(self) -> int:
        return sum(c.word_count for c in self.chapters)


def count_words(text: str) -> int:
    """CJK 按字计，拉丁按词计。混排时两者相加。"""
    cjk = len(re.findall(r"[㐀-鿿぀-ヿ가-힯]", text))
    latin = len(re.findall(r"[A-Za-z][A-Za-z'\-]*", text))
    return cjk + latin


def _match_heading(line: str, *, markdown: bool) -> tuple[str | None, str] | None:
    """返回 (标题, 识别方式)；不是标题则 None。"""
    stripped = line.strip()
    if not stripped or len(stripped) > 60:
        return None

    if markdown:
        m = _MD_HEADING.match(line)
        if m:
            return m.group("title").strip() or None, "markdown"

    for idx, pat in enumerate(_CHAPTER_PATTERNS):
        m = pat.match(line)
        if not m:
            continue
        # 纯数字行风险高：仅当整行很短且不像正文时才认
        if idx == len(_CHAPTER_PATTERNS) - 1:
            tail = (m.groupdict().get("title") or "").strip()
            if tail and (len(tail) > 20 or tail[-1] in "。，！？、；：,.!?"):
                return None
            title = f"{m.group('num')} {tail}".strip()
            return title, "numeric"
        title = (m.groupdict().get("title") or "").strip()
        return (title or stripped), "pattern"
    return None


def split_chapters(
    text: str,
    *,
    source_format: str = "plain",
    min_chars: int = 200,
    fallback_chars: int = 3000,
) -> IngestResult:
    """把整本文本切成章节。

    min_chars: 低于此长度的段落不单独成章，并入前一章（防止把目录行切成空章）。
    fallback_chars: 未识别到任何章节标记时，按此长度在段落边界切分。
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    markdown = source_format == "markdown"

    buckets: list[tuple[str | None, list[str], str]] = []
    current_title: str | None = None
    current_lines: list[str] = []
    current_by = "length"
    heading_count = 0

    for line in lines:
        hit = _match_heading(line, markdown=markdown)
        if hit is not None:
            title, by = hit
            if current_lines or current_title is not None:
                buckets.append((current_title, current_lines, current_by))
            current_title, current_lines, current_by = title, [], by
            heading_count += 1
        else:
            current_lines.append(line)
    if current_lines or current_title is not None:
        buckets.append((current_title, current_lines, current_by))

    # 去掉开头没有标题且内容极短的桶（通常是书名页/目录残留）
    if buckets and buckets[0][0] is None and len("\n".join(buckets[0][1]).strip()) < min_chars:
        buckets.pop(0)

    if heading_count == 0 or not buckets:
        return _split_by_length(text, fallback_chars)

    # 合并过短的桶到前一章。
    # 只合并弱信号（无标题、纯数字行）—— 「第二章」这类强标记即使内容很短也是真章节，
    # 按长度合并它会把真实的章节结构吃掉。
    weak = {"length", "numeric"}
    merged: list[tuple[str | None, list[str], str]] = []
    for title, body, by in buckets:
        content = "\n".join(body).strip()
        if merged and by in weak and len(content) < min_chars:
            prev_title, prev_body, prev_by = merged[-1]
            extra = ([title] if title else []) + body
            merged[-1] = (prev_title, prev_body + extra, prev_by)
            continue
        merged.append((title, body, by))

    chapters = [
        ParsedChapter(
            order_no=i + 1,
            title=title,
            content="\n".join(body).strip(),
            detected_by=by,
        )
        for i, (title, body, by) in enumerate(merged)
    ]
    chapters = [c for c in chapters if c.content or c.title]
    for i, c in enumerate(chapters):
        c.order_no = i + 1

    return IngestResult(chapters=chapters, strategy="heading", detected_headings=heading_count)


_SENT_END = re.compile(r"(?<=[。！？!?…])\s*|(?<=[.!?])\s+")


def _split_long_paragraph(para: str, chunk: int) -> list[str]:
    """单段就超长时（很多网文全文无空行），退到句子边界切。"""
    if len(para) <= chunk * 2:
        return [para]
    sentences = [s for s in _SENT_END.split(para) if s and s.strip()]
    out: list[str] = []
    buf: list[str] = []
    size = 0
    for sent in sentences:
        buf.append(sent)
        size += len(sent)
        if size >= chunk:
            out.append("".join(buf))
            buf, size = [], 0
    if buf:
        out.append("".join(buf))
    return out or [para]


def _split_by_length(text: str, chunk: int) -> IngestResult:
    """无章节标记时的兜底：优先段落边界，单段过长则退到句子边界。"""
    raw_paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    paragraphs: list[str] = []
    for p in raw_paragraphs:
        paragraphs.extend(_split_long_paragraph(p, chunk))
    chapters: list[ParsedChapter] = []
    buf: list[str] = []
    size = 0

    for para in paragraphs:
        buf.append(para)
        size += len(para)
        if size >= chunk:
            chapters.append(
                ParsedChapter(order_no=len(chapters) + 1, title=None,
                              content="\n\n".join(buf).strip())
            )
            buf, size = [], 0
    if buf:
        chapters.append(
            ParsedChapter(order_no=len(chapters) + 1, title=None,
                          content="\n\n".join(buf).strip())
        )
    if not chapters and text.strip():
        chapters.append(ParsedChapter(order_no=1, title=None, content=text.strip()))
    return IngestResult(chapters=chapters, strategy="length")
