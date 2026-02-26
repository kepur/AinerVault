from __future__ import annotations

from sqlalchemy import Float, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base_model import Base, StandardColumnsMixin
from .enum_models import EntityType


class Entity(Base, StandardColumnsMixin):
	__tablename__ = "entities"
	__table_args__ = (
		UniqueConstraint("tenant_id", "project_id", "type", "label", name="uq_entities_scope_type_label"),
		Index("ix_entities_scope_type", "tenant_id", "project_id", "type"),
	)

	novel_id: Mapped[str] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
	type: Mapped[EntityType] = mapped_column(nullable=False)
	label: Mapped[str] = mapped_column(String(256), nullable=False)
	canonical_label: Mapped[str | None] = mapped_column(String(256))
	anchor_prompt: Mapped[str | None] = mapped_column(Text)
	traits_json: Mapped[dict | None] = mapped_column(JSONB)


class EntityAlias(Base, StandardColumnsMixin):
	__tablename__ = "entity_aliases"
	__table_args__ = (
		UniqueConstraint("tenant_id", "project_id", "entity_id", "alias", name="uq_entity_aliases_scope_alias"),
		Index("ix_entity_aliases_scope_entity", "tenant_id", "project_id", "entity_id"),
	)

	entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), nullable=False)
	alias: Mapped[str] = mapped_column(String(256), nullable=False)
	locale: Mapped[str | None] = mapped_column(String(16))


class EntityCanonicalization(Base, StandardColumnsMixin):
	__tablename__ = "entity_canonicalizations"
	__table_args__ = (
		UniqueConstraint("tenant_id", "project_id", "entity_id", "version", name="uq_entity_canonicalizations_scope_entity_ver"),
		Index("ix_entity_canonicalizations_scope_entity", "tenant_id", "project_id", "entity_id"),
	)

	entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), nullable=False)
	canonical_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
	binding_rule_json: Mapped[dict | None] = mapped_column(JSONB)


class CulturalBinding(Base, StandardColumnsMixin):
	__tablename__ = "cultural_bindings"
	__table_args__ = (
		Index("ix_cultural_bindings_scope_entity", "tenant_id", "project_id", "entity_id"),
		Index("ix_cultural_bindings_scope_locale", "tenant_id", "project_id", "locale"),
	)

	entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), nullable=False)
	locale: Mapped[str] = mapped_column(String(16), nullable=False)
	binding_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
	safety_tags_json: Mapped[list | None] = mapped_column(JSONB)


class Relationship(Base, StandardColumnsMixin):
	__tablename__ = "relationships"
	__table_args__ = (Index("ix_relationships_scope_subject", "tenant_id", "project_id", "subject_entity_id"),)

	subject_entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), nullable=False)
	object_entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), nullable=False)
	relation: Mapped[str] = mapped_column(String(128), nullable=False)
	confidence: Mapped[float | None] = mapped_column(Float)


class StoryEvent(Base, StandardColumnsMixin):
	__tablename__ = "story_events"
	__table_args__ = (
		UniqueConstraint("tenant_id", "project_id", "chapter_id", "event_no", name="uq_story_events_scope_no"),
		Index("ix_story_events_scope_chapter", "tenant_id", "project_id", "chapter_id"),
	)

	chapter_id: Mapped[str] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False)
	event_no: Mapped[int] = mapped_column(nullable=False)
	summary: Mapped[str] = mapped_column(Text, nullable=False)
	structured_json: Mapped[dict | None] = mapped_column(JSONB)


class EntityState(Base, StandardColumnsMixin):
	__tablename__ = "entity_states"
	__table_args__ = (
		Index("ix_entity_states_scope_entity", "tenant_id", "project_id", "entity_id"),
		Index("ix_entity_states_scope_chapter", "tenant_id", "project_id", "chapter_id"),
	)

	entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), nullable=False)
	chapter_id: Mapped[str] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False)
	state_json: Mapped[dict] = mapped_column(JSONB, nullable=False)


class AssetCandidate(Base, StandardColumnsMixin):
	__tablename__ = "asset_candidates"
	__table_args__ = (Index("ix_asset_candidates_scope_entity", "tenant_id", "project_id", "entity_id"),)

	entity_id: Mapped[str | None] = mapped_column(ForeignKey("entities.id", ondelete="SET NULL"))
	shot_id: Mapped[str | None] = mapped_column(ForeignKey("shots.id", ondelete="SET NULL"))
	asset_uri: Mapped[str] = mapped_column(String(1024), nullable=False)
	score: Mapped[float] = mapped_column(Float, nullable=False)
	source: Mapped[str] = mapped_column(String(64), nullable=False)
	meta_json: Mapped[dict | None] = mapped_column(JSONB)
