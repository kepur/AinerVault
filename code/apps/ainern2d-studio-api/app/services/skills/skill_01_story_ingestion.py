"""SKILL 01: StoryIngestionService — 业务逻辑实现。
参考规格: SKILL_01_STORY_INGESTION_NORMALIZATION.md
状态: SERVICE_READY
"""
from __future__ import annotations

import re
import unicodedata
from uuid import uuid4

from loguru import logger
from sqlalchemy.orm import Session

from ainern2d_shared.schemas.skills.skill_01 import (
    DocumentMeta,
    DocumentStructure,
    IngestionLogEntry,
    IngestionOptions,
    LanguageDetection,
    MixedLanguageInfo,
    QualityReport,
    Segment,
    Skill01Input,
    Skill01Output,
)
from ainern2d_shared.services.base_skill import BaseSkillService, SkillContext
from ainern2d_shared.utils.time import utcnow

# ── Constants ──────────────────────────────────────────────────────────────────
_VALID_SOURCE_TYPES = {
    "text", "manual_text", "web_scrape", "file_upload", "ocr_text", "api_payload",
}
_MIN_TEXT_LENGTH = 20

_CHAPTER_PATTERN = re.compile(
    r"(?:^|\n)\s*(?:第[一二三四五六七八九十百千\d]+[章节回部篇]|Chapter\s+\d+|CHAPTER\s+\d+|Scene\s+\d+)",
    re.MULTILINE,
)
_CONTROL_CHAR_RE = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b\u200c\u200d\ufeff]"
)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MD_LINK_IMG_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MD_HEADING_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_MD_HR_RE = re.compile(r"^[-*_]{3,}\s*$", re.MULTILINE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？.!?])\s*(?=\S)")


def _char_ratio(text: str, ranges: list[tuple[int, int]]) -> float:
    """Fraction of characters whose codepoint falls in any of *ranges*."""
    if not text:
        return 0.0
    count = sum(1 for ch in text if any(lo <= ord(ch) <= hi for lo, hi in ranges))
    return count / len(text)


def _make_log(action: str, detail: str = "") -> IngestionLogEntry:
    """Create a structured ingestion log entry with UTC timestamp."""
    return IngestionLogEntry(action=action, detail=detail, timestamp=utcnow().isoformat())


class StoryIngestionService(BaseSkillService[Skill01Input, Skill01Output]):
    """SKILL 01 — Story Ingestion & Normalization.

    State machine: INIT → PRECHECKING → NORMALIZING → PARSING_STRUCTURE
                       → DETECTING_LANGUAGE → QUALITY_CHECKING
                       → READY_FOR_ROUTING | REVIEW_REQUIRED | FAILED
    """

    skill_id = "skill_01"
    skill_name = "StoryIngestionService"

    def __init__(self, db: Session) -> None:
        super().__init__(db)

    # ── Public entry ───────────────────────────────────────────────────────────

    def execute(self, input_dto: Skill01Input, ctx: SkillContext) -> Skill01Output:
        ingestion_log: list[IngestionLogEntry] = []
        warnings: list[str] = []

        # ── Resolve effective options from ingestion_options + feature_flags ──
        opts = input_dto.ingestion_options or IngestionOptions()
        ff = input_dto.feature_flags or {}
        enable_sentence_split = opts.enable_sentence_split or ff.get("enable_sentence_split", False)
        strict_mode = opts.strict_mode

        # ── [I1] Source Precheck ─────────────────────────────────────────────
        self._record_state(ctx, "INIT", "PRECHECKING")
        issues = self._source_precheck(input_dto)
        if issues:
            self._record_state(ctx, "PRECHECKING", "FAILED")
            raise ValueError(f"REQ-VALIDATION-001: {'; '.join(issues)}")
        ingestion_log.append(_make_log("precheck_passed"))

        # ── [I2] Text Normalization ──────────────────────────────────────────
        self._record_state(ctx, "PRECHECKING", "NORMALIZING")
        normalized_text, norm_log = self._normalize_text(
            input_dto.raw_text,
            source_type=input_dto.input_source_type,
            preserve_html=opts.preserve_html_tags,
        )
        ingestion_log.extend(norm_log)

        if strict_mode and any(e.action.startswith("warning") for e in norm_log):
            self._record_state(ctx, "NORMALIZING", "FAILED")
            raise ValueError("REQ-VALIDATION-001: strict_mode — normalization produced warnings")

        # ── [I3] Structure Parsing ───────────────────────────────────────────
        self._record_state(ctx, "NORMALIZING", "PARSING_STRUCTURE")
        structure, segments, title = self._parse_structure(
            normalized_text,
            enable_sentence_split=enable_sentence_split,
        )
        ingestion_log.append(_make_log(
            "parsed",
            f"chapters={structure.chapter_count} paragraphs={structure.paragraph_count}",
        ))

        # ── [I4] Language Detection ──────────────────────────────────────────
        self._record_state(ctx, "PARSING_STRUCTURE", "DETECTING_LANGUAGE")
        language_detection, lang_warnings = self._detect_language(normalized_text)
        warnings.extend(lang_warnings)
        ingestion_log.append(_make_log("language_detected", language_detection.primary_language))

        # Per-segment language tagging
        segments = self._tag_segment_languages(segments)

        if strict_mode and lang_warnings:
            self._record_state(ctx, "DETECTING_LANGUAGE", "FAILED")
            raise ValueError(f"REQ-VALIDATION-001: strict_mode — language warnings: {'; '.join(lang_warnings)}")

        # ── [I5] Quality Report ──────────────────────────────────────────────
        self._record_state(ctx, "DETECTING_LANGUAGE", "QUALITY_CHECKING")
        quality_report, quality_warnings = self._quality_check(normalized_text, segments)
        warnings.extend(quality_warnings)

        if strict_mode and quality_warnings:
            self._record_state(ctx, "QUALITY_CHECKING", "FAILED")
            raise ValueError(f"REQ-VALIDATION-001: strict_mode — quality issues: {'; '.join(quality_warnings)}")

        # ── Final status decision ────────────────────────────────────────────
        needs_review = (
            quality_report.completeness_score < 30.0
            or not quality_report.encoding_ok
            or len(warnings) > 3
        )
        status = "review_required" if needs_review else "ready_for_routing"
        final_state = "REVIEW_REQUIRED" if needs_review else "READY_FOR_ROUTING"
        self._record_state(ctx, "QUALITY_CHECKING", final_state)

        doc_meta = DocumentMeta(
            doc_id=f"DOC_{uuid4().hex[:8]}",
            title=title,
            author=input_dto.source_metadata.get("author", ""),
            word_count=len(normalized_text),
            chapter_count=structure.chapter_count,
            source_type=input_dto.input_source_type,
            project_id=input_dto.project_id or ctx.project_id,
        )

        ingestion_log.append(_make_log("completed", f"status={status}"))

        logger.info(
            f"[{self.skill_id}] completed | run={ctx.run_id} status={status} "
            f"lang={language_detection.primary_language} "
            f"segments={len(segments)} warnings={len(warnings)}"
        )

        return Skill01Output(
            version="1.0",
            status=status,
            document_meta=doc_meta,
            language_detection=language_detection,
            structure=structure,
            normalized_text=normalized_text,
            segments=segments,
            quality_report=quality_report,
            warnings=warnings,
            ingestion_log=ingestion_log,
            trace_id=ctx.trace_id,
            idempotency_key=ctx.idempotency_key,
        )

    # ── [I1] Source Precheck ───────────────────────────────────────────────────

    @staticmethod
    def _source_precheck(input_dto: Skill01Input) -> list[str]:
        issues: list[str] = []
        text = (input_dto.raw_text or "").strip()
        if not text:
            issues.append("raw_text is empty")
        elif len(text) < _MIN_TEXT_LENGTH:
            issues.append(
                f"raw_text too short ({len(text)} chars, minimum={_MIN_TEXT_LENGTH})"
            )
        if input_dto.input_source_type not in _VALID_SOURCE_TYPES:
            issues.append(
                f"invalid input_source_type: {input_dto.input_source_type!r}"
            )
        return issues

    # ── [I2] Text Normalization ────────────────────────────────────────────────

    @staticmethod
    def _normalize_text(
        raw: str,
        *,
        source_type: str = "text",
        preserve_html: bool = False,
    ) -> tuple[str, list[IngestionLogEntry]]:
        log: list[IngestionLogEntry] = []

        # CRLF → LF
        text = raw.replace("\r\n", "\n").replace("\r", "\n")
        if text != raw:
            log.append(_make_log("normalized_line_endings"))

        # Remove control chars and zero-width chars
        cleaned = _CONTROL_CHAR_RE.sub("", text)
        removed = len(text) - len(cleaned)
        if removed:
            log.append(_make_log("removed_control_chars", f"count={removed}"))
        text = cleaned

        # HTML tag stripping for web_scrape (unless user wants to preserve)
        if source_type == "web_scrape" and not preserve_html:
            before_len = len(text)
            text = _HTML_TAG_RE.sub("", text)
            stripped = before_len - len(text)
            if stripped:
                log.append(_make_log("stripped_html_tags", f"chars_removed={stripped}"))

        # Markdown noise removal for web_scrape
        if source_type == "web_scrape":
            text = _MD_LINK_IMG_RE.sub(r"\1", text)
            text = _MD_LINK_RE.sub(r"\1", text)
            text = _MD_HEADING_RE.sub("", text)
            text = _MD_HR_RE.sub("", text)
            log.append(_make_log("removed_markdown_noise"))

        # Collapse 3+ consecutive blank lines to 2
        text = re.sub(r"\n{3,}", "\n\n", text)

        # Strip trailing whitespace per line
        text = "\n".join(ln.rstrip() for ln in text.split("\n")).strip()

        # NFC Unicode normalization
        text = unicodedata.normalize("NFC", text)
        log.append(_make_log("unicode_nfc_normalized"))

        return text, log

    # ── [I3] Structure Parsing ─────────────────────────────────────────────────

    @staticmethod
    def _parse_structure(
        text: str,
        *,
        enable_sentence_split: bool = False,
    ) -> tuple[DocumentStructure, list[Segment], str]:
        lines = text.split("\n")

        # Title: first non-empty line, only if concise (≤ 60 chars)
        first_line = next((ln.strip() for ln in lines if ln.strip()), "")
        title = first_line if 0 < len(first_line) <= 60 else ""
        has_title = bool(title)

        # Split into chapters (or treat whole text as one chapter)
        parts = _CHAPTER_PATTERN.split(text)
        chapters = [p.strip() for p in parts if p.strip()]
        if not chapters:
            chapters = [text.strip()]
        chapter_count = len(chapters)

        # Build paragraph-level segments
        segments: list[Segment] = []
        paragraph_count = 0
        search_offset = 0

        for ch_idx, chapter_text in enumerate(chapters):
            chapter_id = f"ch_{ch_idx + 1:03d}"
            raw_paras = re.split(r"\n\n+", chapter_text)
            paragraphs = [p.strip() for p in raw_paras if p.strip()]

            for para in paragraphs:
                paragraph_count += 1
                seg_type = (
                    "dialogue"
                    if para[:1] in ("「", "\u300c", '"', "\u201c")
                    else "paragraph"
                )
                pos = text.find(para, search_offset)
                start = max(pos, 0)
                end = start + len(para)
                search_offset = end

                segments.append(
                    Segment(
                        segment_id=f"seg_{uuid4().hex[:8]}",
                        chapter_id=chapter_id,
                        text=para,
                        start_offset=start,
                        end_offset=end,
                        segment_type=seg_type,
                    )
                )

                # Sentence splitting within paragraph when enabled
                if enable_sentence_split:
                    sentences = _SENTENCE_SPLIT_RE.split(para)
                    sentences = [s.strip() for s in sentences if s.strip()]
                    if len(sentences) > 1:
                        sent_offset = start
                        for sent in sentences:
                            s_pos = text.find(sent, sent_offset)
                            s_start = max(s_pos, 0)
                            s_end = s_start + len(sent)
                            sent_offset = s_end
                            segments.append(
                                Segment(
                                    segment_id=f"seg_{uuid4().hex[:8]}",
                                    chapter_id=chapter_id,
                                    text=sent,
                                    start_offset=s_start,
                                    end_offset=s_end,
                                    segment_type="sentence",
                                )
                            )

        structure = DocumentStructure(
            has_title=has_title,
            chapter_count=chapter_count,
            paragraph_count=paragraph_count,
            sentence_split_enabled=enable_sentence_split,
        )
        return structure, segments, title

    # ── [I4] Language Detection ────────────────────────────────────────────────

    @staticmethod
    def _detect_language(text: str) -> tuple[LanguageDetection, list[str]]:
        warnings: list[str] = []
        if not text:
            return LanguageDetection(primary_language="unknown", confidence=0.0, route_hint="unknown"), warnings

        # CJK Unified Ideographs (shared Chinese/Japanese/Korean glyphs)
        cjk_ratio = _char_ratio(text, [(0x4E00, 0x9FFF)])
        # Hiragana + Katakana
        jp_ratio = _char_ratio(text, [(0x3040, 0x30FF)])
        # Hangul syllables
        ko_ratio = _char_ratio(text, [(0xAC00, 0xD7A3)])
        # ASCII letters
        ascii_ratio = _char_ratio(text, [(0x41, 0x5A), (0x61, 0x7A)])

        secondary: list[str] = []
        mixed_languages: list[MixedLanguageInfo] = []
        route_parts: list[str] = []

        if ko_ratio > 0.15:
            primary = "ko"
            confidence = min(0.95, 0.5 + ko_ratio)
            route_parts.append("ko_primary")
            if ascii_ratio > 0.10:
                secondary.append("en-US")
                mixed_languages.append(MixedLanguageInfo(lang="en", ratio=round(ascii_ratio, 4)))
                route_parts.append("with_minor_en")
        elif jp_ratio > 0.05:
            primary = "ja"
            confidence = min(0.95, 0.5 + jp_ratio * 5)
            route_parts.append("ja_primary")
            if ascii_ratio > 0.10:
                secondary.append("en-US")
                mixed_languages.append(MixedLanguageInfo(lang="en", ratio=round(ascii_ratio, 4)))
                route_parts.append("with_minor_en")
        elif cjk_ratio > 0.20:
            primary = "zh-CN"
            confidence = min(0.98, 0.6 + cjk_ratio)
            route_parts.append("zh_primary")
            if ascii_ratio > 0.15:
                secondary.append("en-US")
                mixed_languages.append(MixedLanguageInfo(lang="en", ratio=round(ascii_ratio, 4)))
                warnings.append(f"mixed_language: en-US ratio={ascii_ratio:.2f}")
                route_parts.append("with_minor_en")
        elif ascii_ratio > 0.50:
            primary = "en-US"
            confidence = min(0.95, 0.5 + ascii_ratio * 0.5)
            route_parts.append("en_primary")
            if cjk_ratio > 0.05:
                secondary.append("zh-CN")
                mixed_languages.append(MixedLanguageInfo(lang="zh", ratio=round(cjk_ratio, 4)))
                warnings.append(f"mixed_language: zh-CN ratio={cjk_ratio:.2f}")
                route_parts.append("with_minor_zh")
        else:
            primary = "unknown"
            confidence = 0.3
            route_parts.append("unknown")
            warnings.append("language_detection_uncertain: insufficient signal")

        route_hint = "_".join(route_parts)

        return (
            LanguageDetection(
                primary_language=primary,
                confidence=round(confidence, 4),
                secondary_languages=secondary,
                mixed_languages=mixed_languages,
                route_hint=route_hint,
            ),
            warnings,
        )

    # ── Per-segment language tagging ───────────────────────────────────────────

    def _tag_segment_languages(self, segments: list[Segment]) -> list[Segment]:
        """Add per-segment language_tag, confidence, and mixed_language_info."""
        tagged: list[Segment] = []
        for seg in segments:
            lang_det, _ = self._detect_language(seg.text)
            tagged.append(seg.model_copy(update={
                "language_tag": lang_det.primary_language,
                "confidence": lang_det.confidence,
                "mixed_language_info": lang_det.mixed_languages,
            }))
        return tagged

    # ── [I5] Quality Report ────────────────────────────────────────────────────

    @staticmethod
    def _quality_check(
        text: str, segments: list[Segment]
    ) -> tuple[QualityReport, list[str]]:
        warnings: list[str] = []

        # Encoding: presence of Unicode replacement character signals garbled bytes
        encoding_ok = "\ufffd" not in text

        # Empty segments
        empty_count = sum(1 for s in segments if not s.text.strip())
        if empty_count:
            warnings.append(f"empty_segments: {empty_count}")

        # Duplicate paragraphs (only count paragraph-type segments)
        para_texts = [s.text for s in segments if s.segment_type != "sentence"]
        duplicates = len(para_texts) - len(set(para_texts))
        if duplicates:
            warnings.append(f"duplicate_paragraphs: {duplicates}")

        # Completeness score based on character count
        char_count = len(text)
        if char_count < 200:
            completeness = 10.0
            warnings.append("text_too_short_for_planning")
        elif char_count < 1_000:
            completeness = 50.0
        elif char_count < 5_000:
            completeness = 75.0
        else:
            completeness = 90.0

        # Penalise for duplicates and empty segments
        penalty = min(30.0, duplicates * 5.0 + empty_count * 2.0)
        completeness = max(0.0, completeness - penalty)

        if not encoding_ok:
            warnings.append("encoding_issues_detected")

        return (
            QualityReport(
                completeness_score=round(completeness, 2),
                encoding_ok=encoding_ok,
                warnings=warnings,
                length_chars=char_count,
                empty_paragraphs=empty_count,
                duplicate_paragraphs=duplicates,
                quality_score=round(completeness, 2),
            ),
            warnings,
        )
