"""分镜层：ShotPlan → Shot → FrameSpec(first/last) + AudioSpec。

「前后针」= FrameSpec 的 first / last 两个角色。
尾帧默认从首帧派生（derive_from_first），独立 t2i 两次人物必崩。
"""
from __future__ import annotations

from enum import Enum

from sqlalchemy import (
    Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, StdMixin
from app.models.script import DocStatus


class FrameRole(str, Enum):
    first = "first"   # 前针
    last = "last"     # 后针


class AudioKind(str, Enum):
    dialogue = "dialogue"
    narration = "narration"
    sfx = "sfx"
    bgm = "bgm"
    ambience = "ambience"


class SpecStatus(str, Enum):
    pending = "pending"
    generating = "generating"
    ready = "ready"
    approved = "approved"
    failed = "failed"
    skipped = "skipped"


class ShotPlan(Base, StdMixin):
    __tablename__ = "shot_plans"
    __table_args__ = (
        UniqueConstraint("script_doc_id", "version", name="uq_shot_plans_doc_version"),
        Index("ix_shot_plans_doc_status", "script_doc_id", "status"),
    )

    script_doc_id: Mapped[str] = mapped_column(
        ForeignKey("script_docs.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[DocStatus] = mapped_column(default=DocStatus.draft, nullable=False)
    target_language_code: Mapped[str | None] = mapped_column(String(16))
    transform_id: Mapped[str | None] = mapped_column(String(32), index=True)
    #: 导演包决定「怎么拍」：景别分布、运镜偏好、切分密度
    director_profile_id: Mapped[str | None] = mapped_column(String(32), index=True)
    # {target_duration_ms, aspect_ratio, style_profile_id, shot_density}
    config_json: Mapped[dict | None] = mapped_column(JSONB)
    stats_json: Mapped[dict | None] = mapped_column(JSONB)


class Shot(Base, StdMixin):
    __tablename__ = "shots"
    __table_args__ = (
        Index("ix_shots_plan_order", "shot_plan_id", "order_no"),
        Index("ix_shots_scene", "scene_id"),
    )

    shot_plan_id: Mapped[str] = mapped_column(
        ForeignKey("shot_plans.id", ondelete="CASCADE"), nullable=False
    )
    scene_id: Mapped[str | None] = mapped_column(ForeignKey("scenes.id", ondelete="SET NULL"))
    order_no: Mapped[int] = mapped_column(Integer, nullable=False)
    block_ids_json: Mapped[list | None] = mapped_column(JSONB)
    # 初值来自估算，TTS 完成后回填真实时长 —— 时间线长度由配音决定
    duration_ms: Mapped[int] = mapped_column(Integer, default=4000, nullable=False)
    # {move, speed, fov, transition_in, transition_out}
    camera_json: Mapped[dict | None] = mapped_column(JSONB)
    #: ecu | cu | ms | fs | ws | els —— 由导演包的 shot_sizes 分布分配
    shot_size: Mapped[str | None] = mapped_column(String(8))
    description: Mapped[str | None] = mapped_column(Text)
    spec_fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)
    edited_by_human: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[SpecStatus] = mapped_column(default=SpecStatus.pending, nullable=False)
    video_asset_id: Mapped[str | None] = mapped_column(String(32))


class FrameSpec(Base, StdMixin):
    """前后针。"""

    __tablename__ = "frame_specs"
    __table_args__ = (
        UniqueConstraint("shot_id", "role", name="uq_frame_specs_shot_role"),
        Index("ix_frame_specs_status", "status"),
    )

    shot_id: Mapped[str] = mapped_column(
        ForeignKey("shots.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[FrameRole] = mapped_column(nullable=False)
    prompt: Mapped[str | None] = mapped_column(Text)
    negative_prompt: Mapped[str | None] = mapped_column(Text)
    entity_ids_json: Mapped[list | None] = mapped_column(JSONB)
    ref_asset_ids: Mapped[list | None] = mapped_column(JSONB)
    # 仅 role=last 有效。默认 True —— 尾帧以首帧为基底做 i2i，保证连贯
    derive_from_first: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    derive_instruction: Mapped[str | None] = mapped_column(Text)
    # {width, height, seed, steps, cfg, strength}
    params_json: Mapped[dict | None] = mapped_column(JSONB)
    asset_id: Mapped[str | None] = mapped_column(String(32))
    gen_task_id: Mapped[str | None] = mapped_column(String(32), index=True)
    status: Mapped[SpecStatus] = mapped_column(default=SpecStatus.pending, nullable=False)
    edited_by_human: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class AudioSpec(Base, StdMixin):
    __tablename__ = "audio_specs"
    __table_args__ = (
        Index("ix_audio_specs_shot", "shot_id"),
        Index("ix_audio_specs_scene", "scene_id"),
        Index("ix_audio_specs_status", "status"),
    )

    shot_id: Mapped[str | None] = mapped_column(ForeignKey("shots.id", ondelete="CASCADE"))
    scene_id: Mapped[str | None] = mapped_column(ForeignKey("scenes.id", ondelete="CASCADE"))
    kind: Mapped[AudioKind] = mapped_column(nullable=False)
    block_id: Mapped[str | None] = mapped_column(String(32))
    entity_id: Mapped[str | None] = mapped_column(String(32))
    text: Mapped[str | None] = mapped_column(Text)
    language_code: Mapped[str | None] = mapped_column(String(16))
    # {voice_id, emotion, speed, pitch, volume_db, loop}
    params_json: Mapped[dict | None] = mapped_column(JSONB)
    asset_id: Mapped[str | None] = mapped_column(String(32))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    timestamps_json: Mapped[list | None] = mapped_column(JSONB)
    gen_task_id: Mapped[str | None] = mapped_column(String(32), index=True)
    status: Mapped[SpecStatus] = mapped_column(default=SpecStatus.pending, nullable=False)
