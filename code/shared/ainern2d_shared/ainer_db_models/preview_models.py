from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base_model import Base, StandardColumnsMixin


class EntityInstanceLink(Base, StandardColumnsMixin):
	"""SKILL 21: persistent entity instance links across run/scene/shot."""

	__tablename__ = "entity_instance_links"
	__table_args__ = (
		UniqueConstraint(
			"tenant_id", "project_id", "entity_id", "run_id", "shot_id", "instance_key",
			name="uq_entity_instance_links_scope_inst",
		),
		Index("ix_entity_instance_links_scope_run", "tenant_id", "project_id", "run_id"),
		Index("ix_entity_instance_links_scope_entity", "tenant_id", "project_id", "entity_id"),
		Index("ix_entity_instance_links_scope_shot", "tenant_id", "project_id", "shot_id"),
	)

	entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), nullable=False)
	run_id: Mapped[str] = mapped_column(ForeignKey("render_runs.id", ondelete="CASCADE"), nullable=False)
	shot_id: Mapped[str | None] = mapped_column(ForeignKey("shots.id", ondelete="SET NULL"))
	scene_id: Mapped[str | None] = mapped_column(ForeignKey("scenes.id", ondelete="SET NULL"))
	instance_key: Mapped[str] = mapped_column(String(128), nullable=False)
	source_skill: Mapped[str] = mapped_column(String(32), nullable=False, default="skill_21")
	confidence: Mapped[float | None] = mapped_column(Float)
	meta_json: Mapped[dict | None] = mapped_column(JSONB)


class EntityContinuityProfile(Base, StandardColumnsMixin):
	"""SKILL 21: continuity anchors and lock state for each canonical entity."""

	__tablename__ = "entity_continuity_profiles"
	__table_args__ = (
		UniqueConstraint("tenant_id", "project_id", "entity_id", name="uq_entity_continuity_profiles_scope_entity"),
		Index("ix_entity_continuity_profiles_scope_status", "tenant_id", "project_id", "continuity_status"),
	)

	entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), nullable=False)
	continuity_status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
	anchors_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
	rules_json: Mapped[dict | None] = mapped_column(JSONB)
	locked_preview_variant_id: Mapped[str | None] = mapped_column(
		ForeignKey("entity_preview_variants.id", ondelete="SET NULL"),
	)
	last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
	meta_json: Mapped[dict | None] = mapped_column(JSONB)


class EntityPreviewVariant(Base, StandardColumnsMixin):
	"""Preview candidates generated for character/scene/prop multi-angle review."""

	__tablename__ = "entity_preview_variants"
	__table_args__ = (
		Index("ix_entity_preview_variants_scope_run", "tenant_id", "project_id", "run_id"),
		Index("ix_entity_preview_variants_scope_entity_status", "tenant_id", "project_id", "entity_id", "status"),
		Index("ix_entity_preview_variants_scope_job", "tenant_id", "project_id", "dispatch_job_id"),
	)

	run_id: Mapped[str] = mapped_column(ForeignKey("render_runs.id", ondelete="CASCADE"), nullable=False)
	entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), nullable=False)
	shot_id: Mapped[str | None] = mapped_column(ForeignKey("shots.id", ondelete="SET NULL"))
	scene_id: Mapped[str | None] = mapped_column(ForeignKey("scenes.id", ondelete="SET NULL"))
	view_angle: Mapped[str] = mapped_column(String(64), nullable=False, default="front")
	generation_backend: Mapped[str] = mapped_column(String(64), nullable=False, default="comfyui")
	status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
	dispatch_job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
	artifact_id: Mapped[str | None] = mapped_column(ForeignKey("artifacts.id", ondelete="SET NULL"))
	prompt_text: Mapped[str | None] = mapped_column(Text)
	negative_prompt_text: Mapped[str | None] = mapped_column(Text)
	regenerate_from_variant_id: Mapped[str | None] = mapped_column(String(64))
	score: Mapped[float | None] = mapped_column(Float)
	review_note: Mapped[str | None] = mapped_column(Text)
	meta_json: Mapped[dict | None] = mapped_column(JSONB)


class CharacterVoiceBinding(Base, StandardColumnsMixin):
	"""Stable voice bindings per character entity."""

	__tablename__ = "character_voice_bindings"
	__table_args__ = (
		UniqueConstraint("tenant_id", "project_id", "entity_id", "language_code", name="uq_character_voice_bindings_scope_lang"),
		Index("ix_character_voice_bindings_scope_voice", "tenant_id", "project_id", "voice_id"),
	)

	entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), nullable=False)
	language_code: Mapped[str] = mapped_column(String(16), nullable=False, default="zh-CN")
	voice_id: Mapped[str] = mapped_column(String(128), nullable=False)
	tts_model: Mapped[str] = mapped_column(String(64), nullable=False, default="tts-1")
	provider: Mapped[str] = mapped_column(String(64), nullable=False, default="openai")
	locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
	sample_audio_artifact_id: Mapped[str | None] = mapped_column(ForeignKey("artifacts.id", ondelete="SET NULL"))
	notes: Mapped[str | None] = mapped_column(Text)
	meta_json: Mapped[dict | None] = mapped_column(JSONB)


class PersonaDatasetBinding(Base, StandardColumnsMixin):
	"""SKILL 22: dataset bindings for persona runtime assembly."""

	__tablename__ = "persona_dataset_bindings"
	__table_args__ = (
		UniqueConstraint(
			"tenant_id", "project_id", "persona_pack_version_id", "collection_id",
			name="uq_persona_dataset_bindings_scope_pair",
		),
		Index("ix_persona_dataset_bindings_scope_persona", "tenant_id", "project_id", "persona_pack_version_id"),
		Index("ix_persona_dataset_bindings_scope_collection", "tenant_id", "project_id", "collection_id"),
	)

	persona_pack_version_id: Mapped[str] = mapped_column(
		ForeignKey("persona_pack_versions.id", ondelete="CASCADE"),
		nullable=False,
	)
	collection_id: Mapped[str] = mapped_column(ForeignKey("rag_collections.id", ondelete="CASCADE"), nullable=False)
	binding_role: Mapped[str] = mapped_column(String(32), nullable=False, default="primary")
	weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
	meta_json: Mapped[dict | None] = mapped_column(JSONB)


class PersonaIndexBinding(Base, StandardColumnsMixin):
	"""SKILL 22: index bindings (kb versions) for persona runtime assembly."""

	__tablename__ = "persona_index_bindings"
	__table_args__ = (
		UniqueConstraint(
			"tenant_id", "project_id", "persona_pack_version_id", "kb_version_id",
			name="uq_persona_index_bindings_scope_pair",
		),
		Index("ix_persona_index_bindings_scope_persona", "tenant_id", "project_id", "persona_pack_version_id"),
		Index("ix_persona_index_bindings_scope_kb", "tenant_id", "project_id", "kb_version_id"),
	)

	persona_pack_version_id: Mapped[str] = mapped_column(
		ForeignKey("persona_pack_versions.id", ondelete="CASCADE"),
		nullable=False,
	)
	kb_version_id: Mapped[str] = mapped_column(ForeignKey("kb_versions.id", ondelete="CASCADE"), nullable=False)
	priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
	retrieval_policy_json: Mapped[dict | None] = mapped_column(JSONB)


class PersonaLineageEdge(Base, StandardColumnsMixin):
	"""SKILL 22: lineage graph edges for upgrade/branch relationships."""

	__tablename__ = "persona_lineage_edges"
	__table_args__ = (
		UniqueConstraint(
			"tenant_id", "project_id", "source_persona_pack_version_id", "target_persona_pack_version_id", "edge_type",
			name="uq_persona_lineage_edges_scope_edge",
		),
		Index("ix_persona_lineage_edges_scope_source", "tenant_id", "project_id", "source_persona_pack_version_id"),
		Index("ix_persona_lineage_edges_scope_target", "tenant_id", "project_id", "target_persona_pack_version_id"),
	)

	source_persona_pack_version_id: Mapped[str] = mapped_column(
		ForeignKey("persona_pack_versions.id", ondelete="CASCADE"),
		nullable=False,
	)
	target_persona_pack_version_id: Mapped[str] = mapped_column(
		ForeignKey("persona_pack_versions.id", ondelete="CASCADE"),
		nullable=False,
	)
	edge_type: Mapped[str] = mapped_column(String(32), nullable=False, default="upgrade")
	reason: Mapped[str | None] = mapped_column(Text)
	meta_json: Mapped[dict | None] = mapped_column(JSONB)


class PersonaRuntimeManifest(Base, StandardColumnsMixin):
	"""SKILL 22: concrete runtime manifest resolved per run/persona."""

	__tablename__ = "persona_runtime_manifests"
	__table_args__ = (
		UniqueConstraint(
			"tenant_id", "project_id", "run_id", "persona_pack_version_id",
			name="uq_persona_runtime_manifests_scope_run_persona",
		),
		Index("ix_persona_runtime_manifests_scope_run", "tenant_id", "project_id", "run_id"),
		Index("ix_persona_runtime_manifests_scope_persona", "tenant_id", "project_id", "persona_pack_version_id"),
	)

	run_id: Mapped[str] = mapped_column(ForeignKey("render_runs.id", ondelete="CASCADE"), nullable=False)
	persona_pack_version_id: Mapped[str | None] = mapped_column(
		ForeignKey("persona_pack_versions.id", ondelete="SET NULL"),
	)
	resolved_dataset_ids_json: Mapped[list | None] = mapped_column(JSONB)
	resolved_index_ids_json: Mapped[list | None] = mapped_column(JSONB)
	runtime_manifest_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
	preview_query: Mapped[str | None] = mapped_column(Text)
	preview_topk: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
	preview_result_json: Mapped[dict | None] = mapped_column(JSONB)
