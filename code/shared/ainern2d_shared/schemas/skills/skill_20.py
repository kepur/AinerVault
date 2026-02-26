"""SKILL 20: Shot DSL Compiler & Prompt Backend — Input/Output DTOs."""
from __future__ import annotations
from ainern2d_shared.schemas.base import BaseSchema


class CompiledShot(BaseSchema):
    shot_id: str
    backend: str = "comfyui"  # comfyui | sdxl | flux
    positive_prompt: str = ""
    negative_prompt: str = ""
    parameters: dict = {}  # fps, duration, seed, resolution, etc.
    constraints_applied: list[str] = []
    persona_influences: list[str] = []
    rag_sources_used: list[str] = []


class CompilerTrace(BaseSchema):
    shot_id: str
    decisions: list[dict] = []
    warnings: list[str] = []


class Skill20Input(BaseSchema):
    shot_prompt_plans: list[dict] = []
    creative_control_stack: dict = {}
    compute_budget: dict = {}
    persona_style: dict = {}


class Skill20Output(BaseSchema):
    compiled_shots: list[CompiledShot] = []
    compiler_traces: list[CompilerTrace] = []
    status: str = "compiled_ready"
