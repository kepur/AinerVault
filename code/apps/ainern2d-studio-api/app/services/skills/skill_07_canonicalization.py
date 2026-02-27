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
    ConflictItem,
    EntityVariantMapping,
    FallbackAction07,
    FeedbackAnchorTags,
    KBSuggestion,
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
    (["院", "courtyard"], "scene_place",
     "place.residential", "place.residential.courtyard"),
    (["桥", "bridge"], "scene_place",
     "place.infrastructure", "place.infrastructure.bridge"),
    (["庙", "寺", "temple", "shrine", "monastery"], "scene_place",
     "place.religious", "place.religious.temple"),
    (["市集", "集市", "market", "bazaar", "marketplace"], "scene_place",
     "place.commercial", "place.commercial.market"),
    # Props
    (["剑", "刀", "sword", "blade", "dagger", "katana"], "prop",
     "prop.cold_weapon", "prop.cold_weapon.blade"),
    (["枪", "弓", "spear", "bow", "polearm"], "prop",
     "prop.cold_weapon", "prop.cold_weapon.polearm_or_ranged"),
    (["令牌", "玉佩", "token", "seal", "amulet", "信物"], "prop",
     "prop.symbol", "prop.symbol.token_or_seal"),
    (["书", "卷", "scroll", "book", "letter"], "prop",
     "prop.document", "prop.document.scroll_or_book"),
    (["灯笼", "灯", "lantern", "lamp", "candle", "torch"], "prop",
     "prop.lighting", "prop.lighting.lantern_or_lamp"),
    (["酒", "茶", "wine", "tea", "drink", "beverage"], "prop",
     "prop.consumable", "prop.consumable.drink"),
    (["马", "horse", "carriage", "cart", "车"], "prop",
     "prop.transport", "prop.transport.horse_or_cart"),
    # Costumes
    (["袍", "robe", "gown", "道袍", "长袍"], "costume",
     "costume.formal", "costume.formal.robe"),
    (["甲", "铠甲", "armor", "armour"], "costume",
     "costume.armor", "costume.armor.battle"),
    (["斗篷", "cloak", "mantle", "cape"], "costume",
     "costume.outerwear", "costume.outerwear.cloak"),
    (["冠", "crown", "hat", "帽", "头饰", "headpiece"], "costume",
     "costume.headwear", "costume.headwear.formal"),
    (["裙", "dress", "skirt"], "costume",
     "costume.lower", "costume.lower.dress_or_skirt"),
    # Characters → always map to character.human
    ([], "character", "character.human", "character.human"),
]

# ── Culture pack visual traits library (8-12 traits per culture/type) ────────
_CULTURE_TRAITS: dict[str, dict[str, list[str]]] = {
    "cn_wuxia": {
        "scene_place": [
            "wood_architecture", "lantern_lighting", "jianghu_ambiance",
            "curved_tile_roof", "bamboo_grove_backdrop", "ink_wash_fog",
            "stone_bridge", "courtyard_garden", "calligraphy_signboard",
            "red_lacquer_pillar", "paper_window_lattice", "clay_tile_floor",
        ],
        "prop": [
            "chinese_sword_jian", "ancient_cn_material", "jade_pendant",
            "bronze_wine_cup", "bamboo_scroll", "silk_fan",
            "iron_token", "calligraphy_brush", "herbal_medicine_pouch",
            "lacquer_box", "porcelain_teapot",
        ],
        "costume": [
            "hanfu_style", "jianghu_outfit", "ancient_cn_fabric",
            "wide_sleeve_robe", "cloth_belt_sash", "embroidered_silk",
            "bamboo_hat", "straw_sandals", "leather_wrist_guard",
            "jade_hair_pin", "dark_cloth_cloak",
        ],
        "character": [
            "jianghu_warrior_style", "ancient_cn_attire", "ink_eyebrow",
            "hair_bun_topknot", "lean_martial_physique", "cloth_shoe",
            "inner_strength_aura", "sword_carrying_posture", "tea_sipping_poise",
            "calloused_hands", "weathered_travel_look",
        ],
    },
    "cn_xianxia": {
        "scene_place": [
            "mystical_architecture", "cloud_mountain", "xianxia_environment",
            "floating_island", "celestial_palace", "spirit_river",
            "ancient_cave_dwelling", "peach_blossom_grove", "jade_stairway",
            "glowing_formation_array", "starlit_meditation_hall",
        ],
        "prop": [
            "magical_weapon", "spiritual_artifact", "flying_sword",
            "jade_slip_scroll", "spirit_stone", "formation_flag",
            "alchemy_furnace", "soul_binding_chain", "heavenly_compass",
            "immortal_gourd", "thunder_talisman",
        ],
        "costume": [
            "xianxia_robe", "cultivation_attire", "flowing_white_silk",
            "cloud_pattern_embroidery", "jade_belt_ornament", "feather_cloak",
            "golden_crown", "sect_uniform", "spirit_armor",
            "lotus_hair_ornament", "celestial_sash",
        ],
        "character": [
            "cultivator_style", "immortal_aesthetic", "ethereal_glow_skin",
            "long_flowing_hair", "sword_riding_posture", "third_eye_mark",
            "qi_aura_visual", "youthful_ageless_face", "meditation_pose",
            "dao_bone_frame", "spiritual_pressure_halo",
        ],
    },
    "cn_modern_urban": {
        "scene_place": [
            "modern_chinese_building", "urban_street", "contemporary_interior",
            "high_rise_apartment", "neon_night_market", "subway_station",
            "office_tower_lobby", "hutong_alley", "rooftop_terrace",
            "convenience_store", "tea_house_modern",
        ],
        "prop": [
            "modern_everyday_item", "smartphone", "takeaway_coffee_cup",
            "electric_scooter", "laptop_bag", "id_card",
            "transit_card", "umbrella_foldable", "instant_noodle_cup",
            "wechat_qr_code_sign",
        ],
        "costume": [
            "modern_cn_fashion", "business_casual", "streetwear_cn",
            "down_jacket", "sneakers", "crossbody_bag",
            "face_mask_medical", "baseball_cap", "cheongsam_modern",
            "denim_jeans",
        ],
        "character": [
            "modern_cn_casual", "office_worker_look", "college_student",
            "delivery_rider", "street_vendor", "tech_professional",
            "elderly_tai_chi", "young_couple_style", "urban_commuter",
            "night_market_patron",
        ],
    },
    "jp_anime": {
        "scene_place": [
            "anime_aesthetic_scene", "japanese_urban_or_school",
            "sakura_lined_street", "shinto_shrine", "rooftop_school",
            "onsen_town", "akihabara_neon", "rural_countryside_jp",
            "izakaya_interior", "train_platform", "convenience_store_jp",
        ],
        "prop": [
            "anime_style_prop", "bento_box", "katana_blade",
            "school_bag_randoseru", "shuriken", "omamori_charm",
            "manga_volume", "chopstick_pair", "paper_fan_uchiwa",
            "wooden_geta_sandal",
        ],
        "costume": [
            "anime_costume_style", "seifuku_school_uniform", "kimono_traditional",
            "yukata_casual", "sailor_fuku", "maid_outfit",
            "samurai_hakama", "ninja_shinobi_gear", "shrine_maiden_miko",
            "tokusatsu_suit",
        ],
        "character": [
            "anime_character_design", "large_expressive_eyes", "colorful_hair",
            "chibi_proportion_option", "bishounen_aesthetic", "tsundere_expression",
            "cat_ear_accessory", "school_id_badge", "sweat_drop_effect",
            "sparkle_background_aura",
        ],
    },
    "kr_historical": {
        "scene_place": [
            "hanok_architecture", "joseon_palace", "korean_countryside",
            "thatched_roof_village", "gisaeng_house", "confucian_academy",
            "fortress_wall", "pine_tree_mountain", "pavilion_by_stream",
            "market_street_joseon",
        ],
        "prop": [
            "korean_celadon_pottery", "gayageum_instrument", "wooden_chest",
            "ink_brush_korean", "horse_bridle_joseon", "silk_scroll_kr",
            "jade_ring", "iron_pot", "paper_lantern_kr",
        ],
        "costume": [
            "hanbok_male", "hanbok_female", "gat_horsehair_hat",
            "dopo_overcoat", "binyeo_hair_pin", "norigae_pendant",
            "chima_jeogori", "silk_belt_daedae", "beoseon_socks",
        ],
        "character": [
            "joseon_scholar_look", "court_lady_look", "warrior_hwarang",
            "yangban_noble", "peasant_farmer_kr", "gisaeng_entertainer",
            "monk_buddhist_kr", "royal_bearing", "humble_servant_posture",
        ],
    },
    "en_western_fantasy": {
        "scene_place": [
            "medieval_european_architecture", "fantasy_landscape",
            "stone_castle", "enchanted_forest", "cobblestone_village",
            "dragon_lair_cave", "wizard_tower", "throne_room",
            "harbor_port_medieval", "underground_dungeon", "tavern_fireplace",
        ],
        "prop": [
            "european_weapon", "fantasy_artifact", "iron_longsword",
            "wooden_shield", "crystal_orb", "spell_tome",
            "torch_wall_mounted", "gold_coin_pouch", "enchanted_ring",
            "quill_ink_set", "horn_drinking_vessel",
        ],
        "costume": [
            "medieval_european_attire", "fantasy_clothing", "chainmail_armor",
            "leather_jerkin", "hooded_travelling_cloak", "royal_velvet_cape",
            "iron_helm", "fur_lined_boots", "gauntlet_steel",
            "mage_robe_embroidered",
        ],
        "character": [
            "western_fantasy_character", "rugged_adventurer", "elven_features",
            "dwarven_stout_build", "regal_posture", "scarred_veteran_face",
            "flowing_beard", "pointed_ear_option", "mystic_eye_glow",
            "heraldic_emblem_patch",
        ],
    },
    "generic": {
        "scene_place": [
            "generic_neutral_scene", "simple_interior", "outdoor_open",
            "neutral_background", "soft_lighting", "minimalist_architecture",
            "flat_color_backdrop", "studio_environment",
        ],
        "prop": [
            "generic_prop", "basic_container", "simple_tool",
            "unbranded_object", "plain_weapon_silhouette", "neutral_furniture",
            "basic_lighting_fixture", "simple_document",
        ],
        "costume": [
            "generic_attire", "neutral_clothing", "simple_robe",
            "basic_tunic", "unadorned_cloak", "plain_footwear",
            "minimal_accessory", "earth_tone_fabric",
        ],
        "character": [
            "generic_character", "neutral_expression", "average_build",
            "simple_hairstyle", "clean_appearance", "unremarkable_posture",
            "default_skin_tone", "no_distinctive_marks",
        ],
    },
}

# ── Conflict detection keyword patterns ───────────────────────────────────────
_ERA_MODERN_KEYWORDS = re.compile(
    r"\b(?:modern|urban|contemporary|street|neon|phone|car|office|laptop|wifi"
    r"|elevator|skyscraper|subway|taxi|television|internet|electricity)\b", re.I,
)
_ERA_MODERN_ZH = re.compile(r"现代|都市|城市|手机|汽车|办公|电脑|地铁|出租车|电视|网络|电灯|高楼")
_ERA_ANCIENT_PACKS = {"cn_wuxia", "cn_xianxia", "jp_historical", "kr_historical", "en_western_fantasy"}

_LANG_SIGNAGE_RULES: dict[str, set[str]] = {
    "cn_wuxia": {"hanzi", "chinese"},
    "cn_xianxia": {"hanzi", "chinese"},
    "cn_modern_urban": {"hanzi", "chinese", "pinyin"},
    "jp_anime": {"kanji", "hiragana", "katakana", "japanese"},
    "jp_historical": {"kanji", "hiragana", "japanese"},
    "kr_historical": {"hangul", "hanja", "korean"},
    "en_western_fantasy": {"latin", "runic", "english"},
}
_SIGNAGE_CONFLICT_KEYWORDS: dict[str, re.Pattern[str]] = {
    "latin_in_cn": re.compile(r"\b(?:english_sign|latin_text|alphabet_board|roman_letter)\b", re.I),
    "hanzi_in_en": re.compile(r"中文招牌|汉字标牌|Chinese_signage", re.I),
    "hangul_in_cn": re.compile(r"한글|hangul_sign", re.I),
}

_GENRE_WUXIA_KEYWORDS = re.compile(
    r"\b(?:wuxia|jianghu|martial_arts|kung_fu|武侠|江湖|武林)\b", re.I,
)
_GENRE_MODERN_KEYWORDS = re.compile(
    r"\b(?:bar_counter|cocktail|DJ|nightclub|disco|neon_bar|pub_taps|jukebox"
    r"|karaoke|modern_lounge)\b", re.I,
)
_GENRE_MODERN_ZH = re.compile(r"酒吧台|鸡尾酒|夜店|迪厅|KTV|卡拉OK")

_COSTUME_MODERN_KEYWORDS = re.compile(
    r"\b(?:suit|tie|sneakers|t-shirt|jeans|hoodie|tracksuit|blazer|polo)\b", re.I,
)
_COSTUME_MODERN_ZH = re.compile(r"西装|领带|运动鞋|牛仔裤|T恤|帽衫|卫衣|休闲裤")

_PROP_REGION_CONFLICT_MAP: dict[str, re.Pattern[str]] = {
    "cn_wuxia": re.compile(r"\b(?:katana|samurai|shuriken|longsword|rapier|musket|geta)\b", re.I),
    "cn_xianxia": re.compile(r"\b(?:katana|longsword|rapier|revolver|pistol|rifle)\b", re.I),
    "jp_anime": re.compile(r"\b(?:jian|dao|qiang|guandao|nunchaku|飞镖|暗器)\b", re.I),
    "en_western_fantasy": re.compile(r"\b(?:katana|shuriken|jian|dao|nunchaku)\b", re.I),
    "kr_historical": re.compile(r"\b(?:katana|jian|rapier|musket|longsword)\b", re.I),
}

_ARCHITECTURE_ANCIENT_CN = re.compile(
    r"\b(?:glass_curtain_wall|steel_frame|concrete|skyscraper|elevator|revolving_door)\b", re.I,
)
_ARCHITECTURE_ANCIENT_CN_ZH = re.compile(r"玻璃幕墙|钢结构|混凝土|摩天楼|电梯|旋转门")
_ARCHITECTURE_WESTERN_IN_CN = re.compile(
    r"\b(?:gothic_arch|flying_buttress|stained_glass_church|roman_column_massive)\b", re.I,
)

_SOCIAL_NORM_CONFLICT_RULES: list[tuple[set[str], re.Pattern[str], str]] = [
    # handshake / fist-bump in ancient Chinese formal court
    ({"cn_wuxia", "cn_xianxia", "kr_historical"},
     re.compile(r"\b(?:handshake|fist_bump|high_five|hug_greeting)\b", re.I),
     "Modern Western greeting gesture in traditional East-Asian context"),
    # shoes indoors in Japanese setting
    ({"jp_anime", "jp_historical"},
     re.compile(r"\b(?:shoes_indoors|boots_inside|wearing_shoes_tatami)\b", re.I),
     "Wearing shoes indoors in Japanese setting violates social norms"),
    # bare head in Joseon court
    ({"kr_historical"},
     re.compile(r"\b(?:bare_head_court|no_hat_noble|uncovered_head_yangban)\b", re.I),
     "Joseon noble without gat headwear in formal court setting"),
]

# ── Scene context → extra trait modifiers ────────────────────────────────────
_SCENE_CONTEXT_TRAITS: dict[str, list[str]] = {
    "宫廷": ["imperial_grandeur", "gold_accent", "ornate_carvings"],
    "palace": ["imperial_grandeur", "gold_accent", "ornate_carvings"],
    "court": ["imperial_grandeur", "gold_accent", "ornate_carvings"],
    "江湖": ["rustic_wood", "dusty_road", "wanderer_vibe"],
    "jianghu": ["rustic_wood", "dusty_road", "wanderer_vibe"],
    "校园": ["campus_greenery", "classroom_interior", "youthful_energy"],
    "school": ["campus_greenery", "classroom_interior", "youthful_energy"],
    "campus": ["campus_greenery", "classroom_interior", "youthful_energy"],
    "办公室": ["corporate_interior", "fluorescent_light", "glass_partition"],
    "office": ["corporate_interior", "fluorescent_light", "glass_partition"],
    "贫民区": ["worn_walls", "dim_lighting", "crowded_alley"],
    "slum": ["worn_walls", "dim_lighting", "crowded_alley"],
    "战场": ["scorched_earth", "broken_weapons", "smoke_haze"],
    "battlefield": ["scorched_earth", "broken_weapons", "smoke_haze"],
    "market": ["bustling_crowd", "colorful_stall", "vendor_shout"],
    "市集": ["bustling_crowd", "colorful_stall", "vendor_shout"],
}

# ── Character role → extra trait modifiers ───────────────────────────────────
_CHARACTER_ROLE_TRAITS: dict[str, list[str]] = {
    "侠客": ["sword_at_waist", "travel_worn_cloak", "sharp_gaze"],
    "hero": ["sword_at_waist", "travel_worn_cloak", "sharp_gaze"],
    "皇帝": ["dragon_robe", "imperial_crown", "commanding_aura"],
    "emperor": ["dragon_robe", "imperial_crown", "commanding_aura"],
    "king": ["royal_crown", "ermine_cloak", "commanding_aura"],
    "学生": ["school_uniform", "book_bag", "youthful_face"],
    "student": ["school_uniform", "book_bag", "youthful_face"],
    "丫鬟": ["servant_dress", "modest_hair_bun", "downcast_eyes"],
    "servant": ["servant_dress", "modest_hair_bun", "downcast_eyes"],
    "maid": ["servant_dress", "modest_hair_bun", "downcast_eyes"],
    "掌柜": ["merchant_robe", "abacus_prop", "shrewd_expression"],
    "merchant": ["merchant_robe", "abacus_prop", "shrewd_expression"],
    "将军": ["general_armor", "war_horse", "battle_flag"],
    "general": ["general_armor", "war_horse", "battle_flag"],
    "道士": ["daoist_robe", "horsehair_whisk", "talisman"],
    "priest": ["clerical_vestment", "holy_symbol", "solemn_expression"],
    "beggar": ["ragged_cloth", "patched_bowl", "unkempt_hair"],
    "乞丐": ["ragged_cloth", "patched_bowl", "unkempt_hair"],
    "assassin": ["dark_cloak", "concealed_blade", "shadow_posture"],
    "刺客": ["dark_cloak", "concealed_blade", "shadow_posture"],
}


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
        entity_id_map = self._build_entity_id_map(input_dto)
        canonical_entities = self._canonicalize(
            input_dto.entities,
            input_dto.scenes,
            entity_id_map,
        )
        self._record_state(ctx, "CANONICALIZING", "CANONICAL_READY")

        # ── [B2] Culture Pack Routing ─────────────────────────────────────────
        self._record_state(ctx, "CANONICAL_READY", "CULTURE_ROUTING")
        selected_pack, reasoning = self._route_culture_pack(input_dto)
        constraints = _build_constraints(selected_pack.id)
        self._record_state(ctx, "CULTURE_ROUTING", "CULTURE_BOUND")

        # ── [B3] Variant Mapping ──────────────────────────────────────────────
        self._record_state(ctx, "CULTURE_BOUND", "VARIANT_MAPPING")
        variant_mapping, unresolved = self._map_variants(
            canonical_entities, selected_pack, input_dto,
        )
        if unresolved:
            warnings.append(f"unresolved_entities: {len(unresolved)}")
        self._record_state(ctx, "VARIANT_MAPPING", "VARIANTS_READY")

        # ── [B4] Conflict Check ───────────────────────────────────────────────
        self._record_state(ctx, "VARIANTS_READY", "CONFLICT_CHECKING")
        conflicts, fallback_actions = self._check_conflicts(
            canonical_entities, variant_mapping, selected_pack, input_dto,
        )
        high_conflicts = [c for c in conflicts if c.severity == "high"]

        # ── KB suggestions ────────────────────────────────────────────────────
        kb_suggestions = _build_kb_suggestions(variant_mapping, selected_pack.id)

        # ── Feedback anchor tags ──────────────────────────────────────────────
        feedback_tags = _build_feedback_anchor_tags(conflicts, unresolved)

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
            kb_suggestions=kb_suggestions,
            feedback_anchor_tags=feedback_tags,
            warnings=warnings,
            status=status,
        )

    # ── [B1] Canonicalization ─────────────────────────────────────────────────

    @staticmethod
    def _canonicalize(
        entities: list[dict],
        scenes: list[dict],
        entity_id_map: dict[str, str],
    ) -> list[CanonicalEntityFull]:
        scene_ids_by_order = [s.get("scene_id", "") for s in scenes]

        result: list[CanonicalEntityFull] = []
        for idx, ent in enumerate(entities, start=1):
            uid = str(ent.get("entity_uid", ent.get("source_entity_uid", ""))).strip()
            if not uid:
                uid = f"entity_{idx:04d}"
            entity_id = str(
                ent.get("entity_id")
                or entity_id_map.get(uid)
                or uid
            ).strip()
            etype = ent.get("entity_type", "character")
            surface = ent.get("surface_form", "")

            root, specific = _lookup_canonical(surface, etype)
            scene_scope = ent.get("scene_scope", scene_ids_by_order[:2])

            result.append(
                CanonicalEntityFull(
                    entity_uid=uid,
                    entity_id=entity_id,
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
        scene_ctx = (input_dto.scene_context or "").strip()
        char_role = (input_dto.character_role or "").strip()

        for ent in canonical_entities:
            specific = ent.canonical_entity_specific
            # --- Better unresolved handling: 3 categories ---
            if not specific:
                unresolved.append(
                    UnresolvedEntity(
                        entity_uid=ent.entity_uid,
                        reason="insufficient_information: canonical_entity_specific is empty",
                        severity="low",
                        suggested_fallback=f"entity.generic.{ent.entity_type}",
                        requires_review=False,
                    )
                )
                continue

            # Semantic ambiguity: surface form matches multiple canonical roots
            if _is_semantically_ambiguous(ent.surface_form, ent.entity_type):
                unresolved.append(
                    UnresolvedEntity(
                        entity_uid=ent.entity_uid,
                        reason=f"semantic_ambiguity: '{ent.surface_form}' matches multiple canonical categories",
                        severity="medium",
                        suggested_fallback=f"{specific}.{pack_id}",
                        requires_review=True,
                    )
                )
                # Still produce a best-effort variant below

            variant_id = f"{specific}.{pack_id}"
            base_traits = list(traits_table.get(ent.entity_type, traits_table.get("character", [])))

            # Enrich traits with scene_context modifiers
            if scene_ctx:
                base_traits.extend(_SCENE_CONTEXT_TRAITS.get(scene_ctx, []))

            # Enrich traits with character_role modifiers (for character entities)
            if char_role and ent.entity_type == "character":
                base_traits.extend(_CHARACTER_ROLE_TRAITS.get(char_role, []))

            # Deduplicate while preserving order
            seen: set[str] = set()
            deduped_traits: list[str] = []
            for t in base_traits:
                if t not in seen:
                    seen.add(t)
                    deduped_traits.append(t)

            conf = 0.90 if pack_id != "generic" else 0.50
            fallback_used = pack_id == "generic"

            display_name = _build_display_name(ent.surface_form, pack_id)

            # Prompt template refs
            prompt_refs = _build_prompt_template_refs(ent, pack_id, char_role)
            # Asset refs
            asset_refs = _build_asset_refs(ent, pack_id)

            variant_mapping.append(
                EntityVariantMapping(
                    entity_uid=ent.entity_uid,
                    entity_id=ent.entity_id or ent.entity_uid,
                    canonical_entity_id=ent.entity_id or ent.entity_uid,
                    matched_entity_id=ent.entity_id or ent.entity_uid,
                    source_entity_uid=ent.entity_uid,
                    canonical_entity_specific=specific,
                    selected_variant_id=variant_id,
                    variant_display_name=display_name,
                    culture_pack=pack_id,
                    match_confidence=round(conf, 4),
                    visual_traits=deduped_traits,
                    prompt_template_refs=prompt_refs,
                    asset_refs=asset_refs,
                    fallback_used=fallback_used,
                )
            )
        return variant_mapping, unresolved

    # ── [B4] Conflict Check — all 7 types ─────────────────────────────────────

    @staticmethod
    def _check_conflicts(
        canonical_entities: list[CanonicalEntityFull],
        variant_mapping: list[EntityVariantMapping],
        selected_pack: SelectedCulturePack,
        input_dto: Skill07Input,
    ) -> tuple[list[ConflictItem], list[FallbackAction07]]:
        conflicts: list[ConflictItem] = []
        fallback_actions: list[FallbackAction07] = []
        pack_id = selected_pack.id
        is_ancient_pack = pack_id in _ERA_ANCIENT_PACKS
        genre = (input_dto.genre or "").lower()

        for ent in canonical_entities:
            surface = ent.surface_form
            attrs_str = " ".join(str(v) for v in ent.attributes.values())
            combined = f"{surface} {attrs_str}"

            # 1) ERA_CONFLICT — ancient pack + modern surface keywords
            if is_ancient_pack and (
                _ERA_MODERN_KEYWORDS.search(combined)
                or _ERA_MODERN_ZH.search(combined)
            ):
                conflicts.append(ConflictItem(
                    conflict_type="ERA_CONFLICT",
                    entity_uid=ent.entity_uid,
                    severity="medium",
                    description=f"Entity '{surface}' appears modern but culture pack is ancient ({pack_id})",
                    suggested_fix=f"Replace with period-appropriate equivalent in {pack_id}",
                ))
                fallback_actions.append(FallbackAction07(
                    entity_uid=ent.entity_uid,
                    action=f"use_period_appropriate_variant_in_{pack_id}",
                ))

            # 2) LANGUAGE_SIGNAGE_CONFLICT — signage text system mismatch
            allowed_scripts = _LANG_SIGNAGE_RULES.get(pack_id, set())
            if allowed_scripts:
                for label, pattern in _SIGNAGE_CONFLICT_KEYWORDS.items():
                    if pattern.search(combined):
                        # Check if the detected script is not in allowed set
                        conflict_script = label.split("_in_")[0]
                        target_region = label.split("_in_")[1] if "_in_" in label else ""
                        if target_region and pack_id.startswith(target_region):
                            conflicts.append(ConflictItem(
                                conflict_type="LANGUAGE_SIGNAGE_CONFLICT",
                                entity_uid=ent.entity_uid,
                                severity="medium",
                                description=(
                                    f"Signage '{conflict_script}' detected in entity '{surface}' "
                                    f"but culture pack '{pack_id}' expects {sorted(allowed_scripts)}"
                                ),
                                suggested_fix=f"Use signage consistent with {pack_id}: {sorted(allowed_scripts)}",
                            ))
                            fallback_actions.append(FallbackAction07(
                                entity_uid=ent.entity_uid,
                                action=f"replace_signage_with_{pack_id}_script",
                            ))

            # 3) GENRE_CONFLICT — wuxia/xianxia pack + modern bar/nightclub elements
            if ("wuxia" in pack_id or "xianxia" in pack_id) and (
                _GENRE_MODERN_KEYWORDS.search(combined)
                or _GENRE_MODERN_ZH.search(combined)
            ):
                conflicts.append(ConflictItem(
                    conflict_type="GENRE_CONFLICT",
                    entity_uid=ent.entity_uid,
                    severity="medium",
                    description=f"Modern entertainment element in entity '{surface}' conflicts with {pack_id} genre",
                    suggested_fix=f"Replace with genre-appropriate element (e.g. teahouse, wine shop) for {pack_id}",
                ))
                fallback_actions.append(FallbackAction07(
                    entity_uid=ent.entity_uid,
                    action=f"replace_with_genre_appropriate_in_{pack_id}",
                ))

            # 4) COSTUME_CONFLICT — ancient pack + modern costume on characters
            if is_ancient_pack and ent.entity_type in ("character", "costume") and (
                _COSTUME_MODERN_KEYWORDS.search(combined)
                or _COSTUME_MODERN_ZH.search(combined)
            ):
                conflicts.append(ConflictItem(
                    conflict_type="COSTUME_CONFLICT",
                    entity_uid=ent.entity_uid,
                    severity="high",
                    description=f"Modern costume element detected for entity '{surface}' in ancient pack {pack_id}",
                    suggested_fix=f"Replace with period-appropriate attire for {pack_id}",
                ))
                fallback_actions.append(FallbackAction07(
                    entity_uid=ent.entity_uid,
                    action=f"replace_costume_with_{pack_id}_period_attire",
                ))

            # 5) PROP_REGION_CONFLICT — region-specific props that don't belong
            region_pattern = _PROP_REGION_CONFLICT_MAP.get(pack_id)
            if region_pattern and ent.entity_type == "prop" and region_pattern.search(combined):
                conflicts.append(ConflictItem(
                    conflict_type="PROP_REGION_CONFLICT",
                    entity_uid=ent.entity_uid,
                    severity="medium",
                    description=f"Prop '{surface}' appears region-inappropriate for culture pack {pack_id}",
                    suggested_fix=f"Replace with region-appropriate prop variant from {pack_id}",
                ))
                fallback_actions.append(FallbackAction07(
                    entity_uid=ent.entity_uid,
                    action=f"replace_prop_with_{pack_id}_region_variant",
                ))

            # 6) ARCHITECTURE_CONFLICT — building style vs pack mismatch
            if ent.entity_type == "scene_place" and is_ancient_pack:
                if pack_id.startswith("cn_") and (
                    _ARCHITECTURE_ANCIENT_CN.search(combined)
                    or _ARCHITECTURE_ANCIENT_CN_ZH.search(combined)
                ):
                    conflicts.append(ConflictItem(
                        conflict_type="ARCHITECTURE_CONFLICT",
                        entity_uid=ent.entity_uid,
                        severity="high",
                        description=f"Modern architecture element in scene '{surface}' conflicts with ancient {pack_id}",
                        suggested_fix=f"Replace with traditional architecture style for {pack_id}",
                    ))
                    fallback_actions.append(FallbackAction07(
                        entity_uid=ent.entity_uid,
                        action=f"replace_architecture_with_{pack_id}_traditional",
                    ))
                if pack_id.startswith("cn_") and _ARCHITECTURE_WESTERN_IN_CN.search(combined):
                    conflicts.append(ConflictItem(
                        conflict_type="ARCHITECTURE_CONFLICT",
                        entity_uid=ent.entity_uid,
                        severity="low",
                        description=f"Western architecture element in scene '{surface}' may conflict with {pack_id}",
                        suggested_fix=f"Consider replacing with Chinese architectural equivalent for {pack_id}",
                    ))

            # 7) SOCIAL_NORM_CONFLICT — gestures / etiquette mismatch
            for applicable_packs, norm_pattern, norm_desc in _SOCIAL_NORM_CONFLICT_RULES:
                if pack_id in applicable_packs and norm_pattern.search(combined):
                    conflicts.append(ConflictItem(
                        conflict_type="SOCIAL_NORM_CONFLICT",
                        entity_uid=ent.entity_uid,
                        severity="low",
                        description=f"{norm_desc}: entity '{surface}' in pack {pack_id}",
                        suggested_fix=f"Replace with culturally-appropriate gesture/norm for {pack_id}",
                    ))
                    fallback_actions.append(FallbackAction07(
                        entity_uid=ent.entity_uid,
                        action=f"replace_social_norm_with_{pack_id}_appropriate",
                    ))

        # Check variant-level conflicts: conflicting sources
        uid_to_variants: dict[str, list[EntityVariantMapping]] = {}
        for vm in variant_mapping:
            uid_to_variants.setdefault(vm.entity_uid, []).append(vm)

        return conflicts, fallback_actions

    @staticmethod
    def _build_entity_id_map(input_dto: Skill07Input) -> dict[str, str]:
        """Build source_uid -> stable entity_id map from SKILL 21 outputs."""
        mapping: dict[str, str] = {}

        def _ingest(items: list[dict]) -> None:
            for item in items:
                source_uid = str(item.get("source_entity_uid", "")).strip()
                entity_id = str(
                    item.get("matched_entity_id")
                    or item.get("entity_id")
                    or ""
                ).strip()
                if source_uid and entity_id:
                    mapping[source_uid] = entity_id

        if input_dto.resolved_entities:
            _ingest([i for i in input_dto.resolved_entities if isinstance(i, dict)])

        continuity_result = input_dto.entity_registry_continuity_result or {}
        if isinstance(continuity_result, dict):
            _ingest([
                i for i in continuity_result.get("resolved_entities", [])
                if isinstance(i, dict)
            ])

        return mapping


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


def _is_semantically_ambiguous(surface: str, entity_type: str) -> bool:
    """Check if a surface form matches keywords in multiple canonical categories."""
    surface_lower = surface.lower()
    match_count = 0
    for keywords, type_filter, _root, _specific in _CANON_RULES:
        if type_filter and type_filter != entity_type:
            continue
        if keywords and any(k in surface_lower or k in surface for k in keywords):
            match_count += 1
    return match_count >= 2


def _build_constraints(pack_id: str) -> CultureConstraints:
    presets: dict[str, CultureConstraints] = {
        "cn_wuxia": CultureConstraints(
            visual_do=["wood_architecture", "lantern_lighting", "jianghu_costume",
                       "ink_wash_palette", "bamboo_forest", "tile_rooftop"],
            visual_dont=["modern_neon_sign", "western_pub_taps", "contemporary_furniture",
                         "glass_curtain_wall", "plastic_material"],
            signage_rules=["hanzi_preferred", "avoid_modern_typography", "brush_calligraphy_style"],
            hard_constraints=["no_anachronistic_technology", "no_western_architecture"],
            soft_preferences=["prefer_wuxia_cinematic_style", "warm_lantern_tones"],
        ),
        "cn_xianxia": CultureConstraints(
            visual_do=["mystical_floating_environment", "cultivation_artifacts",
                       "cloud_sea", "jade_material", "celestial_glow"],
            visual_dont=["modern_elements", "western_fantasy", "urban_scenery"],
            signage_rules=["hanzi_preferred", "ancient_seal_script_accent"],
            hard_constraints=["no_modern_technology", "no_western_mythology"],
            soft_preferences=["prefer_ethereal_visual_style", "pastel_cloud_palette"],
        ),
        "cn_modern_urban": CultureConstraints(
            visual_do=["chinese_city_skyline", "neon_signage", "modern_interior"],
            visual_dont=["ancient_architecture", "fantasy_elements"],
            signage_rules=["simplified_chinese", "bilingual_ok"],
            hard_constraints=[],
            soft_preferences=["contemporary_chinese_urban_aesthetic"],
        ),
        "jp_anime": CultureConstraints(
            visual_do=["anime_cel_shading", "japanese_cultural_elements",
                       "sakura_motif", "clean_line_art"],
            visual_dont=["photorealistic_western", "chinese_historical"],
            signage_rules=["kanji_hiragana_preferred", "katakana_for_foreign"],
            hard_constraints=[],
            soft_preferences=["prefer_anime_aesthetic", "vibrant_color_palette"],
        ),
        "kr_historical": CultureConstraints(
            visual_do=["hanok_architecture", "joseon_costume", "celadon_pottery",
                       "pine_tree_landscape"],
            visual_dont=["modern_korean_elements", "japanese_architecture", "chinese_palace"],
            signage_rules=["hanja_hangul_mixed", "classical_korean_typography"],
            hard_constraints=["no_anachronistic_technology"],
            soft_preferences=["prefer_joseon_dynasty_palette", "muted_earth_tones"],
        ),
        "en_western_fantasy": CultureConstraints(
            visual_do=["stone_castle", "torch_lighting", "medieval_village",
                       "enchanted_forest", "heraldic_banners"],
            visual_dont=["modern_technology", "east_asian_architecture"],
            signage_rules=["latin_script", "runic_accent_ok"],
            hard_constraints=["no_modern_technology"],
            soft_preferences=["prefer_epic_fantasy_palette", "warm_tavern_tones"],
        ),
    }
    return presets.get(pack_id, CultureConstraints(
        soft_preferences=[f"follow_{pack_id}_visual_guidelines"],
    ))


def _build_display_name(surface: str, pack_id: str) -> str:
    if pack_id.startswith("cn_"):
        return surface
    return surface


def _build_prompt_template_refs(
    ent: CanonicalEntityFull,
    pack_id: str,
    char_role: str,
) -> list[str]:
    """Generate prompt template reference hints for downstream Prompt Planner."""
    refs: list[str] = []
    etype = ent.entity_type
    root_short = ent.canonical_entity_root.replace(".", "_")
    specific_short = ent.canonical_entity_specific.replace(".", "_") if ent.canonical_entity_specific else root_short

    # Base template: {pack}_{entity_type}_{specific}_v1
    base_ref = f"{pack_id}_{specific_short}_v1"
    refs.append(base_ref)

    # Role-specific template for characters
    if etype == "character" and char_role:
        role_safe = re.sub(r"[^a-zA-Z0-9_\u4e00-\u9fff]", "_", char_role).strip("_")
        refs.append(f"{pack_id}_character_{role_safe}_v1")

    # Scene template with mood if available
    if etype == "scene_place":
        mood = ent.attributes.get("mood", "")
        if mood:
            refs.append(f"{pack_id}_scene_{mood}_v1")

    return refs


def _build_asset_refs(ent: CanonicalEntityFull, pack_id: str) -> list[str]:
    """Generate asset reference hints for downstream Asset Matcher."""
    refs: list[str] = []
    etype = ent.entity_type
    specific = ent.canonical_entity_specific or ent.canonical_entity_root
    specific_last = specific.rsplit(".", 1)[-1] if specific else etype

    # Primary asset ref
    refs.append(f"ref_{pack_id}_{specific_last}_01")

    # LoRA / style ref for visual entity types
    if etype in ("scene_place", "character", "costume"):
        refs.append(f"lora_{pack_id}_{etype}_v2")

    return refs


def _build_kb_suggestions(
    variant_mapping: list[EntityVariantMapping],
    pack_id: str,
) -> list[KBSuggestion]:
    """Build knowledge-base recommendation hints for downstream skill use."""
    suggestions: list[KBSuggestion] = []
    for vm in variant_mapping:
        # Asset search hint
        suggestions.append(KBSuggestion(
            entity_uid=vm.entity_uid,
            suggestion_type="asset_search",
            value=f"search:{vm.selected_variant_id}",
            source="variant_mapping",
            confidence=vm.match_confidence,
        ))
        # Prompt hint from visual traits
        if vm.visual_traits:
            trait_hint = ", ".join(vm.visual_traits[:5])
            suggestions.append(KBSuggestion(
                entity_uid=vm.entity_uid,
                suggestion_type="prompt_hint",
                value=f"include traits: {trait_hint}",
                source="culture_trait",
                confidence=round(vm.match_confidence * 0.9, 4),
            ))
        # LoRA hint for scene/character
        if vm.canonical_entity_specific and any(
            t in vm.canonical_entity_specific for t in ("place", "character")
        ):
            suggestions.append(KBSuggestion(
                entity_uid=vm.entity_uid,
                suggestion_type="lora_hint",
                value=f"lora_{pack_id}_{vm.canonical_entity_specific.split('.')[0]}_v2",
                source="variant_mapping",
                confidence=round(vm.match_confidence * 0.85, 4),
            ))
    return suggestions


def _build_feedback_anchor_tags(
    conflicts: list[ConflictItem],
    unresolved: list[UnresolvedEntity],
) -> FeedbackAnchorTags:
    """Build tags for SKILL 13 feedback evolution loop."""
    culture_mismatch: list[str] = []
    naming_inconsistency: list[str] = []
    signage_conflict: list[str] = []

    for c in conflicts:
        tag = f"{c.entity_uid}:{c.conflict_type}"
        if c.conflict_type == "LANGUAGE_SIGNAGE_CONFLICT":
            signage_conflict.append(tag)
        elif c.conflict_type in ("ERA_CONFLICT", "GENRE_CONFLICT", "COSTUME_CONFLICT",
                                  "PROP_REGION_CONFLICT", "ARCHITECTURE_CONFLICT",
                                  "SOCIAL_NORM_CONFLICT"):
            culture_mismatch.append(tag)

    for u in unresolved:
        if "ambiguity" in u.reason or "inconsistency" in u.reason.lower():
            naming_inconsistency.append(f"{u.entity_uid}:{u.reason.split(':')[0]}")

    return FeedbackAnchorTags(
        culture_mismatch=culture_mismatch,
        naming_inconsistency=naming_inconsistency,
        signage_style_conflict=signage_conflict,
    )
