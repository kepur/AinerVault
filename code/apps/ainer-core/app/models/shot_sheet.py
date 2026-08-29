"""镜头制作单 —— 每个工种对这一镜的完整交代。

这是本系统对下游（图像／视频／音频生成）的**主要交付物**。
本系统不生成画面与声音，但必须把「该生成什么」说到不留空白，
否则那些模块只能自己猜，而猜出来的东西没法跨镜保持一致。

## 为什么按工种分开存，而不是一个大 JSON

一次让模型填完摄影灯光美术声音剪辑，它会平均用力、每项都写两句 ——
而这些维度的判据完全不同：灯光要方位与光质，剪辑要秒数与切点。
分开之后每一项都能带着自己的判据与反例去生成，也能单独重跑：
灯光不满意就重出灯光，不必把整张单子推倒。

后出的工种能看见先出的产出：灯光要知道摄影定的机位，
声音要知道剪辑定的时长。顺序写在 crew.CREW 里。

## 首尾帧与运镜

video 段单独存 —— 它是**这一镜的运动**，也是首帧到尾帧的差。
下游做视频时要的正是这个：起幅什么样、落幅什么样、中间怎么走。
存在 shot 上而不是 frame 上，因为运动属于镜头不属于某一帧。
"""
from __future__ import annotations

import enum

from sqlalchemy import (
    Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, StdMixin
from app.models.world import ReviewStatus


class SheetStatus(str, enum.Enum):
    pending = "pending"        # 还没生成
    drafted = "drafted"        # 模型出了初稿
    reviewed = "reviewed"      # 人看过
    locked = "locked"          # 定稿，重跑不覆盖


class CrewSheet(Base, StdMixin):
    """一个镜头 × 一个工种的产出。

    (shot, role) 唯一。payload_json 的字段由该工种的规格决定 ——
    不做成固定列，因为工种会增加，而每个工种的维度差别很大。
    """

    __tablename__ = "crew_sheets"
    __table_args__ = (
        UniqueConstraint("shot_id", "role", name="uq_crew_sheet_shot_role"),
        Index("ix_crew_sheet_role", "role", "status"),
    )

    shot_id: Mapped[str] = mapped_column(
        ForeignKey("shots.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    #: 按该工种的必填维度组织的结构化产出
    payload_json: Mapped[dict | None] = mapped_column(JSONB)
    #: payload 拼成的提示词片段，落库以便直接取用与比对
    prompt: Mapped[str | None] = mapped_column(Text)
    #: 缺了哪些必填维度。空列表 = 完整。
    #: **不是警告而是验收标准** —— 缺项的单子不该进入生成
    missing_json: Mapped[list | None] = mapped_column(JSONB)
    #: 命中了哪些「不合格写法」。规格里的反例在这里被反向使用
    rejected_json: Mapped[list | None] = mapped_column(JSONB)
    model: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[SheetStatus] = mapped_column(
        default=SheetStatus.drafted, nullable=False
    )
    edited_by_human: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    note: Mapped[str | None] = mapped_column(Text)


class ShotMotion(Base, StdMixin):
    """这一镜的运动 —— 首帧到尾帧之间发生了什么。

    与 CrewSheet 分开，因为它有**两个消费者**：
    尾帧的 i2i 要知道该改什么，视频模型要知道怎么动。
    两者要的粒度不同，但来源是同一份描述。
    """

    __tablename__ = "shot_motions"
    __table_args__ = (
        UniqueConstraint("shot_id", name="uq_shot_motion_shot"),
    )

    shot_id: Mapped[str] = mapped_column(
        ForeignKey("shots.id", ondelete="CASCADE"), nullable=False
    )
    #: 起幅：镜头开始时画面是什么样
    start_frame: Mapped[str | None] = mapped_column(Text)
    #: 落幅：镜头结束时画面是什么样
    end_frame: Mapped[str | None] = mapped_column(Text)
    #: 相机怎么动。静止也要明写 —— 不写视频模型会自己加运动
    camera_move: Mapped[str | None] = mapped_column(Text)
    #: 主体怎么动
    subject_move: Mapped[str | None] = mapped_column(Text)
    #: 运动速度与节奏曲线（匀速／先慢后快／急停）
    pacing: Mapped[str | None] = mapped_column(String(128))
    #: 首尾之间**变化了什么**，逐项列出。
    #: 这是 i2i 的直接依据 —— 没有它，尾帧只能整张重画
    deltas_json: Mapped[list | None] = mapped_column(JSONB)
    #: 给视频模型的完整运动提示词
    motion_prompt: Mapped[str | None] = mapped_column(Text)
    status: Mapped[SheetStatus] = mapped_column(
        default=SheetStatus.drafted, nullable=False
    )
    edited_by_human: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )


class VoiceCasting(Base, StdMixin):
    """角色 × 圈层 的音色绑定。

    全片同一个角色必须是同一个音色 —— 换了观众会当成换了人。
    所以绑定挂在角色上而不是镜头上，镜头只引用它。

    时期演化在这里同样适用：少年与中年的音色不同，
    但**必须是同一个音色的不同年龄版本**，不是两个人。
    epoch_key 对应 asset_epochs 的分期。
    """

    __tablename__ = "voice_castings"
    __table_args__ = (
        UniqueConstraint("entity_id", "world_profile_id", "epoch_key",
                         name="uq_voice_casting_entity_profile_epoch"),
    )

    entity_id: Mapped[str] = mapped_column(
        ForeignKey("world_entities.id", ondelete="CASCADE"), nullable=False
    )
    world_profile_id: Mapped[str] = mapped_column(
        ForeignKey("world_profiles.id", ondelete="CASCADE"), nullable=False
    )
    epoch_key: Mapped[str] = mapped_column(String(64), default="baseline",
                                           nullable=False)
    #: 音色的结构化描述：性别、年龄感、音高、音质、口音、语速基线
    timbre_json: Mapped[dict | None] = mapped_column(JSONB)
    #: 供 TTS 使用的音色 id 或参考音频。中间层据此选声
    voice_ref: Mapped[str | None] = mapped_column(String(128))
    voice_asset_id: Mapped[str | None] = mapped_column(String(32))
    #: 该角色的语言习惯：口头禅、句式偏好、常用称呼
    speech_habits: Mapped[str | None] = mapped_column(Text)
    rationale: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ReviewStatus] = mapped_column(
        default=ReviewStatus.candidate, nullable=False
    )
    locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
