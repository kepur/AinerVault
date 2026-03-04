from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
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
	script_json: Mapped[dict | None] = mapped_column(JSONB)       # scenes[]
	world_model_json: Mapped[dict | None] = mapped_column(JSONB)  # characters/locations/props/beats/style_hints
	# Persistence / versioning
	format_detect_json: Mapped[dict | None] = mapped_column(JSONB)
	script_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
	world_model_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
	script_run_id: Mapped[str | None] = mapped_column(String(64))
	world_model_run_id: Mapped[str | None] = mapped_column(String(64))
	script_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
	world_model_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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


# ── Entity Mapping ─────────────────────────────────────────────────────────────

class EntityMappingType(str, Enum):
	character = "character"
	location = "location"
	prop = "prop"
	style = "style"
	event = "event"


class EntityContinuityStatus(str, Enum):
	unbound = "unbound"
	candidate = "candidate"
	locked = "locked"
	drifted = "drifted"


class EntityMapping(Base, StandardColumnsMixin):
	__tablename__ = "entity_mappings"
	__table_args__ = (
		Index("ix_entity_mappings_novel", "novel_id"),
		Index("ix_entity_mappings_status", "continuity_status"),
	)

	novel_id: Mapped[str | None] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"))
	entity_type: Mapped[EntityMappingType | None] = mapped_column()
	canonical_name: Mapped[str] = mapped_column(String(256), nullable=False)
	source_language: Mapped[str] = mapped_column(String(16), default="zh-CN", nullable=False)
	translations_json: Mapped[dict | None] = mapped_column(JSONB)   # {lang: name}
	aliases_json: Mapped[list | None] = mapped_column(JSONB)        # []
	culture_tags_json: Mapped[list | None] = mapped_column(JSONB)   # []
	world_model_source: Mapped[str | None] = mapped_column(String(128))  # chapter_id or "manual"
	anchor_asset_id: Mapped[str | None] = mapped_column(String(128))
	continuity_status: Mapped[EntityContinuityStatus] = mapped_column(
		default=EntityContinuityStatus.unbound, nullable=False
	)
	notes: Mapped[str | None] = mapped_column(Text)
	# Name localization
	naming_policy: Mapped[str | None] = mapped_column(String(64))    # transliteration/literal/cultural_equivalent
	culture_profile_id: Mapped[str | None] = mapped_column(String(64))
	style_tags_json: Mapped[list | None] = mapped_column(JSONB)      # [rural, folksy, ...]
	rationale: Mapped[str | None] = mapped_column(Text)              # why this name was chosen
	localization_candidates_json: Mapped[list | None] = mapped_column(JSONB)  # [{name, policy, rationale}]
	drift_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
	locked_langs_json: Mapped[dict | None] = mapped_column(JSONB)    # {lang: bool}
	naming_policy_by_lang_json: Mapped[dict | None] = mapped_column(JSONB)  # {lang: policy}
	locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
	updated_by_ai: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


# ── Skill Run ──────────────────────────────────────────────────────────────────

class SkillRunStatus(str, Enum):
	queued = "queued"
	running = "running"
	succeeded = "succeeded"
	failed = "failed"


class SkillRun(Base, StandardColumnsMixin):
	"""LLM 调用运行记录 — 去重、成本统计、版本回溯。"""
	__tablename__ = "skill_runs"
	__table_args__ = (
		Index("ix_skill_runs_input_hash", "input_hash"),
		Index("ix_skill_runs_chapter", "chapter_id"),
		Index("ix_skill_runs_novel", "novel_id"),
	)

	skill_id: Mapped[str] = mapped_column(String(64), nullable=False)      # e.g. "novel_to_script"
	novel_id: Mapped[str | None] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"))
	chapter_id: Mapped[str | None] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"))
	input_hash: Mapped[str | None] = mapped_column(String(64))             # SHA256 of canonical input
	input_snapshot: Mapped[dict | None] = mapped_column(JSONB)             # debug: first 500 chars + params
	status: Mapped[SkillRunStatus] = mapped_column(default=SkillRunStatus.queued, nullable=False)
	output_json: Mapped[dict | None] = mapped_column(JSONB)
	raw_response: Mapped[str | None] = mapped_column(Text)
	token_usage: Mapped[dict | None] = mapped_column(JSONB)
	cost_estimate: Mapped[float | None] = mapped_column(Float)
	model_provider_id: Mapped[str | None] = mapped_column(String(64))
	model_name: Mapped[str | None] = mapped_column(String(128))
