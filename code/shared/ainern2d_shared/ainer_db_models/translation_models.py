from __future__ import annotations

from enum import Enum

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base_model import Base, StandardColumnsMixin


# ── Enums ──────────────────────────────────────────────────────────────────────

class TranslationProjectStatus(str, Enum):
    draft = "draft"
    in_progress = "in_progress"
    completed = "completed"
    archived = "archived"


class ConsistencyMode(str, Enum):
    strict = "strict"
    balanced = "balanced"
    free = "free"


class BlockType(str, Enum):
    narration = "narration"
    dialogue = "dialogue"
    action = "action"
    heading = "heading"
    scene_break = "scene_break"


class TranslationBlockStatus(str, Enum):
    draft = "draft"
    reviewed = "reviewed"
    locked = "locked"


class WarningType(str, Enum):
    name_drift = "name_drift"
    new_variant = "new_variant"
    cross_chapter = "cross_chapter"


class WarningStatus(str, Enum):
    open = "open"
    resolved = "resolved"
    ignored = "ignored"


# ── Models ─────────────────────────────────────────────────────────────────────

class TranslationProject(Base, StandardColumnsMixin):
    __tablename__ = "translation_projects"
    __table_args__ = (
        Index("ix_tp_novel", "novel_id"),
        Index("ix_tp_scope", "tenant_id", "project_id"),
    )

    novel_id: Mapped[str] = mapped_column(
        ForeignKey("novels.id", ondelete="CASCADE"), nullable=False
    )
    source_language_code: Mapped[str] = mapped_column(String(16), nullable=False)
    target_language_code: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[TranslationProjectStatus] = mapped_column(
        default=TranslationProjectStatus.draft, nullable=False
    )
    model_provider_id: Mapped[str | None] = mapped_column(String(128))
    consistency_mode: Mapped[ConsistencyMode] = mapped_column(
        default=ConsistencyMode.balanced, nullable=False
    )
    term_dictionary_json: Mapped[dict | None] = mapped_column(JSONB)
    stats_json: Mapped[dict | None] = mapped_column(JSONB)


class ScriptBlock(Base, StandardColumnsMixin):
    __tablename__ = "script_blocks"
    __table_args__ = (
        Index("ix_sb_project_chapter", "translation_project_id", "chapter_id"),
        Index("ix_sb_project_seq", "translation_project_id", "seq_no"),
    )

    translation_project_id: Mapped[str] = mapped_column(
        ForeignKey("translation_projects.id", ondelete="CASCADE"), nullable=False
    )
    chapter_id: Mapped[str] = mapped_column(
        ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False
    )
    seq_no: Mapped[int] = mapped_column(Integer, nullable=False)
    block_type: Mapped[BlockType] = mapped_column(
        default=BlockType.narration, nullable=False
    )
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    speaker_tag: Mapped[str | None] = mapped_column(String(128))


class TranslationBlock(Base, StandardColumnsMixin):
    __tablename__ = "translation_blocks"
    __table_args__ = (
        Index("ix_tb_script_block", "script_block_id"),
        Index("ix_tb_project", "translation_project_id"),
    )

    script_block_id: Mapped[str] = mapped_column(
        ForeignKey("script_blocks.id", ondelete="CASCADE"), nullable=False
    )
    translation_project_id: Mapped[str] = mapped_column(
        ForeignKey("translation_projects.id", ondelete="CASCADE"), nullable=False
    )
    translated_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[TranslationBlockStatus] = mapped_column(
        default=TranslationBlockStatus.draft, nullable=False
    )
    translation_notes: Mapped[str | None] = mapped_column(Text)
    model_provider_id: Mapped[str | None] = mapped_column(String(128))


class EntityNameVariant(Base, StandardColumnsMixin):
    __tablename__ = "entity_name_variants"
    __table_args__ = (
        Index("ix_env_project", "translation_project_id"),
    )

    translation_project_id: Mapped[str] = mapped_column(
        ForeignKey("translation_projects.id", ondelete="CASCADE"), nullable=False
    )
    entity_id: Mapped[str | None] = mapped_column(String(128))
    source_name: Mapped[str] = mapped_column(String(256), nullable=False)
    canonical_target_name: Mapped[str] = mapped_column(String(256), nullable=False)
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    aliases_json: Mapped[list | None] = mapped_column(JSONB)


class ConsistencyWarning(Base, StandardColumnsMixin):
    __tablename__ = "consistency_warnings"
    __table_args__ = (
        Index("ix_cw_project", "translation_project_id"),
        Index("ix_cw_status", "status"),
    )

    translation_project_id: Mapped[str] = mapped_column(
        ForeignKey("translation_projects.id", ondelete="CASCADE"), nullable=False
    )
    translation_block_id: Mapped[str | None] = mapped_column(
        ForeignKey("translation_blocks.id", ondelete="SET NULL")
    )
    warning_type: Mapped[WarningType] = mapped_column(nullable=False)
    source_name: Mapped[str] = mapped_column(String(256), nullable=False)
    detected_variant: Mapped[str] = mapped_column(String(256), nullable=False)
    expected_canonical: Mapped[str | None] = mapped_column(String(256))
    status: Mapped[WarningStatus] = mapped_column(
        default=WarningStatus.open, nullable=False
    )
