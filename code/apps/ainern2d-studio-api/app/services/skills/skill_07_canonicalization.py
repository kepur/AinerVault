"""SKILL 07: CanonicalizationService — 业务逻辑实现。
参考规格: SKILL_07_ENTITY_CANONICALIZATION_CULTURAL_BINDING.md
状态: SERVICE_READY
"""
from __future__ import annotations

import re

from loguru import logger
from sqlalchemy.orm import Session

from ainern2d_shared.schemas.skills.skill_07 import (
    CanonicalEntityFull,
    CultureBindingTrace,
    CultureConstraints,
    EntityVariantMapping,
    FallbackAction07,
    RoutingReasoningSummary,
    SelectedCulturePack,
    Skill07Input,
    Skill07Output,
    UnresolvedEntity,
)
from ainern2d_shared.services.base_skill import BaseSkillService, SkillContext

# ── Canonical namespace rules ─────────────────────────────────────────────────
# (keyword_patterns, entity_type_filter, canonical_root, canonical_specific)
_CANON_RULES: list[tuple[list[str], str, str, str]] = [
    # Places
    (["客栈", "酒馆", "inn", "tavern", "pub"], "scene_place",
     "place.social_lodging_venue", "place.social_lodging_venue.inn"),
    (["山", "peak", "mountain", "hill", "林", "forest"], "scene_place",
     "place.natural", "place.natural.mountain_or_forest"),
    (["城", "街", "city", "town", "street", "district"], "scene_place",
     "place.urban", "place.urban.city_or_street"),
    (["宫", "殿", "palace", "throne", "hall"], "scene_place",
     "place.official", "place.official.palace_or_hall"),
    (["院", "courtyard", "courtyard"], "scene_place",
     "place.residential", "place.residential.courtyard"),
    # Props
    (["剑", "刀", "sword", "blade", "dagger", "katana"], "prop",
     "prop.cold_weapon", "prop.cold_weapon.blade"),
    (["枪", "弓", "spear", "bow", "polearm"], "prop",
     "prop.cold_weapon", "prop.cold_weapon.polearm_or_ranged"),
    (["令牌", "玉佩", "token", "seal", "amulet", "信物"], "prop",
     "prop.symbol", "prop.symbol.token_or_seal"),
    (["书", "卷", "scroll", "book", "letter"], "prop",
     "prop.document", "prop.document.scroll_or_book"),
    # Costumes
    (["袍", "robe", "gown", "道袍", "长袍"], "costume",
     "costume.formal", "costume.formal.robe"),
    (["甲", "铠甲", "armor", "armour"], "costume",
     "costume.armor", "costume.armor.battle"),
    (["斗篷", "cloak", "mantle", "cape"], "costume",
     "costume.outerwear", "costume.outerwear.cloak"),
    # Characters → always map to character.human
    ([], "character", "character.human", "character.human"),
]

# ── Culture pack visual traits library ───────────────────────────────────────
_CULTURE_TRAITS: dict[str, dict[str, list[str]]] = {
    "cn_wuxia": {
        "scene_place": ["wood_architecture", "lantern_lighting", "jianghu_ambiance"],
        "prop": ["chinese_sword_style", "ancient_cn_material"],
        "costume": ["hanfu_style", "jianghu_outfit", "ancient_cn_fabric"],
        "character": ["jianghu_warrior_style", "ancient_cn_attire"],
    },
    "cn_xianxia": {
        "scene_place": ["mystical_architecture", "cloud_mountain", "xianxia_environment"],
        "prop": ["magical_weapon", "spiritual_artifact"],
        "costume": ["xianxia_robe", "cultivation_attire"],
        "character": ["cultivator_style", "immortal_aesthetic"],
    },
    "cn_modern_urban": {
        "scene_place": ["modern_chinese_building", "urban_street", "contemporary_interior"],
        "prop": ["modern_everyday_item"],
        "costume": ["modern_cn_fashion"],
        "character": ["modern_cn_casual"],
    },
    "jp_anime": {
        "scene_place": ["anime_aesthetic_scene", "japanese_urban_or_school"],
        "prop": ["anime_style_prop"],
        "costume": ["anime_costume_style"],
        "character": ["anime_character_design"],
    },
    "en_western_fantasy": {
        "scene_place": ["medieval_european_architecture", "fantasy_landscape"],
        "prop": ["european_weapon", "fantasy_artifact"],
        "costume": ["medieval_european_attire", "fantasy_clothing"],
        "character": ["western_fantasy_character"],
    },
    "generic": {
        "scene_place": ["generic_neutral_scene"],
        "prop": ["generic_prop"],
        "costume": ["generic_attire"],
        "character": ["generic_character"],
    },
}

# ── Conflict type checks ───────────────────────────────────────────────────────
_ERA_MODERN_KEYWORDS = re.compile(
    r"\b(?:modern|urban|contemporary|street|neon|phone|car|office)\b", re.I
)
_ERA_MODERN_ZH = re.compile(r"现代|都市|城市|手机|汽车|办公")
_ERA_ANCIENT_PACKS = {"cn_wuxia", "cn_xianxia", "jp_historical", "en_western_fantasy"}


class CanonicalizationService(BaseSkillService[Skill07Input, Skill07Output]):
    """SKILL 07 — Entity Canonicalization & Cultural Binding.

    State machine:
      INIT → CANONICALIZING → CANONICAL_READY → CULTURE_ROUTING
           → CULTURE_BOUND → VARIANT_MAPPING → VARIANTS_READY
           → CONFLICT_CHECKING → READY_FOR_ASSET_MATCH | REVIEW_REQUIRED | FAILED
    """

    skill_id = "skill_07"
    skill_name = "CanonicalizationService"

    def __init__(self, db: Session) -> None:
        super().__init__(db)

    # ── Public entry ───────────────────────────────────────────────────────────

    def execute(self, input_dto: Skill07Input, ctx: SkillContext) -> Skill07Output:
        warnings: list[str] = []

        if not input_dto.entities:
            self._record_state(ctx, "INIT", "FAILED")
            raise ValueError("REQ-VALIDATION-001: entities list is empty — SKILL 04 output required")

        # ── [B1] Canonicalization ─────────────────────────────────────────────
        self._record_state(ctx, "INIT", "CANONICALIZING")
        canonical_entities = self._canonicalize(input_dto.entities, input_dto.scenes)
        self._record_state(ctx, "CANONICALIZING", "CANONICAL_READY")

        # ── [B2] Culture Pack Routing ─────────────────────────────────────────
        self._record_state(ctx, "CANONICAL_READY", "CULTURE_ROUTING")
        selected_pack, reasoning = self._route_culture_pack(input_dto)
        constraints = _build_constraints(selected_pack.id)
        self._record_state(ctx, "CULTURE_ROUTING", "CULTURE_BOUND")

        # ── [B3] Variant Mapping ──────────────────────────────────────────────
        self._record_state(ctx, "CULTURE_BOUND", "VARIANT_MAPPING")
        variant_mapping, unresolved = self._map_variants(
            canonical_entities, selected_pack, input_dto
        )
        if unresolved:
            warnings.append(f"unresolved_entities: {len(unresolved)}")
        self._record_state(ctx, "VARIANT_MAPPING", "VARIANTS_READY")

        # ── [B4] Conflict Check ───────────────────────────────────────────────
        self._record_state(ctx, "VARIANTS_READY", "CONFLICT_CHECKING")
        conflicts, fallback_actions = self._check_conflicts(
            canonical_entities, selected_pack, input_dto
        )
        high_conflicts = [c for c in conflicts if c.severity == "high"]

        # ── Final status ──────────────────────────────────────────────────────
        needs_review = bool(high_conflicts) or any(u.requires_review for u in unresolved)
        status = "review_required" if needs_review else "ready_for_asset_match"
        final_state = "REVIEW_REQUIRED" if needs_review else "READY_FOR_ASSET_MATCH"
        self._record_state(ctx, "CONFLICT_CHECKING", final_state)

        logger.info(
            f"[{self.skill_id}] completed | run={ctx.run_id} status={status} "
            f"canonical={len(canonical_entities)} variants={len(variant_mapping)} "
            f"conflicts={len(conflicts)} unresolved={len(unresolved)}"
        )

        return Skill07Output(
            selected_culture_pack=selected_pack,
            routing_reasoning_summary=reasoning,
            culture_constraints=constraints,
            canonical_entities=canonical_entities,
            entity_variant_mapping=variant_mapping,
            conflicts=conflicts,
            unresolved_entities=unresolved,
            fallback_actions=fallback_actions,
            culture_binding_trace=CultureBindingTrace(culture_pack_id=selected_pack.id),
            warnings=warnings,
            status=status,
        )

    # ── [B1] Canonicalization ─────────────────────────────────────────────────

    @staticmethod
    def _canonicalize(
        entities: list[dict],
        scenes: list[dict],
    ) -> list[CanonicalEntityFull]:
        scene_ids_by_order = [s.get("scene_id", "") for s in scenes]

        result: list[CanonicalEntityFull] = []
        for ent in entities:
            uid = ent.get("entity_uid", "")
            etype = ent.get("entity_type", "character")
            surface = ent.get("surface_form", "")

            root, specific = _lookup_canonical(surface, etype)
            scene_scope = ent.get("scene_scope", scene_ids_by_order[:2])

            result.append(
                CanonicalEntityFull(
                    entity_uid=uid,
                    entity_type=etype,
                    surface_form=surface,
                    source_mentions=[surface],
                    canonical_entity_root=root,
                    canonical_entity_specific=specific,
                    attributes=ent.get("attributes", {}),
                    scene_scope=scene_scope if isinstance(scene_scope, list) else [scene_scope],
                )
            )
        return result

    # ── [B2] Culture Pack Routing ─────────────────────────────────────────────

    @staticmethod
    def _route_culture_pack(
        input_dto: Skill07Input,
    ) -> tuple[SelectedCulturePack, RoutingReasoningSummary]:
        # Priority 1: user_override
        override = input_dto.user_override.get("culture_pack")
        if override:
            return (
                SelectedCulturePack(
                    id=override, locale=input_dto.target_locale,
                    era=input_dto.time_period, genre=input_dto.genre,
                    source="user_override",
                ),
                RoutingReasoningSummary(reason_tags=["user_override"], confidence=1.0),
            )

        # Priority 2: top culture_candidate from SKILL 02 output
        if input_dto.culture_candidates:
            top = input_dto.culture_candidates[0]
            pack_id = top.get("culture_pack_id", top.get("culture_code", "generic"))
            conf = float(top.get("confidence", 0.7))
            tags = top.get("reason_tags", [])
            return (
                SelectedCulturePack(
                    id=pack_id,
                    locale=input_dto.target_locale,
                    era=input_dto.time_period,
                    genre=input_dto.genre,
                    source="culture_candidate_from_skill02",
                ),
                RoutingReasoningSummary(reason_tags=tags, confidence=round(conf, 4)),
            )

        # Priority 3: genre + world_setting heuristic
        genre = (input_dto.genre or "").lower()
        world = (input_dto.story_world_setting or "").lower()
        lang = (input_dto.target_language or "zh-CN").lower()

        if "wuxia" in genre or ("historical" in world and lang.startswith("zh")):
            pack_id, conf, tags = "cn_wuxia", 0.82, ["genre_wuxia_inferred"]
        elif "xianxia" in genre or "cultivation" in genre:
            pack_id, conf, tags = "cn_xianxia", 0.78, ["genre_xianxia_inferred"]
        elif lang.startswith("zh"):
            pack_id, conf, tags = "cn_modern_urban", 0.55, ["zh_language_default"]
        elif lang.startswith("ja"):
            pack_id, conf, tags = "jp_anime", 0.60, ["ja_language_default"]
        elif "fantasy" in genre or "fantasy" in world:
            pack_id, conf, tags = "en_western_fantasy", 0.65, ["en_fantasy_inferred"]
        else:
            pack_id, conf, tags = "generic", 0.40, ["default_fallback"]

        return (
            SelectedCulturePack(
                id=pack_id,
                locale=input_dto.target_locale,
                era=input_dto.time_period,
                genre=input_dto.genre,
                source="genre+world_setting",
            ),
            RoutingReasoningSummary(reason_tags=tags, confidence=conf),
        )

    # ── [B3] Variant Mapping ──────────────────────────────────────────────────

    @staticmethod
    def _map_variants(
        canonical_entities: list[CanonicalEntityFull],
        selected_pack: SelectedCulturePack,
        input_dto: Skill07Input,
    ) -> tuple[list[EntityVariantMapping], list[UnresolvedEntity]]:
        pack_id = selected_pack.id
        traits_table = _CULTURE_TRAITS.get(pack_id, _CULTURE_TRAITS["generic"])
        variant_mapping: list[EntityVariantMapping] = []
        unresolved: list[UnresolvedEntity] = []

        for ent in canonical_entities:
            specific = ent.canonical_entity_specific
            if not specific:
                unresolved.append(
                    UnresolvedEntity(
                        entity_uid=ent.entity_uid,
                        reason="canonical_entity_specific_empty",
                        severity="low",
                        suggested_fallback=f"entity.generic.{ent.entity_type}",
                        requires_review=False,
                    )
                )
                continue

            variant_id = f"{specific}.{pack_id}"
            traits = traits_table.get(ent.entity_type, traits_table.get("character", []))
            conf = 0.90 if pack_id != "generic" else 0.50
            fallback_used = pack_id == "generic"

            display_name = _build_display_name(ent.surface_form, pack_id)

            variant_mapping.append(
                EntityVariantMapping(
                    entity_uid=ent.entity_uid,
                    canonical_entity_specific=specific,
                    selected_variant_id=variant_id,
                    variant_display_name=display_name,
                    culture_pack=pack_id,
                    match_confidence=round(conf, 4),
                    visual_traits=traits,
                    fallback_used=fallback_used,
                )
            )
        return variant_mapping, unresolved

    # ── [B4] Conflict Check ───────────────────────────────────────────────────

    @staticmethod
    def _check_conflicts(
        canonical_entities: list[CanonicalEntityFull],
        selected_pack: SelectedCulturePack,
        input_dto: Skill07Input,
    ):
        from ainern2d_shared.schemas.skills.skill_07 import ConflictItem  # local import to avoid circular
        conflicts: list[ConflictItem] = []
        fallback_actions: list[FallbackAction07] = []

        pack_id = selected_pack.id
        is_ancient_pack = pack_id in _ERA_ANCIENT_PACKS

        for ent in canonical_entities:
            surface = ent.surface_form
            # ERA conflict: ancient pack + modern surface keywords
            if is_ancient_pack and (
                _ERA_MODERN_KEYWORDS.search(surface)
                or _ERA_MODERN_ZH.search(surface)
            ):
                conflicts.append(
                    ConflictItem(
                        conflict_type="ERA_CONFLICT",
                        entity_uid=ent.entity_uid,
                        severity="medium",
                        description=f"Entity '{surface}' appears modern but culture pack is ancient ({pack_id})",
                        suggested_fix=f"Replace with period-appropriate equivalent in {pack_id}",
                    )
                )
                fallback_actions.append(
                    FallbackAction07(
                        entity_uid=ent.entity_uid,
                        action=f"use_period_appropriate_variant_in_{pack_id}",
                    )
                )

        return conflicts, fallback_actions


# ── Module-level helpers ───────────────────────────────────────────────────────

def _lookup_canonical(surface: str, entity_type: str) -> tuple[str, str]:
    """Return (canonical_root, canonical_specific) for a surface form + type."""
    surface_lower = surface.lower()
    for keywords, type_filter, root, specific in _CANON_RULES:
        if type_filter and type_filter != entity_type:
            continue
        if not keywords or any(k in surface_lower or k in surface for k in keywords):
            return root, specific
    # Generic fallback
    return f"entity.{entity_type}", f"entity.{entity_type}.generic"


def _build_constraints(pack_id: str) -> CultureConstraints:
    presets: dict[str, CultureConstraints] = {
        "cn_wuxia": CultureConstraints(
            visual_do=["wood_architecture", "lantern_lighting", "jianghu_costume"],
            visual_dont=["modern_neon_sign", "western_pub_taps", "contemporary_furniture"],
            signage_rules=["hanzi_preferred", "avoid_modern_typography"],
            hard_constraints=["no_anachronistic_technology"],
            soft_preferences=["prefer_wuxia_cinematic_style"],
        ),
        "cn_xianxia": CultureConstraints(
            visual_do=["mystical_floating_environment", "cultivation_artifacts"],
            visual_dont=["modern_elements", "western_fantasy"],
            signage_rules=["hanzi_preferred"],
            hard_constraints=["no_modern_technology"],
            soft_preferences=["prefer_ethereal_visual_style"],
        ),
        "jp_anime": CultureConstraints(
            visual_do=["anime_cel_shading", "japanese_cultural_elements"],
            visual_dont=["photorealistic_western", "chinese_historical"],
            signage_rules=["kanji_hiragana_preferred"],
            hard_constraints=[],
            soft_preferences=["prefer_anime_aesthetic"],
        ),
    }
    return presets.get(pack_id, CultureConstraints(
        soft_preferences=[f"follow_{pack_id}_visual_guidelines"]
    ))


def _build_display_name(surface: str, pack_id: str) -> str:
    if pack_id.startswith("cn_"):
        return surface  # keep Chinese display name
    return surface
