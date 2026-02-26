"""SKILL 10: PromptPlannerService — Full implementation.

Reference: SKILL_10_PROMPT_PLANNER.md
State machine (§19):
  INIT → PRECHECKING → PRECHECK_READY → BUILDING_GLOBAL_CONSTRAINTS →
  GLOBAL_CONSTRAINTS_READY → BUILDING_SHOT_PROMPT_LAYERS →
  BUILDING_MICROSHOT_PROMPT_LAYERS → BUILDING_MODEL_VARIANTS →
  BUILDING_PRESET_MAPPING_HINTS → FALLBACK_PROCESSING →
  ASSEMBLING_PROMPT_PLAN → READY_FOR_PROMPT_EXECUTION | REVIEW_REQUIRED | FAILED
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from ainern2d_shared.schemas.skills.skill_10 import (
    AssemblyRules,
    BackendCapability,
    DerivedFrom,
    FallbackPromptAction,
    GlobalConsistencyAnchors,
    GlobalPromptConstraints,
    KeyframePrompt,
    LengthEstimate,
    MicroshotOverrides,
    MicroshotPromptPlan,
    ModelVariant,
    NegativeLayers,
    ParameterHints,
    PresetMappingHints,
    PresetModeMapping,
    PromptConsistencyScore,
    PromptLayers,
    PromptPlanSummary,
    RAGRecipeContext,
    ReviewRequiredItem,
    ShotPromptPlan,
    Skill10FeatureFlags,
    Skill10Input,
    Skill10Output,
    Skill10UserOverrides,
)
from ainern2d_shared.services.base_skill import BaseSkillService, SkillContext

# ── Token limits per backend (§4 ComfyUI/SDXL/Flux) ─────────────────────────
_BACKEND_TOKEN_LIMITS: dict[str, int] = {
    "comfyui": 77,
    "sdxl": 154,   # CLIP-G 77 + CLIP-L 77
    "flux": 256,   # T5 encoder
}

# ── Layer priority weights (higher = kept when trimming) ─────────────────────
_LAYER_PRIORITIES: dict[str, float] = {
    "quality": 0.9,
    "base": 0.85,
    "entity": 0.8,
    "cultural": 0.75,
    "shot": 0.7,
    "lighting_mood": 0.6,
    "motion": 0.55,
    "consistency_anchor": 0.5,
}

# ── Culture-aware negative prompts (§13) ─────────────────────────────────────
_CULTURE_NEGATIVES: dict[str, list[str]] = {
    "cn_wuxia": [
        "modern architecture", "western furniture", "neon signs",
        "modern typography", "western pub taps",
    ],
    "cn_xianxia": [
        "modern technology", "western elements", "realistic urban",
        "modern vehicles",
    ],
    "jp_anime": ["photorealistic", "western medieval", "chinese historical"],
    "en_western_fantasy": [
        "modern technology", "asian elements", "neon", "cars", "smartphones",
    ],
}

# ── Global quality negatives (§13.1) ─────────────────────────────────────────
_GLOBAL_NEGATIVES: list[str] = [
    "low quality", "blurry", "deformed", "watermark", "signature",
    "extra limbs", "deformed anatomy", "bad proportions",
]

# ── Culture style fragments (§6.2 Cultural Layer) ────────────────────────────
_CULTURE_STYLE: dict[str, list[str]] = {
    "cn_wuxia": [
        "ancient Chinese wuxia aesthetic", "jianghu atmosphere",
        "traditional ink style", "cinematic",
    ],
    "cn_xianxia": [
        "xianxia cultivation aesthetic", "ethereal glow",
        "mystical mountains", "cinematic",
    ],
    "jp_anime": [
        "anime style", "detailed cel shading",
        "vibrant colors", "japanese aesthetic",
    ],
    "en_western_fantasy": [
        "medieval fantasy", "epic cinematic",
        "dramatic lighting", "detailed",
    ],
}

# ── Model mode keyframe slots (§8 / §16.2) ──────────────────────────────────
_MODE_KEYFRAME_SLOTS: dict[str, list[str]] = {
    "T2I": [],
    "I2V_START_END": ["start", "end"],
    "I2V_START_MID_END": ["start", "mid", "end"],
    "I2V_MULTI_KEYFRAME": ["start", "mid_1", "mid_2", "end"],
    "VIDEO_TEXT_DRIVEN": [],
    "HYBRID": ["start", "end"],
}

# ── Supported modes per backend ──────────────────────────────────────────────
_BACKEND_MODES: dict[str, list[str]] = {
    "comfyui": [
        "T2I", "I2V_START_END", "I2V_START_MID_END",
        "I2V_MULTI_KEYFRAME", "HYBRID",
    ],
    "sdxl": ["T2I"],
    "flux": ["T2I", "VIDEO_TEXT_DRIVEN"],
}

# ── Mode downgrade chain (§D3) ──────────────────────────────────────────────
_MODE_DOWNGRADE: dict[str, str] = {
    "I2V_MULTI_KEYFRAME": "I2V_START_MID_END",
    "I2V_START_MID_END": "I2V_START_END",
    "I2V_START_END": "T2I",
    "HYBRID": "T2I",
    "VIDEO_TEXT_DRIVEN": "T2I",
}


def _estimate_tokens(text: str) -> int:
    """Rough token count: count comma-separated fragments."""
    if not text:
        return 0
    return max(1, len(text.split(", ")))


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.md5(":".join(parts).encode()).hexdigest()[:8]
    return f"{prefix}_{digest}"


# ══════════════════════════════════════════════════════════════════════════════


class PromptPlannerService(BaseSkillService[Skill10Input, Skill10Output]):
    """SKILL 10 — Prompt Planner.

    Implements the full 8-phase pipeline from §9:
      P1 Precheck → P2 Global Constraints → P3 Shot Layers →
      P4 Micro-shot Layers → P5 Model Variants → P6 Preset Mapping →
      P7 Fallback/Degrade → P8 Assembly
    """

    skill_id = "skill_10"
    skill_name = "PromptPlannerService"

    def __init__(self, db: Session) -> None:
        super().__init__(db)

    # ── Public entry ─────────────────────────────────────────────────────

    def execute(self, inp: Skill10Input, ctx: SkillContext) -> Skill10Output:
        warnings: list[str] = []
        review_items: list[ReviewRequiredItem] = []
        fallback_actions: list[FallbackPromptAction] = []
        ff = inp.feature_flags
        overrides = inp.user_overrides
        backend = inp.backend_capability
        token_limit = _BACKEND_TOKEN_LIMITS.get(
            backend.backend_id, backend.max_prompt_tokens,
        )

        # ── P1: Precheck (§9 [P1]) ──────────────────────────────────
        self._record_state(ctx, "INIT", "PRECHECKING")
        blocking = self._precheck(inp)
        if blocking:
            self._record_state(ctx, "PRECHECKING", "FAILED")
            return Skill10Output(status="failed", warnings=blocking)
        self._record_state(ctx, "PRECHECKING", "PRECHECK_READY")

        # ── P2: Global Constraints (§9 [P2]) ────────────────────────
        self._record_state(ctx, "PRECHECK_READY", "BUILDING_GLOBAL_CONSTRAINTS")
        gc = self._build_global_constraints(inp, overrides, ff)
        self._record_state(
            ctx, "BUILDING_GLOBAL_CONSTRAINTS", "GLOBAL_CONSTRAINTS_READY",
        )

        # ── Extract upstream data ────────────────────────────────────
        shot_render_plans = _extract_list(inp.visual_render_plan, "shot_render_plans")
        microshot_render_plans = _extract_list(
            inp.visual_render_plan, "microshot_render_plans",
        )
        entity_variant_mapping = _extract_list(
            inp.entity_canonicalization_result, "entity_variant_mapping",
        )
        entity_asset_matches = _extract_list(
            inp.asset_match_result, "entity_asset_matches",
        )
        culture_constraints = inp.entity_canonicalization_result.get(
            "culture_constraints", {},
        )
        shots = _extract_list(inp.shot_plan, "shots")

        entity_lookup = _build_lookup(entity_variant_mapping, "entity_uid")
        asset_lookup = _build_lookup(entity_asset_matches, "entity_uid")
        shot_info_lookup = {s.get("shot_id", ""): s for s in shots}

        # ── P3: Shot-level Prompt Layers (§9 [P3]) ──────────────────
        self._record_state(
            ctx, "GLOBAL_CONSTRAINTS_READY", "BUILDING_SHOT_PROMPT_LAYERS",
        )
        shot_plans: list[ShotPromptPlan] = []
        for srp in shot_render_plans:
            plan = self._build_shot_prompt_plan(
                srp, shot_info_lookup, entity_lookup, asset_lookup,
                culture_constraints, gc, inp, token_limit, ff, overrides,
            )
            shot_plans.append(plan)
            warnings.extend(plan.warnings)

        # ── P4: Micro-shot Prompt Layers (§9 [P4]) ──────────────────
        ms_plans: list[MicroshotPromptPlan] = []
        shot_plan_lookup = {sp.shot_id: sp for sp in shot_plans}
        if microshot_render_plans:
            self._record_state(
                ctx, "BUILDING_SHOT_PROMPT_LAYERS",
                "BUILDING_MICROSHOT_PROMPT_LAYERS",
            )
            for msrp in microshot_render_plans:
                ms_plan = self._build_microshot_prompt_plan(
                    msrp, shot_plan_lookup, gc, token_limit, ff,
                )
                ms_plans.append(ms_plan)
                warnings.extend(ms_plan.warnings)
            prev_state = "BUILDING_MICROSHOT_PROMPT_LAYERS"
        else:
            prev_state = "BUILDING_SHOT_PROMPT_LAYERS"

        # ── P5: Model Variants (§9 [P5]) ────────────────────────────
        self._record_state(ctx, prev_state, "BUILDING_MODEL_VARIANTS")
        model_variants: list[ModelVariant] = []
        for sp in shot_plans:
            model_variants.extend(
                self._build_model_variants(sp, "shot", inp.model_target, backend, gc, ff),
            )
        for msp in ms_plans:
            model_variants.extend(
                self._build_model_variants_microshot(
                    msp, shot_plan_lookup.get(msp.parent_shot_id),
                    inp.model_target, backend, gc, ff,
                ),
            )

        # ── P6: Preset Mapping Hints (§9 [P6]) ─────────────────────
        self._record_state(ctx, "BUILDING_MODEL_VARIANTS", "BUILDING_PRESET_MAPPING_HINTS")
        preset_hints = self._build_preset_mapping_hints(
            model_variants, backend, inp.comfyui_preset_catalog,
        )

        # ── P7: Fallback & Degradation (§9 [P7]) ───────────────────
        self._record_state(ctx, "BUILDING_PRESET_MAPPING_HINTS", "FALLBACK_PROCESSING")
        for sp in shot_plans:
            fallback_actions.extend(self._apply_fallback(sp, token_limit, ff))
        for msp in ms_plans:
            fallback_actions.extend(self._apply_fallback_microshot(msp, token_limit))

        # Token budget enforcement
        for sp in shot_plans:
            self._enforce_token_budget(sp, token_limit, ff)
        for msp in ms_plans:
            self._update_token_count(msp)

        # ── Consistency Scoring ──────────────────────────────────────
        consistency_scores = self._score_consistency(shot_plans)
        for cs in consistency_scores:
            if cs.overall_score < 0.6:
                review_items.append(ReviewRequiredItem(
                    target_type="scene",
                    target_id=cs.scene_id,
                    reason=f"Low consistency score: {cs.overall_score:.2f}",
                    severity="high",
                ))

        # ── P8: Assembly (§9 [P8]) ──────────────────────────────────
        self._record_state(ctx, "FALLBACK_PROCESSING", "ASSEMBLING_PROMPT_PLAN")

        status = "ready_for_prompt_execution"
        if review_items:
            status = "review_required"
            self._record_state(ctx, "ASSEMBLING_PROMPT_PLAN", "REVIEW_REQUIRED")
        else:
            self._record_state(
                ctx, "ASSEMBLING_PROMPT_PLAN", "READY_FOR_PROMPT_EXECUTION",
            )

        avg_cs = 1.0
        if consistency_scores:
            avg_cs = round(
                sum(c.overall_score for c in consistency_scores)
                / len(consistency_scores), 3,
            )

        summary = PromptPlanSummary(
            total_shots=len(shot_plans),
            total_microshots=len(ms_plans),
            model_variants_generated=len(model_variants),
            fallback_prompt_actions=len(fallback_actions),
            review_required=len(review_items),
            avg_consistency_score=avg_cs,
        )

        logger.info(
            f"[{self.skill_id}] completed | run={ctx.run_id} "
            f"shots={summary.total_shots} microshots={summary.total_microshots} "
            f"variants={summary.model_variants_generated} status={status}"
        )

        return Skill10Output(
            version=ff.prompt_format_version,
            status=status,
            prompt_plan_summary=summary,
            global_prompt_constraints=gc,
            shot_prompt_plans=shot_plans,
            microshot_prompt_plans=ms_plans,
            model_variants=model_variants,
            preset_mapping_hints=preset_hints,
            fallback_prompt_actions=fallback_actions,
            consistency_scores=consistency_scores,
            warnings=warnings,
            review_required_items=review_items,
        )

    # ── P1: Precheck ─────────────────────────────────────────────────────

    def _precheck(self, inp: Skill10Input) -> list[str]:
        """Validate required upstream outputs (§9 [P1])."""
        issues: list[str] = []
        if not inp.visual_render_plan:
            issues.append(
                "PROMPT-PRECHECK-001: missing visual_render_plan (SKILL 09)",
            )
        if not inp.entity_canonicalization_result:
            issues.append(
                "PROMPT-PRECHECK-002: missing entity_canonicalization_result (SKILL 07)",
            )
        if not inp.asset_match_result:
            issues.append(
                "PROMPT-PRECHECK-003: missing asset_match_result (SKILL 08)",
            )
        for src in [
            inp.entity_canonicalization_result,
            inp.asset_match_result,
            inp.visual_render_plan,
        ]:
            s = src.get("status", "")
            if s and "failed" in s.lower():
                issues.append(f"PROMPT-PRECHECK-004: upstream status is '{s}'")
        return issues

    # ── P2: Global Constraints (§17.2) ───────────────────────────────────

    def _build_global_constraints(
        self,
        inp: Skill10Input,
        overrides: Skill10UserOverrides,
        ff: Skill10FeatureFlags,
    ) -> GlobalPromptConstraints:
        culture_pack = inp.entity_canonicalization_result.get(
            "selected_culture_pack", {},
        )
        pack_id = (
            culture_pack.get("id", "generic")
            if isinstance(culture_pack, dict)
            else str(culture_pack)
        )
        culture_cst = inp.entity_canonicalization_result.get(
            "culture_constraints", {},
        )

        style_mode = overrides.style_override or inp.style_mode or "cinematic"
        quality = overrides.quality_preset_override or inp.quality_profile or "standard"

        # ── Positive fragments ───────────────────────────────────────
        pos = list(_CULTURE_STYLE.get(pack_id, ["high quality", "detailed", "cinematic"]))
        pos.append(f"{style_mode} style")
        pos.extend(culture_cst.get("visual_do", []))
        if inp.recipe_context and inp.recipe_context.hard_constraints:
            pos.extend(inp.recipe_context.hard_constraints)
        if inp.recipe_context and inp.recipe_context.soft_hints:
            pos.extend(inp.recipe_context.soft_hints)
        if overrides.forced_culture_fragments:
            pos.extend(overrides.forced_culture_fragments)

        # ── Negative fragments ───────────────────────────────────────
        neg = list(_GLOBAL_NEGATIVES)
        neg.extend(_CULTURE_NEGATIVES.get(pack_id, []))
        neg.extend(culture_cst.get("visual_dont", []))
        neg.extend(culture_cst.get("hard_constraints", []))
        if overrides.negative_prompt_append:
            neg.extend(overrides.negative_prompt_append)

        # ── Consistency anchors ──────────────────────────────────────
        scene_ids: list[str] = []
        char_ids: list[str] = []
        for ev in _extract_list(
            inp.entity_canonicalization_result, "entity_variant_mapping",
        ):
            uid = ev.get("entity_uid", "")
            etype = ev.get("entity_type", "").lower()
            if "scene" in etype or "location" in etype:
                scene_ids.append(uid)
            elif "character" in etype or "person" in etype:
                char_ids.append(uid)

        return GlobalPromptConstraints(
            selected_culture_pack=pack_id,
            global_positive_fragments=_dedup(pos),
            global_negative_fragments=_dedup(neg),
            style_mode=style_mode,
            quality_profile=quality,
            global_consistency_anchors=GlobalConsistencyAnchors(
                scene_anchor_ids=scene_ids,
                character_anchor_ids=char_ids,
            ),
            user_overrides_applied=[
                k for k, v in overrides.model_dump().items() if v
            ],
            rag_recipe_applied=inp.recipe_context,
        )

    # ── P3: Shot Prompt Layer Build (§9 [P3] / §6) ──────────────────────

    def _build_shot_prompt_plan(
        self,
        srp: dict,
        shot_info: dict[str, dict],
        entity_lookup: dict[str, dict],
        asset_lookup: dict[str, dict],
        culture_constraints: dict,
        gc: GlobalPromptConstraints,
        inp: Skill10Input,
        token_limit: int,
        ff: Skill10FeatureFlags,
        overrides: Skill10UserOverrides,
    ) -> ShotPromptPlan:
        shot_id = srp.get("shot_id", "")
        scene_id = srp.get("scene_id", "")
        criticality = srp.get("criticality", "normal")
        motion_level = srp.get("motion_level", "MEDIUM")
        beat_alignment = srp.get("beat_alignment_strength", "medium")
        detail = shot_info.get(shot_id, {})
        shot_goal = detail.get("goal", detail.get("narrative_purpose", ""))
        shot_type = detail.get("shot_type", "")
        camera = detail.get("camera", detail.get("camera_angle", ""))
        char_ids = detail.get("character_ids", detail.get("entities", []))
        warnings: list[str] = []

        # ── 1) Base Layer ────────────────────────────────────────────
        base: list[str] = []
        if shot_goal:
            base.append(shot_goal)
        elif shot_type:
            base.append(f"{shot_type} shot")
        else:
            base.append(f"shot {shot_id}")

        # ── 2) Cultural Layer ────────────────────────────────────────
        cultural = list(gc.global_positive_fragments[:4])

        # ── 3) Entity Layer + LoRA / embedding injection ─────────────
        entity: list[str] = []
        lora_triggers: list[str] = []
        embedding_tokens: list[str] = []
        entity_negs: list[str] = []
        uid_list = _normalize_uid_list(char_ids)
        for uid in uid_list:
            ev = entity_lookup.get(uid, {})
            asset = asset_lookup.get(uid, {})
            desc = ev.get(
                "variant_display_name", ev.get("surface_form", uid),
            )
            traits = ev.get("visual_traits", [])
            if desc:
                entity.append(desc)
            if traits:
                entity.extend(traits[:3])
            if uid in overrides.forced_entity_descriptions:
                entity.append(overrides.forced_entity_descriptions[uid])
            # LoRA / embedding injection
            if ff.enable_lora_injection:
                for ref in ev.get("asset_refs", []):
                    if "lora" in str(ref).lower():
                        lora_triggers.append(ref)
                lora_triggers.extend(asset.get("lora_refs", []))
                embedding_tokens.extend(asset.get("embedding_refs", []))
            entity_negs.extend(ev.get("avoid_trait_drift", []))

        # ── 4) Shot Layer (camera / composition) ─────────────────────
        shot_layer: list[str] = []
        if camera:
            shot_layer.append(camera)
        if shot_type:
            shot_layer.append(shot_type)
        comp = detail.get("composition", "")
        if comp:
            shot_layer.append(comp)

        # ── 5) Motion Layer ──────────────────────────────────────────
        motion: list[str] = []
        m_desc = srp.get("motion_description", "")
        if m_desc:
            motion.append(m_desc)
        if motion_level == "HIGH":
            motion.append("dynamic motion, readable action poses")
        elif motion_level == "LOW":
            motion.append("subtle movement, atmospheric")
        if beat_alignment == "high":
            motion.append("impact-driven movement at beat points")

        motion_negs: list[str] = []
        if motion_level == "HIGH":
            motion_negs.extend([
                "unreadable overlapping poses", "motion blur on key subject",
            ])

        # ── 6) Lighting & Mood Layer ─────────────────────────────────
        lighting: list[str] = []
        mood = srp.get("mood", detail.get("mood", ""))
        light_desc = srp.get("lighting", detail.get("lighting", ""))
        if mood:
            lighting.append(mood)
        if light_desc:
            lighting.append(light_desc)
        palette = srp.get("color_palette", detail.get("color_palette", ""))
        if palette:
            lighting.append(palette)

        # ── 7) Quality Layer ─────────────────────────────────────────
        quality = self._build_quality_layer(
            gc.quality_profile, criticality, motion_level,
        )

        # ── 8) Consistency Anchor Layer ──────────────────────────────
        anchors: list[str] = []
        anchor_ids: list[str] = []
        for uid in uid_list:
            anchors.append(f"character_anchor:{uid}")
            anchor_ids.append(uid)
        if scene_id:
            anchors.append(f"scene_anchor:{scene_id}")
            anchor_ids.append(scene_id)

        # ── 9) Negative Layers ───────────────────────────────────────
        neg_layers = NegativeLayers(
            global_negative=list(gc.global_negative_fragments[:8]),
            culture_negative=_CULTURE_NEGATIVES.get(
                gc.selected_culture_pack, [],
            )[:6],
            entity_negative=entity_negs[:4],
            motion_negative=motion_negs[:4],
            model_specific_negative=[],
        )

        prompt_layers = PromptLayers(
            base=base,
            cultural=cultural,
            entity=entity,
            shot=shot_layer,
            motion=motion,
            lighting_mood=lighting,
            quality=quality,
            consistency_anchor=anchors,
        )

        token_used = _estimate_tokens(
            ", ".join(_all_positive_fragments(prompt_layers)),
        )

        return ShotPromptPlan(
            shot_id=shot_id,
            scene_id=scene_id,
            criticality=criticality,
            prompt_layers=prompt_layers,
            negative_layers=neg_layers,
            consistency_anchors=anchor_ids,
            derived_from=DerivedFrom(
                asset_match_refs=uid_list,
                visual_render_plan_ref=shot_id,
            ),
            assembly_rules=AssemblyRules(),
            lora_triggers=_dedup(lora_triggers),
            embedding_tokens=_dedup(embedding_tokens),
            token_budget_used=token_used,
            token_budget_limit=token_limit,
            warnings=warnings,
        )

    # ── P4: Micro-shot Prompt Layer Build (§9 [P4]) ─────────────────────

    def _build_microshot_prompt_plan(
        self,
        msrp: dict,
        shot_lookup: dict[str, ShotPromptPlan],
        gc: GlobalPromptConstraints,
        token_limit: int,
        ff: Skill10FeatureFlags,
    ) -> MicroshotPromptPlan:
        ms_id = msrp.get("microshot_id", "")
        parent_id = msrp.get("parent_shot_id", msrp.get("shot_id", ""))
        parent = shot_lookup.get(parent_id)
        alignment_pts = msrp.get("alignment_points", [])
        criticality = msrp.get(
            "criticality", parent.criticality if parent else "normal",
        )

        motion_ov: list[str] = []
        if msrp.get("motion_description"):
            motion_ov.append(msrp["motion_description"])
        if msrp.get("key_action"):
            motion_ov.append(msrp["key_action"])

        shot_ov: list[str] = []
        if msrp.get("framing"):
            shot_ov.append(msrp["framing"])

        quality_ov: list[str] = []
        if msrp.get("motion_level", "") == "HIGH":
            quality_ov.append("action readability first")

        overrides_obj = MicroshotOverrides(
            motion=motion_ov, shot=shot_ov, quality=quality_ov,
        )

        warnings: list[str] = []
        if parent:
            merged = PromptLayers(
                base=list(parent.prompt_layers.base),
                cultural=list(parent.prompt_layers.cultural),
                entity=list(parent.prompt_layers.entity),
                shot=shot_ov or list(parent.prompt_layers.shot),
                motion=motion_ov or list(parent.prompt_layers.motion),
                lighting_mood=list(parent.prompt_layers.lighting_mood),
                quality=quality_ov or list(parent.prompt_layers.quality),
                consistency_anchor=list(parent.prompt_layers.consistency_anchor),
            )
            neg = NegativeLayers(
                global_negative=list(parent.negative_layers.global_negative),
                culture_negative=list(parent.negative_layers.culture_negative),
                entity_negative=list(parent.negative_layers.entity_negative),
                motion_negative=list(parent.negative_layers.motion_negative)
                + ["action collapse", "unreadable motion"],
                model_specific_negative=list(
                    parent.negative_layers.model_specific_negative,
                ),
            )
            lora = list(parent.lora_triggers)
            embed = list(parent.embedding_tokens)
        else:
            merged = PromptLayers()
            neg = NegativeLayers(
                global_negative=list(gc.global_negative_fragments),
            )
            lora, embed = [], []
            warnings.append(
                f"PROMPT-MS-001: parent shot '{parent_id}' not found "
                f"for microshot '{ms_id}'",
            )

        token_used = _estimate_tokens(
            ", ".join(_all_positive_fragments(merged)),
        )

        return MicroshotPromptPlan(
            microshot_id=ms_id,
            parent_shot_id=parent_id,
            criticality=criticality,
            inherits_from_shot_layers=parent is not None,
            overrides=overrides_obj,
            prompt_layers=merged,
            negative_layers=neg,
            alignment_points=alignment_pts,
            lora_triggers=lora,
            embedding_tokens=embed,
            token_budget_used=token_used,
            warnings=warnings,
        )

    # ── P5: Model Variant Build (§9 [P5] / §8) ─────────────────────────

    def _build_model_variants(
        self,
        plan: ShotPromptPlan,
        target_type: str,
        model_target: str,
        backend: BackendCapability,
        gc: GlobalPromptConstraints,
        ff: Skill10FeatureFlags,
    ) -> list[ModelVariant]:
        if not ff.enable_model_specific_variants:
            model_target = "T2I"

        mode = _resolve_mode(model_target, backend)
        positive = _assemble_positive(
            plan.prompt_layers, plan.assembly_rules,
            plan.lora_triggers, plan.embedding_tokens, ff,
        )
        negative = _assemble_negative(plan.negative_layers, plan.assembly_rules)
        kf = self._build_keyframe_prompts(plan, mode)
        ph = self._build_parameter_hints(plan, mode, gc)

        return [ModelVariant(
            variant_id=_stable_id("PV", plan.shot_id, mode),
            target_type=target_type,
            target_id=plan.shot_id,
            model_mode=mode,
            positive_prompt=positive,
            negative_prompt=negative,
            keyframe_prompts=kf,
            parameter_hints=ph,
            length_estimate=LengthEstimate(
                positive_tokens=_estimate_tokens(positive),
                negative_tokens=_estimate_tokens(negative),
                positive_chars=len(positive),
                negative_chars=len(negative),
            ),
            preset_mapping_ref=f"{mode.lower()}_v1",
        )]

    def _build_model_variants_microshot(
        self,
        ms: MicroshotPromptPlan,
        parent: ShotPromptPlan | None,
        model_target: str,
        backend: BackendCapability,
        gc: GlobalPromptConstraints,
        ff: Skill10FeatureFlags,
    ) -> list[ModelVariant]:
        mode = _resolve_mode(model_target, backend)
        rules = parent.assembly_rules if parent else AssemblyRules()
        positive = _assemble_positive(
            ms.prompt_layers, rules,
            ms.lora_triggers, ms.embedding_tokens, ff,
        )
        negative = _assemble_negative(ms.negative_layers, rules)

        return [ModelVariant(
            variant_id=_stable_id("PV", ms.microshot_id, mode),
            target_type="microshot",
            target_id=ms.microshot_id,
            model_mode=mode,
            positive_prompt=positive,
            negative_prompt=negative,
            keyframe_prompts=[],
            parameter_hints=ParameterHints(
                motion_strength="high" if ms.criticality == "critical" else "medium",
            ),
            length_estimate=LengthEstimate(
                positive_tokens=_estimate_tokens(positive),
                negative_tokens=_estimate_tokens(negative),
                positive_chars=len(positive),
                negative_chars=len(negative),
            ),
            preset_mapping_ref=f"{mode.lower()}_v1",
        )]

    # ── P6: Preset Mapping Hints (§9 [P6] / §16) ───────────────────────

    def _build_preset_mapping_hints(
        self,
        variants: list[ModelVariant],
        backend: BackendCapability,
        catalog: dict,
    ) -> PresetMappingHints:
        modes_used = {v.model_mode for v in variants}
        per_mode: dict[str, PresetModeMapping] = {}
        fallback_map: dict[str, PresetModeMapping] = {}

        for mode in modes_used:
            slots = _MODE_KEYFRAME_SLOTS.get(mode, [])
            raw = catalog.get(mode, f"{mode.lower()}_default_v1")
            preset_id = (
                raw.get("preset_id", f"{mode.lower()}_default_v1")
                if isinstance(raw, dict) else str(raw)
            )
            per_mode[mode] = PresetModeMapping(
                preset_id_hint=preset_id,
                keyframe_prompt_slots=slots,
                reference_image_refs=["scene_anchor", "character_anchor"],
                style_lora_refs=[],
                control_hints={"backend": backend.backend_id},
            )
            supported = _BACKEND_MODES.get(
                backend.backend_id, backend.supported_modes,
            )
            if mode not in supported:
                fb_mode = _MODE_DOWNGRADE.get(mode, "T2I")
                fallback_map[mode] = PresetModeMapping(
                    preset_id_hint=f"{fb_mode.lower()}_fallback_v1",
                    keyframe_prompt_slots=_MODE_KEYFRAME_SLOTS.get(fb_mode, []),
                    reference_image_refs=["scene_anchor", "character_anchor"],
                )

        return PresetMappingHints(
            default_mappings={
                "positive_prompt_field": "prompt",
                "negative_prompt_field": "negative_prompt",
            },
            per_model_mode_mappings=per_mode,
            fallback_mappings=fallback_map,
        )

    # ── P7: Fallback & Degradation (§9 [P7]) ────────────────────────────

    def _apply_fallback(
        self,
        plan: ShotPromptPlan,
        token_limit: int,
        ff: Skill10FeatureFlags,
    ) -> list[FallbackPromptAction]:
        if not ff.enable_prompt_fallback_variants:
            return []

        frags = _all_positive_fragments(plan.prompt_layers)
        total = _estimate_tokens(", ".join(frags))
        if total <= token_limit:
            return []

        actions: list[FallbackPromptAction] = []
        before = ", ".join(frags)[:120]

        # Level 1: simplified_prompt — drop low-priority layers
        plan.prompt_layers.consistency_anchor = (
            plan.prompt_layers.consistency_anchor[:1]
        )
        total = _estimate_tokens(
            ", ".join(_all_positive_fragments(plan.prompt_layers)),
        )
        actions.append(FallbackPromptAction(
            target_type="shot", target_id=plan.shot_id,
            action="drop_optional_detail",
            reason_tags=["token_over_budget", "level_1_simplify"],
            before_summary=before,
            after_summary=", ".join(
                _all_positive_fragments(plan.prompt_layers),
            )[:120],
        ))

        # Level 2: simplified_prompt — trim entity + motion + lighting
        if total > token_limit:
            plan.prompt_layers.entity = plan.prompt_layers.entity[:2]
            plan.prompt_layers.motion = plan.prompt_layers.motion[:1]
            plan.prompt_layers.lighting_mood = (
                plan.prompt_layers.lighting_mood[:1]
            )
            total = _estimate_tokens(
                ", ".join(_all_positive_fragments(plan.prompt_layers)),
            )
            actions.append(FallbackPromptAction(
                target_type="shot", target_id=plan.shot_id,
                action="simplify_entity_layer",
                reason_tags=["token_over_budget", "level_2_simplify"],
                before_summary=before,
                after_summary=", ".join(
                    _all_positive_fragments(plan.prompt_layers),
                )[:120],
            ))

        # Level 3: minimal_prompt — quality + character + scene only
        if total > token_limit:
            plan.prompt_layers.cultural = []
            plan.prompt_layers.shot = plan.prompt_layers.shot[:1]
            plan.prompt_layers.motion = []
            plan.prompt_layers.lighting_mood = []
            plan.prompt_layers.consistency_anchor = []
            actions.append(FallbackPromptAction(
                target_type="shot", target_id=plan.shot_id,
                action="use_generic_cultural_fragments",
                reason_tags=["token_over_budget", "level_3_minimal"],
                before_summary=before,
                after_summary=", ".join(
                    _all_positive_fragments(plan.prompt_layers),
                )[:120],
            ))

        return actions

    def _apply_fallback_microshot(
        self,
        ms: MicroshotPromptPlan,
        token_limit: int,
    ) -> list[FallbackPromptAction]:
        frags = _all_positive_fragments(ms.prompt_layers)
        total = _estimate_tokens(", ".join(frags))
        if total <= token_limit:
            return []

        before = ", ".join(frags)[:120]
        ms.prompt_layers.cultural = ms.prompt_layers.cultural[:1]
        ms.prompt_layers.lighting_mood = ms.prompt_layers.lighting_mood[:1]
        ms.prompt_layers.consistency_anchor = []
        return [FallbackPromptAction(
            target_type="microshot", target_id=ms.microshot_id,
            action="simplify_entity_layer",
            reason_tags=["token_over_budget", "microshot_simplify"],
            before_summary=before,
            after_summary=", ".join(
                _all_positive_fragments(ms.prompt_layers),
            )[:120],
        )]

    # ── Token Budget Enforcement ─────────────────────────────────────────

    def _enforce_token_budget(
        self,
        plan: ShotPromptPlan,
        limit: int,
        ff: Skill10FeatureFlags,
    ) -> None:
        frags = _all_positive_fragments(plan.prompt_layers)
        total = _estimate_tokens(", ".join(frags))
        plan.token_budget_used = total
        plan.token_budget_limit = limit

        if not ff.token_budget_strict or total <= limit:
            return

        # Trim lowest-priority layers first
        for layer_name, _ in sorted(
            _LAYER_PRIORITIES.items(), key=lambda x: x[1],
        ):
            if total <= limit:
                break
            layer_list: list[str] = getattr(plan.prompt_layers, layer_name, [])
            if layer_list:
                removed = layer_list.pop()
                total = _estimate_tokens(
                    ", ".join(_all_positive_fragments(plan.prompt_layers)),
                )
                plan.warnings.append(
                    f"PROMPT-BUDGET-001: trimmed '{removed}' from {layer_name}",
                )
        plan.token_budget_used = total

    @staticmethod
    def _update_token_count(ms: MicroshotPromptPlan) -> None:
        ms.token_budget_used = _estimate_tokens(
            ", ".join(_all_positive_fragments(ms.prompt_layers)),
        )

    # ── Consistency Scoring ──────────────────────────────────────────────

    @staticmethod
    def _score_consistency(
        plans: list[ShotPromptPlan],
    ) -> list[PromptConsistencyScore]:
        scene_groups: dict[str, list[ShotPromptPlan]] = defaultdict(list)
        for p in plans:
            if p.scene_id:
                scene_groups[p.scene_id].append(p)

        scores: list[PromptConsistencyScore] = []
        for scene_id, group in scene_groups.items():
            if len(group) < 2:
                scores.append(PromptConsistencyScore(
                    scene_id=scene_id, overall_score=1.0,
                ))
                continue

            ent = [set(p.prompt_layers.entity) for p in group]
            env = [
                set(p.prompt_layers.base + p.prompt_layers.cultural)
                for p in group
            ]
            lit = [set(p.prompt_layers.lighting_mood) for p in group]

            c = _jaccard_avg(ent)
            e = _jaccard_avg(env)
            l_ = _jaccard_avg(lit)
            overall = round(c * 0.4 + e * 0.35 + l_ * 0.25, 3)

            issues: list[str] = []
            if c < 0.5:
                issues.append("character description divergence across shots")
            if e < 0.5:
                issues.append("environment description divergence across shots")
            if l_ < 0.5:
                issues.append("lighting description divergence across shots")

            scores.append(PromptConsistencyScore(
                scene_id=scene_id,
                character_consistency=round(c, 3),
                environment_consistency=round(e, 3),
                lighting_consistency=round(l_, 3),
                overall_score=overall,
                issues=issues,
            ))
        return scores

    # ── Internal helpers ─────────────────────────────────────────────────

    def _build_keyframe_prompts(
        self, plan: ShotPromptPlan, mode: str,
    ) -> list[KeyframePrompt]:
        slots = _MODE_KEYFRAME_SLOTS.get(mode, [])
        if not slots:
            return []

        motion_frags = plan.prompt_layers.motion
        base_desc = ", ".join(
            plan.prompt_layers.base[:1] + plan.prompt_layers.entity[:2],
        )
        kf: list[KeyframePrompt] = []
        for slot in slots:
            if slot == "start":
                desc = f"{base_desc}, initial pose, tension building"
            elif slot == "end":
                desc = f"{base_desc}, follow-through recovery, spatial continuity"
            elif "mid" in slot:
                action = motion_frags[0] if motion_frags else "peak action moment"
                desc = f"{base_desc}, {action}"
            else:
                desc = base_desc
            kf.append(KeyframePrompt(slot=slot, prompt=desc))
        return kf

    @staticmethod
    def _build_parameter_hints(
        plan: ShotPromptPlan, mode: str, gc: GlobalPromptConstraints,
    ) -> ParameterHints:
        style_s = "medium"
        if gc.quality_profile == "final":
            style_s = "high"
        elif gc.quality_profile == "preview":
            style_s = "low"

        motion_s = "high" if plan.criticality == "critical" else "medium"
        guidance = (
            "stable_subject_priority"
            if plan.criticality == "critical"
            else "balanced"
        )
        return ParameterHints(
            style_strength=style_s,
            motion_strength=motion_s,
            guidance_hint=guidance,
            quality_priority=gc.quality_profile,
        )

    @staticmethod
    def _build_quality_layer(
        quality_profile: str, criticality: str, motion_level: str,
    ) -> list[str]:
        layer: list[str] = []
        if quality_profile == "final":
            layer.extend(["high detail", "cinematic quality", "masterpiece"])
        elif quality_profile == "preview":
            layer.append("preview quality")
        else:
            layer.extend(["high quality", "detailed"])
        if criticality == "critical":
            layer.append("sharp focus on key subject")
        if motion_level == "HIGH":
            layer.append("high action readability")
        return layer


# ── Module-level helper functions ────────────────────────────────────────────


def _extract_list(data: dict, key: str) -> list[dict]:
    val = data.get(key, [])
    return val if isinstance(val, list) else []


def _build_lookup(items: list[dict], key: str) -> dict[str, dict]:
    return {m.get(key, ""): m for m in items if m.get(key)}


def _normalize_uid_list(raw: Any) -> list[str]:
    """Accept list[str] or list[dict] with entity_uid key."""
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            uid = item.get("entity_uid", "")
            if uid:
                out.append(uid)
    return out


def _dedup(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _all_positive_fragments(layers: PromptLayers) -> list[str]:
    return (
        layers.base + layers.cultural + layers.entity + layers.shot
        + layers.motion + layers.lighting_mood + layers.quality
        + layers.consistency_anchor
    )


def _resolve_mode(target: str, backend: BackendCapability) -> str:
    mode = target.upper().replace("-", "_")
    supported = _BACKEND_MODES.get(backend.backend_id, backend.supported_modes)
    while mode not in supported and mode in _MODE_DOWNGRADE:
        mode = _MODE_DOWNGRADE[mode]
    if mode not in supported:
        mode = "T2I"
    return mode


def _assemble_positive(
    layers: PromptLayers,
    rules: AssemblyRules,
    lora_triggers: list[str],
    embedding_tokens: list[str],
    ff: Skill10FeatureFlags,
) -> str:
    parts: list[str] = []
    for layer_name in rules.positive_order:
        parts.extend(getattr(layers, layer_name, []))
    if ff.enable_lora_injection:
        parts.extend(lora_triggers)
        parts.extend(embedding_tokens)
    return rules.separator.join(p for p in parts if p)


def _assemble_negative(layers: NegativeLayers, rules: AssemblyRules) -> str:
    parts: list[str] = []
    for layer_name in rules.negative_order:
        parts.extend(getattr(layers, layer_name, []))
    return ", ".join(p for p in parts if p)


def _jaccard_avg(sets: list[set]) -> float:
    if len(sets) < 2:
        return 1.0
    total = 0.0
    count = 0
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            union = sets[i] | sets[j]
            total += len(sets[i] & sets[j]) / len(union) if union else 1.0
            count += 1
    return total / count if count else 1.0
