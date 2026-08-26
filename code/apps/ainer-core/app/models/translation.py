"""翻译层。

继承 v1 质量最高的那部分（术语表 / 候选审核 / 一致性告警），并做三处改动：
1. 语言从 project 提到 block 上（target_language_code），一个块可有多语言译文
2. TranslationProject 重对象拆成：novel 上的长期设置 + 每次跑的轻量 run
3. 术语命中记录进 glossary_hits_json，供审计与反向重译
"""
from __future__ import annotations

from enum import Enum

from sqlalchemy import (
    Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, StdMixin


class ConsistencyMode(str, Enum):
    strict = "strict"
    balanced = "balanced"
    free = "free"


class TranslationBlockStatus(str, Enum):
    draft = "draft"
    reviewed = "reviewed"
    locked = "locked"


class RunStatus(str, Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class TermStatus(str, Enum):
    draft = "draft"
    approved = "approved"
    archived = "archived"


class TermType(str, Enum):
    proper_noun = "proper_noun"
    artifact = "artifact"
    creature = "creature"
    place = "place"
    faction = "faction"
    technique = "technique"
    cultural = "cultural"
    other = "other"


class CandidateStatus(str, Enum):
    pending_review = "pending_review"
    approved = "approved"
    rejected = "rejected"
    merged = "merged"


class WarningType(str, Enum):
    name_drift = "name_drift"
    new_variant = "new_variant"
    cross_chapter = "cross_chapter"
    glossary_missing = "glossary_missing"
    glossary_drift = "glossary_drift"


class WarningStatus(str, Enum):
    open = "open"
    resolved = "resolved"
    ignored = "ignored"


class NovelTranslationSettings(Base, StdMixin):
    """翻译配置挂在书上，一次配置长期生效 —— 不再"必须先建翻译项目"。"""

    __tablename__ = "novel_translation_settings"
    __table_args__ = (
        UniqueConstraint("novel_id", "target_language_code", name="uq_nts_novel_lang"),
    )

    novel_id: Mapped[str] = mapped_column(
        ForeignKey("novels.id", ondelete="CASCADE"), nullable=False
    )
    target_language_code: Mapped[str] = mapped_column(String(16), nullable=False)
    consistency_mode: Mapped[ConsistencyMode] = mapped_column(
        default=ConsistencyMode.balanced, nullable=False
    )
    translatable_types: Mapped[list | None] = mapped_column(JSONB)
    style_prompt: Mapped[str | None] = mapped_column(Text)
    capability_route: Mapped[dict | None] = mapped_column(JSONB)
    batch_size: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    context_window: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class TranslationRun(Base, StdMixin):
    __tablename__ = "translation_runs"
    __table_args__ = (Index("ix_translation_runs_novel_status", "novel_id", "status"),)

    novel_id: Mapped[str] = mapped_column(
        ForeignKey("novels.id", ondelete="CASCADE"), nullable=False
    )
    target_language_code: Mapped[str] = mapped_column(String(16), nullable=False)
    transform_id: Mapped[str | None] = mapped_column(String(32), index=True)
    scope_json: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[RunStatus] = mapped_column(default=RunStatus.queued, nullable=False)
    progress: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    error_json: Mapped[dict | None] = mapped_column(JSONB)
    stats_json: Mapped[dict | None] = mapped_column(JSONB)


class TranslationBlock(Base, StdMixin):
    __tablename__ = "translation_blocks"
    __table_args__ = (
        UniqueConstraint("script_block_id", "target_language_code", name="uq_tb_block_lang"),
        Index("ix_translation_blocks_lang_status", "target_language_code", "status"),
    )

    script_block_id: Mapped[str] = mapped_column(
        ForeignKey("script_blocks.id", ondelete="CASCADE"), nullable=False
    )
    target_language_code: Mapped[str] = mapped_column(String(16), nullable=False)
    translated_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[TranslationBlockStatus] = mapped_column(
        default=TranslationBlockStatus.draft, nullable=False
    )
    locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    translation_notes: Mapped[str | None] = mapped_column(Text)
    glossary_hits_json: Mapped[list | None] = mapped_column(JSONB)
    lexicon_hits_json: Mapped[list | None] = mapped_column(JSONB)
    model_meta_json: Mapped[dict | None] = mapped_column(JSONB)
    run_id: Mapped[str | None] = mapped_column(String(32), index=True)


class GlossaryTerm(Base, StdMixin):
    __tablename__ = "glossary_terms"
    __table_args__ = (
        Index("ix_glossary_terms_scope", "novel_id", "target_language_code", "status"),
        Index("ix_glossary_terms_source", "source_term"),
    )

    novel_id: Mapped[str] = mapped_column(
        ForeignKey("novels.id", ondelete="CASCADE"), nullable=False
    )
    source_language_code: Mapped[str] = mapped_column(String(16), nullable=False)
    target_language_code: Mapped[str] = mapped_column(String(16), nullable=False)
    source_term: Mapped[str] = mapped_column(String(256), nullable=False)
    target_term: Mapped[str] = mapped_column(String(256), nullable=False)
    term_type: Mapped[TermType] = mapped_column(default=TermType.proper_noun, nullable=False)
    status: Mapped[TermStatus] = mapped_column(default=TermStatus.draft, nullable=False)
    aliases_json: Mapped[list | None] = mapped_column(JSONB)
    notes: Mapped[str | None] = mapped_column(Text)
    hit_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class GlossaryCandidate(Base, StdMixin):
    __tablename__ = "glossary_candidates"
    __table_args__ = (
        Index("ix_glossary_candidates_scope", "novel_id", "target_language_code", "status"),
    )

    novel_id: Mapped[str] = mapped_column(
        ForeignKey("novels.id", ondelete="CASCADE"), nullable=False
    )
    source_language_code: Mapped[str] = mapped_column(String(16), nullable=False)
    target_language_code: Mapped[str] = mapped_column(String(16), nullable=False)
    source_term: Mapped[str] = mapped_column(String(256), nullable=False)
    suggested_target_term: Mapped[str | None] = mapped_column(String(256))
    term_type: Mapped[TermType] = mapped_column(default=TermType.proper_noun, nullable=False)
    status: Mapped[CandidateStatus] = mapped_column(
        default=CandidateStatus.pending_review, nullable=False
    )
    confidence_score: Mapped[float | None] = mapped_column(Float)
    source_excerpt: Mapped[str | None] = mapped_column(Text)
    source_block_id: Mapped[str | None] = mapped_column(String(32))
    normalized_term: Mapped[str | None] = mapped_column(String(256))
    candidate_reason: Mapped[str | None] = mapped_column(Text)
    review_notes: Mapped[str | None] = mapped_column(Text)
    approved_term_id: Mapped[str | None] = mapped_column(String(32))


class ConsistencyWarning(Base, StdMixin):
    __tablename__ = "consistency_warnings"
    __table_args__ = (
        Index("ix_consistency_warnings_scope", "novel_id", "target_language_code", "status"),
    )

    novel_id: Mapped[str] = mapped_column(
        ForeignKey("novels.id", ondelete="CASCADE"), nullable=False
    )
    target_language_code: Mapped[str] = mapped_column(String(16), nullable=False)
    translation_block_id: Mapped[str | None] = mapped_column(String(32))
    warning_type: Mapped[WarningType] = mapped_column(nullable=False)
    source_name: Mapped[str] = mapped_column(String(256), nullable=False)
    detected_variant: Mapped[str] = mapped_column(String(256), nullable=False)
    expected_canonical: Mapped[str | None] = mapped_column(String(256))
    status: Mapped[WarningStatus] = mapped_column(default=WarningStatus.open, nullable=False)
