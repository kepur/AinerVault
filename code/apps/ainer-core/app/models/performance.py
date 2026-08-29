"""表演层：这一刻画面里发生什么。

剧本层有 speaker_tag，知道**谁在说**，不知道**对谁说**。
实体层有 appearance / voice_hints，那是角色的**恒定属性**，
不是某一刻的**瞬时状态**。两者之间缺的就是这一层。

没有它，从剧本到分镜图有三个坎迈不过去：
    镜头给谁      不知道在场几个人、谁在听，只能永远给说话人特写
    前后帧一致    站位不记录，尾帧的人可能凭空换到画面另一边，动画直接穿帮
    动作差        首帧到尾帧之间「发生了什么」是这一镜的运动，
                  不记动作就只能画两张静止的脸

**恒定属性与瞬时状态必须分开存。** 混在一起的后果是：
「他握紧了剑」这个瞬时动作会污染角色的基础素材，
下一镜他明明放下了剑，生成出来手还是攥着的。
"""
from __future__ import annotations

import enum

from sqlalchemy import (
    Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, StdMixin


class StagePosition(str, enum.Enum):
    """画面站位。用九宫格而不是像素坐标 —— 像素在不同画幅下无意义，
    而九宫格能直接翻译成提示词（"on the left of frame"）。"""

    far_left = "far_left"
    left = "left"
    center_left = "center_left"
    center = "center"
    center_right = "center_right"
    right = "right"
    far_right = "far_right"
    foreground = "foreground"      # 前景，可能只是个背影或肩
    background = "background"      # 背景深处
    offscreen = "offscreen"        # 在场但不入画（画外音、门外）


class Facing(str, enum.Enum):
    """朝向。决定人物在画面里是正脸、侧脸还是背影。"""

    to_camera = "to_camera"
    away = "away"
    profile_left = "profile_left"
    profile_right = "profile_right"
    three_quarter = "three_quarter"


class SpeechRole(str, enum.Enum):
    """这一镜里该角色的对话身份。镜头分配的主要依据。"""

    speaker = "speaker"        # 正在说
    addressee = "addressee"    # 被对着说
    listener = "listener"      # 在场旁听
    silent = "silent"          # 在场但与这段对话无关
    absent = "absent"          # 被提及但不在场


class ShotPerformance(Base, StdMixin):
    """一个镜头里，一个角色的瞬时状态。

    (shot, entity) 唯一 —— 同一镜里同一个人只有一种状态。
    """

    __tablename__ = "shot_performances"
    __table_args__ = (
        UniqueConstraint("shot_id", "entity_id", name="uq_shot_perf_shot_entity"),
        Index("ix_shot_perf_shot", "shot_id", "speech_role"),
    )

    shot_id: Mapped[str] = mapped_column(
        ForeignKey("shots.id", ondelete="CASCADE"), nullable=False
    )
    entity_id: Mapped[str] = mapped_column(
        ForeignKey("world_entities.id", ondelete="CASCADE"), nullable=False
    )
    speech_role: Mapped[SpeechRole] = mapped_column(
        default=SpeechRole.listener, nullable=False
    )
    position: Mapped[StagePosition] = mapped_column(
        default=StagePosition.center, nullable=False
    )
    facing: Mapped[Facing] = mapped_column(default=Facing.three_quarter, nullable=False)
    #: 看向谁/什么。填 entity_id 或自由文本（"the locked chest"）。
    #: 对切镜头的轴线靠它定 —— 两个人对视时视线必须相向，否则观众会觉得"没在交流"
    gaze_target: Mapped[str | None] = mapped_column(String(128))
    #: 首帧时的表情
    expression: Mapped[str | None] = mapped_column(String(128))
    #: 尾帧时的表情。与首帧不同才有表演，相同就是一张静止的脸
    expression_end: Mapped[str | None] = mapped_column(String(128))
    #: 首帧动作
    action: Mapped[str | None] = mapped_column(Text)
    #: 尾帧动作。首尾之差就是这一镜的运动，也是 i2i 的改动依据
    action_end: Mapped[str | None] = mapped_column(Text)
    #: 手持物。指向 asset_specs 的 canonical_key，让道具跨镜保持同一形态
    props_json: Mapped[list | None] = mapped_column(JSONB)
    #: 表情与动作的英文渲染 {expression, expression_end, action, action_end}。
    #: **图像模型不认中文** —— 中文喂进去出来的是汉字纹样不是画面。
    #: 上面那几个中文字段是给人审核的，这一份是给出图的。
    #: 不另开四个列：它们只服务提示词拼装，不参与任何查询
    en_json: Mapped[dict | None] = mapped_column(JSONB)
    #: 与上一镜相比站位是否发生跳变。true 需要人工确认或补一个过渡镜
    position_jump: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text)
    edited_by_human: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
