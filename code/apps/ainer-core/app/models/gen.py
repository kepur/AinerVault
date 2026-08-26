"""生成层：能力调用记录与产物。"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from sqlalchemy import (
    DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, StdMixin


class TaskStatus(str, Enum):
    queued = "queued"
    submitted = "submitted"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class AssetKind(str, Enum):
    image = "image"
    audio = "audio"
    video = "video"
    text = "text"
    other = "other"


class AssetSource(str, Enum):
    generated = "generated"
    uploaded = "uploaded"
    external = "external"


class GenTask(Base, StdMixin):
    """一次能力调用。请求/结果/成本/错误全留痕，是审计与重试的唯一依据。"""

    __tablename__ = "gen_tasks"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_gen_tasks_idem"),
        Index("ix_gen_tasks_status_cap", "status", "capability"),
        Index("ix_gen_tasks_ref", "ref_kind", "ref_id"),
        Index("ix_gen_tasks_provider_task", "provider_task_id"),
        Index("ix_gen_tasks_novel", "novel_id"),
    )

    capability: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_json: Mapped[dict | None] = mapped_column(JSONB)
    endpoint_id: Mapped[str | None] = mapped_column(String(32))
    provider_task_id: Mapped[str | None] = mapped_column(String(128))
    provider: Mapped[str | None] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[TaskStatus] = mapped_column(default=TaskStatus.queued, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # {code, message, retryable, provider_raw}
    error_json: Mapped[dict | None] = mapped_column(JSONB)
    result_json: Mapped[dict | None] = mapped_column(JSONB)
    # {cost, currency, duration_ms, tokens, units}
    usage_json: Mapped[dict | None] = mapped_column(JSONB)
    warnings_json: Mapped[list | None] = mapped_column(JSONB)

    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    estimated_ms: Mapped[int | None] = mapped_column(Integer)
    poll_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    # 反向引用：frame_spec | audio_spec | scene_bg | scene_bgm | translation | entity_ref | lexicon
    ref_kind: Mapped[str | None] = mapped_column(String(32))
    ref_id: Mapped[str | None] = mapped_column(String(32))
    novel_id: Mapped[str | None] = mapped_column(String(32))
    chapter_id: Mapped[str | None] = mapped_column(String(32))


class Asset(Base, StdMixin):
    __tablename__ = "assets"
    __table_args__ = (
        Index("ix_assets_sha256", "sha256"),
        Index("ix_assets_novel_kind", "novel_id", "kind"),
    )

    kind: Mapped[AssetKind] = mapped_column(nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    sha256: Mapped[str | None] = mapped_column(String(64))
    mime: Mapped[str | None] = mapped_column(String(128))
    bytes: Mapped[int | None] = mapped_column(Integer)
    # 图: {width,height,seed}；音: {duration_ms,sample_rate}；视频: {fps,duration_ms}
    meta_json: Mapped[dict | None] = mapped_column(JSONB)
    source: Mapped[AssetSource] = mapped_column(default=AssetSource.generated, nullable=False)
    gen_task_id: Mapped[str | None] = mapped_column(String(32))
    novel_id: Mapped[str | None] = mapped_column(String(32))
    cost: Mapped[float | None] = mapped_column(Float)
