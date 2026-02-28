from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base_model import Base, StandardColumnsMixin
from .enum_models import ArtifactType, AudioItemType, RunStatus


class Novel(Base, StandardColumnsMixin):
	__tablename__ = "novels"
	__table_args__ = (
		UniqueConstraint("tenant_id", "project_id", "title", name="uq_novels_scope_title"),
		Index("ix_novels_scope_created", "tenant_id", "project_id", "created_at"),
	)

	title: Mapped[str] = mapped_column(String(256), nullable=False)
	summary: Mapped[str | None] = mapped_column(Text)
	default_language_code: Mapped[str] = mapped_column(String(16), default="zh", nullable=False)
	team_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class Chapter(Base, StandardColumnsMixin):
	__tablename__ = "chapters"
	__table_args__ = (
		UniqueConstraint("tenant_id", "project_id", "novel_id", "chapter_no", "language_code", name="uq_chapters_scope_no_lang"),
		Index("ix_chapters_scope_novel", "tenant_id", "project_id", "novel_id"),
	)

	novel_id: Mapped[str] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
	chapter_no: Mapped[int] = mapped_column(Integer, nullable=False)
	language_code: Mapped[str] = mapped_column(String(16), default="zh", nullable=False)
	title: Mapped[str | None] = mapped_column(String(256))
	raw_text: Mapped[str] = mapped_column(Text, nullable=False)
	cleaned_text: Mapped[str | None] = mapped_column(Text)
	structured_json: Mapped[dict | None] = mapped_column(JSONB)


class Scene(Base, StandardColumnsMixin):
	__tablename__ = "scenes"
	__table_args__ = (
		UniqueConstraint("tenant_id", "project_id", "novel_id", "label", name="uq_scenes_scope_label"),
		Index("ix_scenes_scope_novel", "tenant_id", "project_id", "novel_id"),
	)

	novel_id: Mapped[str] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
	label: Mapped[str] = mapped_column(String(256), nullable=False)
	description: Mapped[str | None] = mapped_column(Text)


class Shot(Base, StandardColumnsMixin):
	__tablename__ = "shots"
	__table_args__ = (
		UniqueConstraint("tenant_id", "project_id", "chapter_id", "shot_no", name="uq_shots_scope_no"),
		Index("ix_shots_scope_chapter", "tenant_id", "project_id", "chapter_id"),
	)

	chapter_id: Mapped[str] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False)
	scene_id: Mapped[str | None] = mapped_column(ForeignKey("scenes.id", ondelete="SET NULL"))
	shot_no: Mapped[int] = mapped_column(Integer, nullable=False)
	duration_ms: Mapped[int | None] = mapped_column(Integer)
	status: Mapped[RunStatus] = mapped_column(default=RunStatus.queued, nullable=False)
	prompt_json: Mapped[dict | None] = mapped_column(JSONB)
	render_constraint_json: Mapped[dict | None] = mapped_column(JSONB)


class Dialogue(Base, StandardColumnsMixin):
	__tablename__ = "dialogues"
	__table_args__ = (
		UniqueConstraint("tenant_id", "project_id", "chapter_id", "line_no", name="uq_dialogues_scope_line"),
		Index("ix_dialogues_scope_chapter", "tenant_id", "project_id", "chapter_id"),
	)

	chapter_id: Mapped[str] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False)
	line_no: Mapped[int] = mapped_column(Integer, nullable=False)
	speaker: Mapped[str | None] = mapped_column(String(128))
	content: Mapped[str] = mapped_column(Text, nullable=False)
	emotion_hint: Mapped[str | None] = mapped_column(String(64))
	timing_hint_ms: Mapped[int | None] = mapped_column(Integer)


class PromptPlan(Base, StandardColumnsMixin):
	__tablename__ = "prompt_plans"
	__table_args__ = (
		UniqueConstraint("tenant_id", "project_id", "run_id", "shot_id", name="uq_prompt_plans_scope_run_shot"),
		Index("ix_prompt_plans_scope_run", "tenant_id", "project_id", "run_id"),
	)

	run_id: Mapped[str] = mapped_column(ForeignKey("render_runs.id", ondelete="CASCADE"), nullable=False)
	shot_id: Mapped[str] = mapped_column(ForeignKey("shots.id", ondelete="CASCADE"), nullable=False)
	prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
	negative_prompt_text: Mapped[str | None] = mapped_column(Text)
	model_hint_json: Mapped[dict | None] = mapped_column(JSONB)


class TimelineSegment(Base, StandardColumnsMixin):
	__tablename__ = "timeline_segments"
	__table_args__ = (
		Index("ix_timeline_segments_scope_run", "tenant_id", "project_id", "run_id"),
		Index("ix_timeline_segments_scope_shot", "tenant_id", "project_id", "shot_id"),
	)

	run_id: Mapped[str] = mapped_column(ForeignKey("render_runs.id", ondelete="CASCADE"), nullable=False)
	shot_id: Mapped[str | None] = mapped_column(ForeignKey("shots.id", ondelete="SET NULL"))
	track: Mapped[str] = mapped_column(String(32), nullable=False)
	start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
	end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
	artifact_id: Mapped[str | None] = mapped_column(ForeignKey("artifacts.id", ondelete="SET NULL"))
	meta_json: Mapped[dict | None] = mapped_column(JSONB)


class AudioTimelineItem(Base, StandardColumnsMixin):
	__tablename__ = "audio_timeline_items"
	__table_args__ = (
		Index("ix_audio_items_scope_chapter", "tenant_id", "project_id", "chapter_id"),
		Index("ix_audio_items_scope_track", "tenant_id", "project_id", "track_no"),
	)

	chapter_id: Mapped[str] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False)
	type: Mapped[AudioItemType] = mapped_column(nullable=False)
	track_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
	start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
	end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
	artifact_id: Mapped[str | None] = mapped_column(ForeignKey("artifacts.id", ondelete="SET NULL"))
	meta_json: Mapped[dict | None] = mapped_column(JSONB)


class Artifact(Base, StandardColumnsMixin):
	__tablename__ = "artifacts"
	__table_args__ = (
		Index("ix_artifacts_scope_run", "tenant_id", "project_id", "run_id"),
		Index("ix_artifacts_scope_type", "tenant_id", "project_id", "type"),
	)

	run_id: Mapped[str | None] = mapped_column(ForeignKey("render_runs.id", ondelete="CASCADE"))
	shot_id: Mapped[str | None] = mapped_column(ForeignKey("shots.id", ondelete="SET NULL"))
	type: Mapped[ArtifactType] = mapped_column(nullable=False)
	uri: Mapped[str] = mapped_column(String(1024), nullable=False)
	checksum: Mapped[str | None] = mapped_column(String(128))
	size_bytes: Mapped[int | None] = mapped_column(Integer)
	media_meta_json: Mapped[dict | None] = mapped_column(JSONB)
