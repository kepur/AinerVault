"""SKILL 19: Compute-Aware Shot Budgeter — Input/Output DTOs."""
from __future__ import annotations
from ainern2d_shared.schemas.base import BaseSchema


class ShotComputePlan(BaseSchema):
    shot_id: str
    fps: int = 24
    resolution: str = "1280x720"
    priority: int = 0
    gpu_tier: str = "A100"
    estimated_seconds: float = 0.0


class Skill19Input(BaseSchema):
    shots: list[dict] = []
    audio_manifest: dict = {}
    cluster_resources: dict = {}
    creative_controls: dict = {}


class Skill19Output(BaseSchema):
    shot_plans: list[ShotComputePlan] = []
    total_gpu_hours: float = 0.0
    budget_utilization: float = 0.0
    status: str = "compute_plan_ready"
