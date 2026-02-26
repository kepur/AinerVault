"""SKILL 16: Critic Evaluation Suite — Input/Output DTOs."""
from __future__ import annotations
from ainern2d_shared.schemas.base import BaseSchema


class DimensionScore(BaseSchema):
    dimension: str  # visual_consistency | audio_sync | narrative_coherence | style_match
    score: float = 0.0
    max_score: float = 10.0
    details: str = ""


class ProblemLocation(BaseSchema):
    shot_id: str = ""
    dimension: str = ""
    severity: str = "warning"  # info | warning | error | critical
    description: str = ""
    fix_skill: str = ""  # which SKILL to re-run


class Skill16Input(BaseSchema):
    run_id: str = ""
    composed_artifact_uri: str = ""
    creative_controls: dict = {}
    evaluation_dimensions: list[str] = []


class Skill16Output(BaseSchema):
    dimension_scores: list[DimensionScore] = []
    problems: list[ProblemLocation] = []
    overall_score: float = 0.0
    pass_threshold: float = 7.0
    passed: bool = False
    status: str = "completed"
