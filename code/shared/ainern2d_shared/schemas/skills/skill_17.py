"""SKILL 17: Experiment & A/B Test Orchestrator — Input/Output DTOs."""
from __future__ import annotations
from ainern2d_shared.schemas.base import BaseSchema


class ExperimentVariant(BaseSchema):
    variant_id: str
    description: str = ""
    param_overrides: dict = {}


class VariantResult(BaseSchema):
    variant_id: str
    scores: dict = {}
    rank: int = 0
    promoted: bool = False


class Skill17Input(BaseSchema):
    experiment_name: str = ""
    benchmark_case: dict = {}
    variants: list[ExperimentVariant] = []
    evaluation_dimensions: list[str] = []


class Skill17Output(BaseSchema):
    experiment_id: str = ""
    results: list[VariantResult] = []
    winner_variant_id: str = ""
    status: str = "completed"
