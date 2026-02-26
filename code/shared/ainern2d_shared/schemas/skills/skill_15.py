"""SKILL 15: Creative Control Policy — Input/Output DTOs."""
from __future__ import annotations
from ainern2d_shared.schemas.base import BaseSchema


class Constraint(BaseSchema):
    constraint_id: str = ""
    constraint_type: str = "hard"  # hard | soft | exploration
    dimension: str = ""  # visual | audio | narrative | timing
    rule: str = ""
    priority: int = 0


class Skill15Input(BaseSchema):
    persona_style: dict = {}
    project_settings: dict = {}
    user_overrides: list[dict] = []


class Skill15Output(BaseSchema):
    hard_constraints: list[Constraint] = []
    soft_constraints: list[Constraint] = []
    exploration_range: dict = {}
    conflict_resolutions: list[str] = []
    status: str = "policy_ready"
