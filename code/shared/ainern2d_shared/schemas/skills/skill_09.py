"""SKILL 09: Visual Render Planner — Input/Output DTOs."""
from __future__ import annotations
from ainern2d_shared.schemas.base import BaseSchema


class ShotRenderConfig(BaseSchema):
    shot_id: str
    render_mode: str = "i2v"  # i2v | v2v | static
    fps: int = 24
    resolution: str = "1280x720"
    priority: int = 0
    gpu_tier: str = "A100"
    fallback_chain: list[str] = []


class Skill09Input(BaseSchema):
    audio_timeline: dict = {}
    shots: list[dict] = []
    asset_manifest: list[dict] = []
    compute_budget: dict = {}


class Skill09Output(BaseSchema):
    render_plans: list[ShotRenderConfig] = []
    total_gpu_hours_estimate: float = 0.0
    status: str = "ready_for_render_execution"
