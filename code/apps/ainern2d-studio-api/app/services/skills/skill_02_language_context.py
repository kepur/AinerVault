"""SKILL 02: LanguageContextService — 业务逻辑实现。
参考规格: SKILL_02_LANGUAGE_CONTEXT_ROUTER.md
状态: SERVICE_READY
"""
from __future__ import annotations

from typing import ClassVar

from loguru import logger
from sqlalchemy.orm import Session

from ainern2d_shared.schemas.skills.skill_02 import (
    CultureCandidate,
    KBQueryPlan,
    LanguageRoute,
    PlannerHints,
    RecipeContextSeed,
    RetrievalFilters,
    Skill02Input,
    Skill02Output,
    TranslationPlan,
)
from ainern2d_shared.services.base_skill import BaseSkillService, SkillContext

# ── Culture routing rule table ─────────────────────────────────────────────────
# Each rule: (lang_prefix, genre_keywords, world_keywords, pack_id, base_confidence, tags)
CultureRule = tuple[str, list[str], list[str], str, float, list[str]]

_CULTURE_RULES: list[CultureRule] = [
    ("zh", ["wuxia", "武侠", "martial", "jianghu", "江湖"],
     ["historical", "ancient", "传统"],
     "cn_wuxia", 0.91, ["genre_wuxia", "historical_style", "zh_primary"]),

    ("zh", ["xianxia", "仙侠", "cultivation", "immortal", "修仙", "修炼", "fantasy"],
     [],
     "cn_xianxia", 0.83, ["fantasy_cultivation", "zh_primary"]),

    ("zh", ["modern", "urban", "romance", "都市", "现代", "contemporary"],
     ["modern", "contemporary"],
     "cn_modern_urban", 0.80, ["modern_zh", "urban_style"]),

    ("ja", ["anime", "isekai", "school", "shounen", "shoujo", "slice_of_life"],
     [],
     "jp_anime", 0.85, ["jp_anime_style"]),

    ("ja", ["samurai", "historical", "jidaigeki"],
     ["historical"],
     "jp_historical", 0.82, ["jp_jidaigeki_style"]),

    ("ko", ["romance", "drama", "manhwa", "webtoon", "historical"],
     [],
     "kr_drama", 0.80, ["kr_drama_style"]),

    ("en", ["fantasy", "epic", "high_fantasy", "sword"],
     ["fantasy"],
     "en_western_fantasy", 0.78, ["en_western", "fantasy_epic"]),

    ("en", ["scifi", "sci-fi", "cyberpunk", "space"],
     ["scifi"],
     "en_scifi", 0.76, ["en_scifi_style"]),
]

# Generic fallback packs (lowest priority, always appended if nothing matches)
_GENERIC_FALLBACKS: dict[str, tuple[str, list[str]]] = {
    "zh": ("cn_generic", ["zh_generic_fallback"]),
    "ja": ("jp_generic", ["jp_generic_fallback"]),
    "ko": ("kr_generic", ["kr_generic_fallback"]),
    "en": ("en_generic", ["en_generic_fallback"]),
}

_VALID_STATUSES = {"ready_for_routing", "review_required"}


class LanguageContextService(BaseSkillService[Skill02Input, Skill02Output]):
    """SKILL 02 — Language Context Router.

    State machine:
      INIT → PRECHECKING → DECIDING_LANGUAGE_ROUTE → ROUTING_CULTURE_CANDIDATES
           → BUILDING_KB_QUERY_PLAN → EXPORTING_PLANNER_HINTS
           → READY_FOR_PLANNING | REVIEW_REQUIRED | FAILED
    """

    skill_id = "skill_02"
    skill_name = "LanguageContextService"

    # Extensible culture rules — append via register_culture_rule()
    _extra_culture_rules: ClassVar[list[CultureRule]] = []

    def __init__(self, db: Session) -> None:
        super().__init__(db)

    # ── Extension point for culture rules ──────────────────────────────────────

    @classmethod
    def register_culture_rule(
        cls,
        lang_prefix: str,
        genre_keywords: list[str],
        world_keywords: list[str],
        pack_id: str,
        base_confidence: float,
        tags: list[str],
    ) -> None:
        """Register an additional culture routing rule at runtime."""
        cls._extra_culture_rules.append(
            (lang_prefix, genre_keywords, world_keywords, pack_id, base_confidence, tags)
        )

    @classmethod
    def get_all_culture_rules(cls) -> list[CultureRule]:
        """Return built-in rules merged with dynamically registered rules."""
        return _CULTURE_RULES + cls._extra_culture_rules

    # ── Public entry ───────────────────────────────────────────────────────────

    def execute(self, input_dto: Skill02Input, ctx: SkillContext) -> Skill02Output:
        warnings: list[str] = []
        review_items: list[str] = []
        flags = input_dto.feature_flags or {}

        # ── [R1] Precheck ─────────────────────────────────────────────────────
        self._record_state(ctx, "INIT", "PRECHECKING")
        issues = self._precheck(input_dto)
        if issues:
            self._record_state(ctx, "PRECHECKING", "FAILED")
            raise ValueError(f"REQ-VALIDATION-001: {'; '.join(issues)}")

        src_lang = input_dto.primary_language or "unknown"
        tgt_lang = (
            input_dto.target_output_language
            or input_dto.project_defaults.get("default_language", src_lang)
        )
        genre = (input_dto.genre or "").lower()
        world = (input_dto.story_world_setting or "").lower()

        if not input_dto.target_output_language:
            warnings.append("target_output_language_not_set: defaulting to source language")

        if not genre:
            warnings.append("genre_not_provided: culture routing confidence reduced")
            review_items.append("genre_unknown")

        if not world:
            warnings.append("world_setting_not_provided: culture routing confidence reduced")

        # ── [R2] Language Route Decision ──────────────────────────────────────
        self._record_state(ctx, "PRECHECKING", "DECIDING_LANGUAGE_ROUTE")

        # feature_flag: enable_translation_route (default True)
        translation_enabled = flags.get("enable_translation_route", True)
        language_route, translation_plan = self._decide_language_route(
            src_lang, tgt_lang, input_dto, translation_enabled=translation_enabled,
        )

        # feature_flag: enable_multilingual_output_plan
        if flags.get("enable_multilingual_output_plan") and input_dto.secondary_languages:
            language_route.bilingual_output = True
            if translation_plan.mode == "none":
                translation_plan.mode = "bilingual"
            warnings.append(
                "multilingual_output_plan_enabled: secondary languages included"
            )

        # ── [R3] Culture Candidate Routing ────────────────────────────────────
        self._record_state(ctx, "DECIDING_LANGUAGE_ROUTE", "ROUTING_CULTURE_CANDIDATES")

        # feature_flag: enable_culture_candidate_export (default True)
        culture_export_enabled = flags.get("enable_culture_candidate_export", True)
        culture_candidates = self._route_culture_candidates(
            src_lang, genre, world, input_dto,
        )

        if not culture_export_enabled:
            culture_candidates = []
            warnings.append("culture_candidate_export_disabled_by_feature_flag")

        if not culture_candidates:
            warnings.append("no_culture_candidates_matched: generic fallback used")
            review_items.append("culture_candidate_uncertain")

        # ── [R4] KB Query Planning ────────────────────────────────────────────
        self._record_state(ctx, "ROUTING_CULTURE_CANDIDATES", "BUILDING_KB_QUERY_PLAN")
        kb_query_plan = self._build_kb_query_plan(culture_candidates, genre, language_route)

        # ── [R5] Planner Hints Export ─────────────────────────────────────────
        self._record_state(ctx, "BUILDING_KB_QUERY_PLAN", "EXPORTING_PLANNER_HINTS")
        planner_hints = self._export_planner_hints(culture_candidates, genre, world)
        retrieval_filters = self._build_retrieval_filters(
            culture_candidates, genre, world, language_route
        )

        # ── §9 Recipe Context Seed & KB version tracking ─────────────────────
        kb_version_id = input_dto.project_defaults.get("kb_version_id")
        recipe_context_seed = self._build_recipe_context_seed(
            culture_candidates, kb_version_id, ctx,
        )

        # ── Final status ──────────────────────────────────────────────────────
        needs_review = bool(review_items) or len(warnings) > 3
        status = "review_required" if needs_review else "ready_for_planning"
        final_state = "REVIEW_REQUIRED" if needs_review else "READY_FOR_PLANNING"
        self._record_state(ctx, "EXPORTING_PLANNER_HINTS", final_state)

        logger.info(
            f"[{self.skill_id}] completed | run={ctx.run_id} status={status} "
            f"src={src_lang} tgt={tgt_lang} candidates={len(culture_candidates)}"
        )

        return Skill02Output(
            version=ctx.schema_version,
            language_route=language_route,
            translation_plan=translation_plan,
            culture_candidates=culture_candidates,
            kb_query_plan=kb_query_plan,
            planner_hints=planner_hints,
            retrieval_filters=retrieval_filters,
            recipe_context_seed=recipe_context_seed,
            kb_version_id=kb_version_id,
            warnings=warnings,
            review_required_items=review_items,
            status=status,
        )

    # ── [R1] Precheck ──────────────────────────────────────────────────────────

    @staticmethod
    def _precheck(input_dto: Skill02Input) -> list[str]:
        issues: list[str] = []
        if input_dto.quality_status == "failed":
            issues.append(
                "upstream SKILL 01 status is 'failed'; cannot proceed with routing"
            )
        if not input_dto.primary_language:
            issues.append("primary_language is missing from SKILL 01 output")
        return issues

    # ── [R2] Language Route Decision ──────────────────────────────────────────

    @staticmethod
    def _decide_language_route(
        src_lang: str,
        tgt_lang: str,
        input_dto: Skill02Input,
        *,
        translation_enabled: bool = True,
    ) -> tuple[LanguageRoute, TranslationPlan]:
        translation_required = (
            _lang_prefix(src_lang) != _lang_prefix(tgt_lang) and translation_enabled
        )
        bilingual = bool(
            input_dto.user_overrides.get("bilingual_output")
            or input_dto.project_defaults.get("bilingual_output")
        )
        preserve_entities = bool(
            input_dto.user_overrides.get("preserve_named_entities", True)
        )

        if translation_required:
            mode = "bilingual" if bilingual else "full"
        elif bilingual:
            mode = "bilingual"
        else:
            mode = "none"

        return (
            LanguageRoute(
                source_primary_language=src_lang,
                target_output_language=tgt_lang,
                translation_required=translation_required,
                bilingual_output=bilingual,
            ),
            TranslationPlan(
                mode=mode,
                preserve_named_entities=preserve_entities,
                source_lang=src_lang,
                target_lang=tgt_lang,
            ),
        )

    # ── [R3] Culture Candidate Routing ─────────────────────────────────────────

    @classmethod
    def _route_culture_candidates(
        cls,
        src_lang: str,
        genre: str,
        world: str,
        input_dto: Skill02Input,
    ) -> list[CultureCandidate]:
        lang_prefix = _lang_prefix(src_lang)
        override_pack = input_dto.user_overrides.get("culture_pack")
        candidates: list[CultureCandidate] = []
        seen_packs: set[str] = set()

        # User override takes highest priority
        if override_pack:
            candidates.append(
                CultureCandidate(
                    culture_pack_id=override_pack,
                    confidence=1.0,
                    reason_tags=["user_override"],
                )
            )
            seen_packs.add(override_pack)

        # Rule-based matching (built-in + extensions)
        for rule_lang, genre_keys, world_keys, pack_id, base_conf, tags in cls.get_all_culture_rules():
            if pack_id in seen_packs:
                continue
            if not src_lang.startswith(rule_lang) and lang_prefix != rule_lang:
                continue

            genre_match = not genre_keys or any(k in genre for k in genre_keys)
            world_match = not world_keys or any(k in world for k in world_keys)

            if not genre_match:
                continue

            # Reduce confidence if world doesn't match
            conf = base_conf if world_match else round(base_conf * 0.65, 4)
            # Reduce further if genre was not provided
            if not genre:
                conf = round(conf * 0.6, 4)

            candidates.append(
                CultureCandidate(culture_pack_id=pack_id, confidence=conf, reason_tags=tags)
            )
            seen_packs.add(pack_id)

        # Generic fallback
        fallback = _GENERIC_FALLBACKS.get(lang_prefix)
        if fallback and fallback[0] not in seen_packs:
            candidates.append(
                CultureCandidate(
                    culture_pack_id=fallback[0],
                    confidence=0.40,
                    reason_tags=fallback[1],
                )
            )

        # Sort by confidence desc
        candidates.sort(key=lambda c: c.confidence, reverse=True)
        return candidates[:5]  # top 5 max

    # ── [R4] KB Query Planning ─────────────────────────────────────────────────

    @staticmethod
    def _build_kb_query_plan(
        candidates: list[CultureCandidate],
        genre: str,
        language_route: LanguageRoute,
    ) -> KBQueryPlan:
        must_queries: list[str] = []
        optional_queries: list[str] = []

        if candidates:
            top = candidates[0]
            must_queries.append(f"{top.culture_pack_id} visual style norms")
            must_queries.append(f"{top.culture_pack_id} naming and signage conventions")
            if genre:
                must_queries.append(f"{genre} narrative conventions")

        if language_route.translation_required:
            must_queries.append(
                f"translation style guide {language_route.source_primary_language}"
                f" to {language_route.target_output_language}"
            )

        for c in candidates[1:3]:
            optional_queries.append(f"{c.culture_pack_id} visual reference")

        optional_queries.append("character etiquette and gesture norms")

        return KBQueryPlan(must_queries=must_queries, optional_queries=optional_queries)

    # ── [R5] Planner Hints Export ──────────────────────────────────────────────

    @staticmethod
    def _export_planner_hints(
        candidates: list[CultureCandidate],
        genre: str,
        world: str,
    ) -> PlannerHints:
        top_pack = candidates[0].culture_pack_id if candidates else "generic"

        # Infer scene_planner_mode from top pack / genre
        if any(k in top_pack for k in ("wuxia", "xianxia", "anime")):
            scene_mode = "action_dialogue_mixed"
        elif any(k in top_pack for k in ("modern", "drama", "romance")):
            scene_mode = "dialogue_heavy"
        elif any(k in top_pack for k in ("scifi", "fantasy")):
            scene_mode = "world_building_heavy"
        else:
            scene_mode = "generic"

        shot_bias = f"{top_pack}_cinematic" if top_pack != "generic" else "neutral"

        return PlannerHints(
            scene_planner_mode=scene_mode,
            shot_planner_bias=shot_bias,
            culture_binding_hint=f"prefer_{top_pack}",
        )

    @staticmethod
    def _build_retrieval_filters(
        candidates: list[CultureCandidate],
        genre: str,
        world: str,
        language_route: LanguageRoute,
    ) -> RetrievalFilters:
        top_pack = candidates[0].culture_pack_id if candidates else ""
        top_conf = candidates[0].confidence if candidates else 0.0
        strength = "hard_constraint" if top_conf >= 0.85 else "soft_preference"

        return RetrievalFilters(
            culture_pack=top_pack,
            genre=genre,
            era=world,
            style_mode=genre or "generic",
            filter_strength=strength,
        )

    # ── §9 Recipe Context Seed ─────────────────────────────────────────────────

    @staticmethod
    def _build_recipe_context_seed(
        candidates: list[CultureCandidate],
        kb_version_id: str | None,
        ctx: SkillContext,
    ) -> RecipeContextSeed:
        """Build recipe context seed for downstream RAG Recipe assembly (§9)."""
        top_pack = candidates[0].culture_pack_id if candidates else "generic"
        # recipe_id derived from run context; consumers may override later
        recipe_id = f"recipe_{ctx.run_id}" if ctx.run_id else None

        return RecipeContextSeed(
            recipe_id=recipe_id,
            kb_version_id=kb_version_id,
            culture_recipe_hint=top_pack,
        )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _lang_prefix(lang: str) -> str:
    """Return the primary language prefix (e.g. 'zh' from 'zh-CN')."""
    return (lang or "").split("-")[0].split("_")[0].lower()
