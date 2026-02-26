"""SKILL 02: Language Context Router — Input/Output DTOs."""
from __future__ import annotations

from typing import Optional

from ainern2d_shared.schemas.base import BaseSchema


# ── Sub-objects ───────────────────────────────────────────────────────────────

class LanguageRoute(BaseSchema):
    source_primary_language: str = "zh-CN"
    target_output_language: str = "zh-CN"
    translation_required: bool = False
    bilingual_output: bool = False


class TranslationPlan(BaseSchema):
    mode: str = "none"  # none | full | partial | bilingual
    preserve_named_entities: bool = True
    source_lang: str = ""
    target_lang: str = ""


class CultureCandidate(BaseSchema):
    culture_pack_id: str
    confidence: float = 0.0
    reason_tags: list[str] = []


class KBQueryPlan(BaseSchema):
    must_queries: list[str] = []
    optional_queries: list[str] = []


class PlannerHints(BaseSchema):
    scene_planner_mode: str = "generic"
    shot_planner_bias: str = "neutral"
    culture_binding_hint: str = ""


class RetrievalFilters(BaseSchema):
    culture_pack: str = ""
    genre: str = ""
    era: str = ""
    style_mode: str = ""
    filter_strength: str = "soft_preference"  # hard_constraint | soft_preference


class RecipeContextSeed(BaseSchema):
    """Seed context for RAG Recipe assembly (§9 of spec)."""
    recipe_id: Optional[str] = None
    kb_version_id: Optional[str] = None
    culture_recipe_hint: str = ""


# ── Input / Output ────────────────────────────────────────────────────────────

class Skill02Input(BaseSchema):
    # From SKILL 01 output
    primary_language: str = "zh-CN"
    secondary_languages: list[str] = []
    normalized_text: str = ""
    quality_status: str = "ready_for_routing"
    # User / project context
    target_output_language: str = ""
    genre: str = ""
    story_world_setting: str = ""  # realistic | historical | fantasy | scifi | modern
    target_locale: str = ""
    user_overrides: dict = {}
    project_defaults: dict = {}
    feature_flags: dict = {}


class Skill02Output(BaseSchema):
    version: str = "1.0"
    language_route: LanguageRoute = LanguageRoute()
    translation_plan: TranslationPlan = TranslationPlan()
    culture_candidates: list[CultureCandidate] = []
    kb_query_plan: KBQueryPlan = KBQueryPlan()
    planner_hints: PlannerHints = PlannerHints()
    retrieval_filters: RetrievalFilters = RetrievalFilters()
    recipe_context_seed: RecipeContextSeed = RecipeContextSeed()
    kb_version_id: Optional[str] = None
    warnings: list[str] = []
    review_required_items: list[str] = []
    status: str = "ready_for_planning"
