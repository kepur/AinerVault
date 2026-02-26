"""SKILL 10: Prompt Planner — Input/Output DTOs."""
from __future__ import annotations
from ainern2d_shared.schemas.base import BaseSchema


class GlobalPromptConstraints(BaseSchema):
    style_keywords: list[str] = []
    negative_prompts: list[str] = []
    quality_preset: str = "standard"


class ShotPromptPlan(BaseSchema):
    shot_id: str
    positive_prompt: str = ""
    negative_prompt: str = ""
    lora_refs: list[str] = []
    controlnet_refs: list[str] = []
    seed: int = -1


class ModelVariant(BaseSchema):
    variant_id: str
    model_backend: str = "comfyui"  # comfyui | sdxl | flux
    params_override: dict = {}


class Skill10Input(BaseSchema):
    canonical_entities: list[dict] = []
    asset_manifest: list[dict] = []
    render_plans: list[dict] = []
    persona_style: dict = {}
    creative_controls: dict = {}


class Skill10Output(BaseSchema):
    global_constraints: GlobalPromptConstraints = GlobalPromptConstraints()
    shot_prompt_plans: list[ShotPromptPlan] = []
    model_variants: list[ModelVariant] = []
    status: str = "ready_for_prompt_execution"
