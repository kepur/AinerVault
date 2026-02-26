"""Timeline editing forms / DTOs – Pydantic models for edit operations."""

from __future__ import annotations

from typing import Optional

from ainern2d_shared.schemas.base import BaseSchema


class ShotEditRequest(BaseSchema):
    """Request to edit a single shot's properties."""

    shot_id: str
    new_duration_ms: Optional[int] = None
    new_prompt: Optional[str] = None
    new_style_tags: Optional[list[str]] = None


class TrackReorderRequest(BaseSchema):
    """Request to reorder items within a track."""

    track_type: str  # "video" | "audio"
    item_ids_in_order: list[str]


class TimelineTrimRequest(BaseSchema):
    """Request to trim the timeline to a sub-range."""

    start_ms: int
    end_ms: int