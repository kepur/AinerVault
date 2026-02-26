"""SKILL 01: Story Ingestion & Normalization — Input/Output DTOs."""
from __future__ import annotations

from ainern2d_shared.schemas.base import BaseSchema


class DocumentMeta(BaseSchema):
    title: str = ""
    author: str = ""
    word_count: int = 0
    chapter_count: int = 0
    source_type: str = "text"  # text | manual_text | web_scrape | file_upload | ocr_text | api_payload


class DocumentStructure(BaseSchema):
    has_title: bool = False
    chapter_count: int = 1
    paragraph_count: int = 0
    sentence_split_enabled: bool = False


class LanguageDetection(BaseSchema):
    primary_language: str = "zh-CN"
    confidence: float = 0.0
    secondary_languages: list[str] = []


class Segment(BaseSchema):
    segment_id: str
    chapter_id: str
    text: str
    start_offset: int = 0
    end_offset: int = 0
    segment_type: str = "paragraph"  # paragraph | dialogue | narration | description


class QualityReport(BaseSchema):
    completeness_score: float = 0.0
    encoding_ok: bool = True
    warnings: list[str] = []


class Skill01Input(BaseSchema):
    raw_text: str
    input_source_type: str = "text"
    source_metadata: dict = {}
    feature_flags: dict = {}


class Skill01Output(BaseSchema):
    document_meta: DocumentMeta = DocumentMeta()
    language_detection: LanguageDetection = LanguageDetection()
    structure: DocumentStructure = DocumentStructure()
    normalized_text: str = ""
    segments: list[Segment] = []
    quality_report: QualityReport = QualityReport()
    warnings: list[str] = []
    ingestion_log: list[str] = []
    status: str = "ready_for_routing"
