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
    #: payload 拼成的提示词片段，中文，**给人审核**
    prompt: Mapped[str | None] = mapped_column(Text)
    #: 英文那一份，**直接交给图像／视频模型**。
    #: 图像模型不认中文 —— 喂中文出来的是一整版汉字纹样，不是画面。
    #: 制作单是本系统对下游的主要交付物，只有中文等于交不出去
    prompt_en: Mapped[str | None] = mapped_column(Text)
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
        UniqueConstraint("cast_key", "world_profile_id", "epoch_key",
                         name="uq_voice_casting_key_profile_epoch"),
    )

    #: 配音对象的标识。角色是它的 entity_id，旁白是 __narrator__。
    #: **不能直接用 entity_id 当键** —— 旁白没有实体，
    #: 而它恰恰是全片出现最多的那把嗓子，必须与主要角色一样有一行、
    #: 一样参与撞声检测。留空的 entity_id 也做不成唯一键：
    #: Postgres 里 NULL 各不相等，两行旁白能同时存在。
    cast_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_id: Mapped[str | None] = mapped_column(
        ForeignKey("world_entities.id", ondelete="CASCADE")
    )
    world_profile_id: Mapped[str] = mapped_column(
        ForeignKey("world_profiles.id", ondelete="CASCADE"), nullable=False
    )
    epoch_key: Mapped[str] = mapped_column(String(64), default="baseline",
                                           nullable=False)
    #: 音色的结构化描述，取值受 worldview.voice 的术语表约束。
    #: identity 五项（声部/音区/音质/共鸣/口音）跨时期恒定，
    #: epoch 四项（年龄感/语速/力度/状态）随时期变 —— 与素材时期同一套办法
    timbre_json: Mapped[dict | None] = mapped_column(JSONB)
    #: 某个引擎上的落地：voice id 或参考音频。**不是权威** ——
    #: 权威是 timbre_json 的声学描述。存了 voice_id 当权威就锁死在一家引擎上，
    #: 换 TTS 时全书要重配，等于换了一套演员
    voice_ref: Mapped[str | None] = mapped_column(String(128))
    #: 这条 voice_ref 属于哪个引擎。换引擎时据此判断要不要重新落地
    voice_engine: Mapped[str | None] = mapped_column(String(64))
    voice_asset_id: Mapped[str | None] = mapped_column(String(32))
    #: 该角色的语言习惯：口头禅、句式偏好、常用称呼
    speech_habits: Mapped[str | None] = mapped_column(Text)
    rationale: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[ReviewStatus] = mapped_column(
        default=ReviewStatus.candidate, nullable=False
    )
    edited_by_human: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
