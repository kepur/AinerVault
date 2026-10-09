"""Shared stage metadata; SceneProtocol remains the geometry/animation authority."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.director.protocol import SceneProtocol
from app.production.schema import ResourceRef
from app.stage.schema import SceneStage, CoverageShot


class StageContract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Condition(StageContract):
    instance_id: str
    key: str = Field(min_length=1)
    value: Any = None


class StateEvent(StageContract):
    id: str = Field(min_length=1, max_length=80)
    time_ms: int = Field(ge=0)
    description: str = ""
    requires: list[str] = Field(default_factory=list, max_length=100)
    conditions: list[Condition] = Field(default_factory=list, max_length=100)
    changes: list[Condition] = Field(default_factory=list, max_length=100)


class Coverage(StageContract):
    id: str = Field(min_length=1, max_length=80)
    title: str = "镜头"
    camera_id: str
    # Clip clock and world clock are separate. Reverse/hold/overlap are explicit.
    clip_duration_ms: int = Field(gt=0, le=180000)
    scene_start_ms: int = Field(ge=0)
    scene_end_ms: int = Field(ge=0)
    fps: int = Field(default=24, ge=1, le=60)
    intent: str = ""
    participants: list[str] = Field(default_factory=list, max_length=100)
    must_show: list[str] = Field(default_factory=list, max_length=100)
    offscreen: list[str] = Field(default_factory=list, max_length=100)
    transition: Literal["cut", "continuous", "dissolve", "jump"] = "cut"

    @model_validator(mode="after")
    def frame_clock(self):
        if self.clip_duration_ms * self.fps % 1000:
            raise ValueError("镜头时长必须落在整数帧上；请调整时长或 FPS")
        if set(self.must_show) & set(self.offscreen):
            raise ValueError("同一实例不能同时要求入画和离画")
        return self


class StageContent(StageContract):
    protocol: SceneProtocol
    bindings: dict[str, ResourceRef] = Field(default_factory=dict, max_length=500)
    initial_state: dict[str, dict[str, Any]] = Field(default_factory=dict, max_length=500)
    events: list[StateEvent] = Field(default_factory=list, max_length=2000)
    coverages: list[Coverage] = Field(default_factory=list, max_length=500)


class StageCreate(StageContract):
    board_id: str = Field(min_length=1, max_length=32)
    title: str = Field(default="空白舞台", max_length=200)
    duration_ms: int = Field(default=6000, gt=0, le=180000)
    fps: int = Field(default=24, ge=1, le=60)


class StageUpdate(StageContent):
    base_version: int = Field(ge=1)


class NarrativeStageCreate(StageContract):
    board_id: str
    stage: SceneStage
    shots: list[CoverageShot] = Field(default_factory=list, max_length=100)
    bindings: dict[str, ResourceRef] = Field(default_factory=dict, max_length=500)
    heights_m: dict[str, float] = Field(default_factory=dict, max_length=500)
    fps: int = Field(default=24, ge=1, le=60)
    title: str = Field(default="剧情舞台", max_length=200)


class StageLink(StageContract):
    board_id: str
    base_version: int = Field(ge=1)


class StageSample(StageContract):
    base_version: int = Field(ge=1)
    time_ms: int = Field(ge=0)
    camera_id: str | None = None


class CoverageSample(StageContract):
    base_version: int = Field(ge=1)
    clip_time_ms: int = Field(ge=0)


class CoverageBake(StageContract):
    base_version: int = Field(ge=1)
