"""SKILL 10: PromptPlannerService — 业务逻辑实现。
参考规格: SKILL_10_PROMPT_PLANNER.md
状态: SERVICE_READY
"""
from __future__ import annotations

import hashlib

from loguru import logger
from sqlalchemy.orm import Session

from ainern2d_shared.schemas.skills.skill_10 import (
    GlobalPromptConstraints,
    ModelVariant,
    Skill10Input,
    Skill10Output,
    ShotPromptPlan,
)
from ainern2d_shared.services.base_skill import BaseSkillService, SkillContext

# ── Culture-aware negative prompts ────────────────────────────────────────────
_PACK_NEGATIVES: dict[str, list[str]] = {
    "cn_wuxia": ["modern architecture", "western furniture", "neon signs", "cars", "smartphones"],
    "cn_xianxia": ["modern technology", "western elements", "realistic urban"],
    "jp_anime": ["photorealistic", "western medieval", "chinese historical"],
    "en_western_fantasy": ["modern technology", "asian elements", "neon", "cars"],
    "generic": ["low quality", "blurry", "deformed", "extra limbs"],
}
_DEFAULT_NEGATIVES = ["low quality", "blurry", "deformed", "watermark", "signature"]

# ── Style keywords by culture pack ────────────────────────────────────────────
_PACK_STYLE: dict[str, list[str]] = {
    "cn_wuxia": ["ancient chinese architecture", "jianghu aesthetic", "traditional ink painting style", "cinematic"],
    "cn_xianxia": ["xianxia cultivation aesthetic", "mystical mountains", "ethereal glow", "cinematic"],
    "jp_anime": ["anime style", "japanese aesthetic", "detailed cel shading", "vibrant colors"],
    "en_western_fantasy": ["medieval fantasy", "epic cinematic", "dramatic lighting", "detailed"],
    "generic": ["high quality", "detailed", "cinematic lighting"],
}

# ── Model backend mapping ─────────────────────────────────────────────────────
_BACKEND_MAP: dict[str, str] = {
    "i2v": "comfyui",
    "static": "sdxl",
    "v2v": "flux",
}


def _stable_seed(shot_id: str) -> int:
    return int(hashlib.md5(shot_id.encode()).hexdigest()[:8], 16) % (2**32)


class PromptPlannerService(BaseSkillService[Skill10Input, Skill10Output]):
    """SKILL 10 — Prompt Planner.

    State machine:
      INIT → LOADING_CONSTRAINTS → BUILDING_LAYERS → GENERATING_PROMPTS
           → APPLYING_NEGATIVES → READY_FOR_PROMPT_EXECUTION | FAILED
    """

    skill_id = "skill_10"
    skill_name = "PromptPlannerService"

    def __init__(self, db: Session) -> None:
        super().__init__(db)

    def execute(self, input_dto: Skill10Input, ctx: SkillContext) -> Skill10Output:
        self._record_state(ctx, "INIT", "LOADING_CONSTRAINTS")

        # Extract culture pack info
        persona_style = input_dto.persona_style or {}
        pack_id = (input_dto.creative_controls or {}).get("culture_pack_id", "generic")
        quality_preset = persona_style.get("quality_preset", "standard")

        style_kws = list(_PACK_STYLE.get(pack_id, _PACK_STYLE["generic"]))
        neg_base = list(_PACK_NEGATIVES.get(pack_id, _DEFAULT_NEGATIVES))
        neg_base.extend(_DEFAULT_NEGATIVES)

        global_constraints = GlobalPromptConstraints(
            style_keywords=style_kws,
            negative_prompts=list(set(neg_base)),
            quality_preset=quality_preset,
        )

        # Build entity anchor lookup: entity_uid → variant_display_name
        entity_anchors: dict[str, str] = {}
        for ent in input_dto.canonical_entities:
            uid = ent.get("entity_uid", "")
            name = ent.get("surface_form", ent.get("variant_display_name", uid))
            entity_anchors[uid] = name

        # Asset manifest: entity_uid → asset_id
        asset_map: dict[str, str] = {}
        for item in input_dto.asset_manifest:
            uid = item.get("entity_uid", "")
            aid = item.get("asset_id", "")
            if uid and aid:
                asset_map[uid] = aid

        self._record_state(ctx, "LOADING_CONSTRAINTS", "BUILDING_LAYERS")
        self._record_state(ctx, "BUILDING_LAYERS", "GENERATING_PROMPTS")

        shot_plans: list[ShotPromptPlan] = []
        model_variants: list[ModelVariant] = []

        for rp in input_dto.render_plans:
            shot_id = rp.get("shot_id", "")
            render_mode = rp.get("render_mode", "static")
            fps = rp.get("fps", 24)

            # Build positive prompt layers
            layers = []
            layers.extend(style_kws[:2])  # culture layer

            # Entity layer
            for uid, name in entity_anchors.items():
                layers.append(name)

            # Shot-specific layer
            layers.append(f"shot {shot_id}")
            if fps > 1:
                layers.append("dynamic motion")

            # Quality layer
            if quality_preset == "high":
                layers.extend(["8k resolution", "masterpiece", "ultra detailed"])
            else:
                layers.extend(["high quality", "detailed"])

            positive = ", ".join(layers)

            # Lora refs from asset manifest
            lora_refs = [v for k, v in asset_map.items() if "lora" in k.lower()]

            shot_plans.append(ShotPromptPlan(
                shot_id=shot_id,
                positive_prompt=positive,
                negative_prompt=", ".join(global_constraints.negative_prompts),
                lora_refs=lora_refs,
                controlnet_refs=[],
                seed=_stable_seed(shot_id),
            ))

            backend = _BACKEND_MAP.get(render_mode, "sdxl")
            model_variants.append(ModelVariant(
                variant_id=f"{shot_id}__{backend}",
                model_backend=backend,
                params_override={"fps": fps},
            ))

        self._record_state(ctx, "GENERATING_PROMPTS", "APPLYING_NEGATIVES")
        self._record_state(ctx, "APPLYING_NEGATIVES", "READY_FOR_PROMPT_EXECUTION")

        logger.info(
            f"[{self.skill_id}] completed | run={ctx.run_id} shots={len(shot_plans)}"
        )

        return Skill10Output(
            global_constraints=global_constraints,
            shot_prompt_plans=shot_plans,
            model_variants=model_variants,
            status="ready_for_prompt_execution",
        )
