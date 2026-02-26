"""SKILL 18: Failure Recovery & Degradation Policy — Input/Output DTOs."""
from __future__ import annotations
from ainern2d_shared.schemas.base import BaseSchema


class RecoveryAction(BaseSchema):
    action_type: str  # retry | degrade | skip | abort
    target_skill: str = ""
    params: dict = {}
    reason: str = ""


class Skill18Input(BaseSchema):
    error_code: str = ""
    failed_skill: str = ""
    stage: str = ""
    retry_count: int = 0
    creative_controls: dict = {}
    run_context: dict = {}


class Skill18Output(BaseSchema):
    decision: RecoveryAction
    degradation_applied: bool = False
    circuit_breaker_triggered: bool = False
    status: str = "completed"
