"""SKILL 01: Story Ingestion & Normalization — Input/Output DTOs."""
from __future__ import annotations

from typing import Optional

from ainern2d_shared.schemas.base import BaseSchema


class MixedLanguageInfo(BaseSchema):
    """Individual mixed-language entry (lang + ratio)."""
    lang: str
    ratio: float = 0.0


class IngestionOptions(BaseSchema):
    """Ingestion configuration options."""
    preserve_html_tags: bool = False
    preserve_footnotes: bool = False
    strict_mode: bool = False
    enable_sentence_split: bool = False


class IngestionLogEntry(BaseSchema):
    """Structured ingestion log entry with timestamp."""
    action: str
    detail: str = ""
    timestamp: str = ""


class DocumentMeta(BaseSchema):
    doc_id: str = ""
    title: str = ""
    author: str = ""
    word_count: int = 0
    chapter_count: int = 0
    source_type: str = "text"  # text | manual_text | web_scrape | file_upload | ocr_text | api_payload
    project_id: str = ""


class DocumentStructure(BaseSchema):
    has_title: bool = False
    chapter_count: int = 1
    paragraph_count: int = 0
    sentence_split_enabled: bool = False


class LanguageDetection(BaseSchema):
    primary_language: str = "zh-CN"
    confidence: float = 0.0
    secondary_languages: list[str] = []
    mixed_languages: list[MixedLanguageInfo] = []
    route_hint: str = ""


class Segment(BaseSchema):
    segment_id: str
    chapter_id: str
    text: str
    start_offset: int = 0
    end_offset: int = 0
    segment_type: str = "paragraph"  # paragraph | dialogue | narration | description | sentence
    language_tag: str = ""
    confidence: float = 0.0
    mixed_language_info: list[MixedLanguageInfo] = []


class QualityReport(BaseSchema):
    completeness_score: float = 0.0
    encoding_ok: bool = True
    warnings: list[str] = []
    length_chars: int = 0
    empty_paragraphs: int = 0
    duplicate_paragraphs: int = 0
    quality_score: float = 0.0


class Skill01Input(BaseSchema):
    raw_text: str
    input_source_type: str = "text"
    source_metadata: dict = {}
    feature_flags: dict = {}
    ingestion_options: Optional[IngestionOptions] = None
    user_context: dict = {}
    project_id: str = ""
    task_id: str = ""


class Skill01Output(BaseSchema):
    version: str = "1.0"
    status: str = "ready_for_routing"
    document_meta: DocumentMeta = DocumentMeta()
    language_detection: LanguageDetection = LanguageDetection()
    structure: DocumentStructure = DocumentStructure()
    normalized_text: str = ""
    segments: list[Segment] = []
    quality_report: QualityReport = QualityReport()
    warnings: list[str] = []
    ingestion_log: list[IngestionLogEntry] = []
    trace_id: str = ""
    idempotency_key: str = ""
