"""SKILL 33: Prompt Asset Library & Character Growth Continuity — ORM models.

Four tables:
  - semantic_assets       — structured semantic assets (costume/expression/action/prop/scene/mood_camera)
  - character_stage_profiles — character growth stages keyed by chapter range
  - shot_asset_bindings   — per-shot explicit binding of semantic assets + override
  - prompt_snapshots      — immutable prompt snapshots (distinct from PromptPlan)
"""
from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base_model import Base, StandardColumnsMixin


# ── Semantic Asset ─────────────────────────────────────────────────────────────

class SemanticAsset(Base, StandardColumnsMixin):
    """Structured semantic asset — costume / expression / action / prop / scene / mood_camera / prompt_template."""

    __tablename__ = "semantic_assets"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "project_id", "novel_id", "asset_type", "canonical_name",
            name="uq_semantic_assets_scope_type_name",
        ),
        Index("ix_semantic_assets_scope_novel", "tenant_id", "project_id", "novel_id"),
        Index("ix_semantic_assets_scope_entity", "tenant_id", "project_id", "entity_id"),
        Index("ix_semantic_assets_scope_type", "tenant_id", "project_id", "asset_type"),
    )

    novel_id: Mapped[str] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(ForeignKey("entities.id", ondelete="SET NULL"))
    asset_type: Mapped[str] = mapped_column(String(32), nullable=False)  # costume/expression/action/prop/scene/mood_camera/prompt_template
    canonical_name: Mapped[str] = mapped_column(String(256), nullable=False)
    aliases_json: Mapped[list | None] = mapped_column(JSONB)
    tags_json: Mapped[list | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")  # draft/active/archived
    structured_json: Mapped[dict | None] = mapped_column(JSONB)  # type-specific structured fields
    prompt_json: Mapped[dict | None] = mapped_column(JSONB)  # positive prompt fragments
    negative_prompt_json: Mapped[dict | None] = mapped_column(JSONB)  # negative prompt fragments
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    meta_json: Mapped[dict | None] = mapped_column(JSONB)


# ── Character Stage Profile ───────────────────────────────────────────────────

class CharacterStageProfile(Base, StandardColumnsMixin):
    """Character growth stage — appearance/temperament/costume changes by chapter range."""

    __tablename__ = "character_stage_profiles"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "project_id", "entity_id", "stage_name",
            name="uq_character_stage_profiles_scope_stage",
        ),
        Index("ix_character_stage_profiles_scope_entity", "tenant_id", "project_id", "entity_id"),
        Index("ix_character_stage_profiles_scope_novel", "tenant_id", "project_id", "novel_id"),
    )

    novel_id: Mapped[str] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), nullable=False)
    stage_name: Mapped[str] = mapped_column(String(128), nullable=False)
    chapter_start: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    chapter_end: Mapped[int | None] = mapped_column(Integer)
    appearance_override_json: Mapped[dict | None] = mapped_column(JSONB)  # overrides to visual appearance
    temperament_override_json: Mapped[dict | None] = mapped_column(JSONB)  # overrides to temperament
    default_costume_asset_id: Mapped[str | None] = mapped_column(ForeignKey("semantic_assets.id", ondelete="SET NULL"))
    default_prop_asset_ids_json: Mapped[list | None] = mapped_column(JSONB)  # [asset_id, ...]
    emotional_baseline_json: Mapped[dict | None] = mapped_column(JSONB)
    status_tags_json: Mapped[list | None] = mapped_column(JSONB)
    notes: Mapped[str | None] = mapped_column(Text)
    meta_json: Mapped[dict | None] = mapped_column(JSONB)


# ── Shot Asset Binding ─────────────────────────────────────────────────────────

class ShotAssetBinding(Base, StandardColumnsMixin):
    """Per-shot explicit binding of semantic assets + state override."""

    __tablename__ = "shot_asset_bindings"
    __table_args__ = (
        Index("ix_shot_asset_bindings_scope_shot", "tenant_id", "project_id", "shot_id"),
        Index("ix_shot_asset_bindings_scope_chapter", "tenant_id", "project_id", "chapter_id"),
        Index("ix_shot_asset_bindings_scope_entity", "tenant_id", "project_id", "entity_id"),
    )

    run_id: Mapped[str | None] = mapped_column(ForeignKey("render_runs.id", ondelete="SET NULL"))
    chapter_id: Mapped[str] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False)
    scene_id: Mapped[str | None] = mapped_column(ForeignKey("scenes.id", ondelete="SET NULL"))
    shot_id: Mapped[str] = mapped_column(ForeignKey("shots.id", ondelete="CASCADE"), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(ForeignKey("entities.id", ondelete="SET NULL"))
    binding_role: Mapped[str] = mapped_column(String(32), nullable=False, default="subject")  # subject/background/prop/scene/mood
    stage_profile_id: Mapped[str | None] = mapped_column(ForeignKey("character_stage_profiles.id", ondelete="SET NULL"))
    selected_asset_ids_json: Mapped[list | None] = mapped_column(JSONB)  # [asset_id, ...]
    state_override_json: Mapped[dict | None] = mapped_column(JSONB)  # dirt/scars/sweat/special_expression overrides
    prompt_snapshot_id: Mapped[str | None] = mapped_column(ForeignKey("prompt_snapshots.id", ondelete="SET NULL"))
    meta_json: Mapped[dict | None] = mapped_column(JSONB)


# ── Prompt Snapshot ────────────────────────────────────────────────────────────

class PromptSnapshot(Base, StandardColumnsMixin):
    """Immutable prompt snapshot — distinct from PromptPlan (planner output)."""

    __tablename__ = "prompt_snapshots"
    __table_args__ = (
        Index("ix_prompt_snapshots_scope_shot", "tenant_id", "project_id", "shot_id"),
        Index("ix_prompt_snapshots_scope_entity", "tenant_id", "project_id", "entity_id"),
        Index("ix_prompt_snapshots_scope_run", "tenant_id", "project_id", "run_id"),
        Index("ix_prompt_snapshots_scope_hash", "consistency_hash"),
    )

    run_id: Mapped[str | None] = mapped_column(ForeignKey("render_runs.id", ondelete="SET NULL"))
    chapter_id: Mapped[str] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False)
    scene_id: Mapped[str | None] = mapped_column(ForeignKey("scenes.id", ondelete="SET NULL"))
    shot_id: Mapped[str] = mapped_column(ForeignKey("shots.id", ondelete="CASCADE"), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(ForeignKey("entities.id", ondelete="SET NULL"))
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="auto")  # manual/auto/regenerate
    source_id: Mapped[str | None] = mapped_column(String(64))
    merged_prompt_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    merged_negative_prompt_text: Mapped[str | None] = mapped_column(Text)
    merged_json: Mapped[dict | None] = mapped_column(JSONB)  # layered JSON structure
    generation_params_json: Mapped[dict | None] = mapped_column(JSONB)
    consistency_hash: Mapped[str | None] = mapped_column(String(128))
    regenerate_parent_snapshot_id: Mapped[str | None] = mapped_column(
        ForeignKey("prompt_snapshots.id", ondelete="SET NULL"),
    )
    meta_json: Mapped[dict | None] = mapped_column(JSONB)
