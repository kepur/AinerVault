"""SKILL 01: Story Ingestion & Normalization — Input/Output DTOs."""
from __future__ import annotations
from typing import Optional
from ainern2d_shared.schemas.base import BaseSchema


class DocumentMeta(BaseSchema):
    title: str = ""
    author: str = ""
    word_count: int = 0
    chapter_count: int = 0
    source_type: str = "text"  # text | url | ocr | epub


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
    document_meta: DocumentMeta
    language_detection: LanguageDetection
    segments: list[Segment] = []
    quality_report: QualityReport
    status: str = "ready_for_routing"
