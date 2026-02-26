"""SKILL 13: Feedback Evolution Loop — Input/Output DTOs."""
from __future__ import annotations
from ainern2d_shared.schemas.base import BaseSchema


class FeedbackEntry(BaseSchema):
    feedback_id: str = ""
    run_id: str = ""
    shot_id: str = ""
    dimension: str = ""  # visual | audio | narrative | style
    rating: int = 0  # 1-5
    comment: str = ""
    annotated_region: dict = {}


class ImprovementProposal(BaseSchema):
    proposal_id: str = ""
    target_skill: str = ""
    action: str = ""  # update_kb | adjust_policy | retrain_lora
    description: str = ""
    priority: int = 0


class Skill13Input(BaseSchema):
    feedback_entries: list[FeedbackEntry] = []
    run_context: dict = {}


class Skill13Output(BaseSchema):
    proposals: list[ImprovementProposal] = []
    kb_evolution_triggered: bool = False
    status: str = "completed"
