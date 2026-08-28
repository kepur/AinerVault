"""称呼变体：同一个人在不同人嘴里叫什么。

李天明这个人，师父叫他「小天」，母亲叫「明儿」，仇家叫「姓李的」，
朝堂上是「李大人」。这四个称呼在中文里承载的不是信息，是**关系**——
读者从「小天」两个字里读到的是亲近，不是名字。

当前 L1 只有 实体 → 一个目标名，所有别名共用一个占位符、还原成同一个全名。
那样翻出来师父也叫他 Thomas Ashford，亲近感当场归零，
而且译文读着毫无破绽 —— 这类丢失不会报错，只会让读者觉得「淡」。

所以称呼必须是 L1 的一个独立维度：
    实体 × 称呼 × 映射 → 目标称呼
且目标称呼必须与本名同源（Thomas → Tom / Tommy），
不能一个 Thomas 一个 Jack —— 那就成了两个人。
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


class Register(str, enum.Enum):
    """称呼的社交语域 —— 决定目标文化里该用哪种形式。"""

    formal_full = "formal_full"      # 李天明：全名，叙述与正式场合
    formal_title = "formal_title"    # 李大人 / 李公子：头衔式，有距离
    respectful = "respectful"        # 天明先生：敬而不远
    intimate = "intimate"            # 小天 / 明儿：亲昵，长辈或密友
    diminutive = "diminutive"        # 小明：小名，多为幼时留下
    kinship = "kinship"              # 师兄 / 三弟：以关系代名
    epithet = "epithet"              # 北地剑客：绰号、名号
    derogatory = "derogatory"        # 姓李的 / 那小子：轻蔑
    pronoun_like = "pronoun_like"    # 那位公子：指代性称呼


#: 语域 → 目标文化的渲染指引。给命名模型看的，不是给用户看的。
REGISTER_BRIEF: dict[Register, str] = {
    Register.formal_full: "完整正式名，叙述文与正式场合使用",
    Register.formal_title: "头衔 + 姓（Master Ashford / Sir Thomas），保持距离感",
    Register.respectful: "敬称但不疏远（Master Thomas），长辈对晚辈的郑重",
    Register.intimate: "亲昵短形（Tom / lad），只有亲近的人这样叫",
    Register.diminutive: "昵称小形（Tommy），带幼时残留的味道",
    Register.kinship: "以关系代名（brother / my boy），不用本名",
    Register.epithet: "名号绰号，按目标文化的名号习惯重铸，不音译",
    Register.derogatory: "轻蔑式（that Ashford whelp），要能读出敌意",
    Register.pronoun_like: "指代性称呼（the young gentleman），不点名",
}


class EntityAppellation(Base, StdMixin):
    """一个实体的一种称呼，及其在某映射下的目标形式。

    transform_id 可空：为空表示只登记了源文称呼、还没定目标形式。
    抽取阶段先把称呼连同「谁这么叫」采下来，命名阶段再统一定形 ——
    分两步是因为定形必须知道本名，而本名要等家族命名跑完。
    """

    __tablename__ = "entity_appellations"
    __table_args__ = (
        UniqueConstraint(
            "entity_id", "transform_id", "source_surface",
            name="uq_appellation_entity_transform_surface",
        ),
        Index("ix_appellation_entity", "entity_id"),
        Index("ix_appellation_transform", "transform_id", "status"),
    )

    entity_id: Mapped[str] = mapped_column(
        ForeignKey("world_entities.id", ondelete="CASCADE"), nullable=False
    )
    transform_id: Mapped[str | None] = mapped_column(
        ForeignKey("world_transforms.id", ondelete="CASCADE")
    )
    #: 原文里的字面，如「小天」
    source_surface: Mapped[str] = mapped_column(String(128), nullable=False)
    register: Mapped[Register] = mapped_column(default=Register.formal_full, nullable=False)
    #: 谁这么叫。同一个称呼在不同人嘴里可能语域不同 ——
    #: 「小子」出自师父是亲昵，出自仇家是轻蔑，靠这个字段区分。
    speaker_hint: Mapped[str | None] = mapped_column(String(128))
    #: 目标文化里的对应形式，如「Tom」
    target_surface: Mapped[str | None] = mapped_column(String(256))
    #: 与本名的关系说明，审核时一眼看出是否同源
    relation_note: Mapped[str | None] = mapped_column(Text)
    #: 需要人眼确认的原因；为空表示无异常。
    #: 不能靠字面判同源 —— 英语昵称大量与本名无共同词根
    #: （Thomas→Tom 尚可，John→Jack、Edward→Ned、Margaret→Peggy 全无字面关系），
    #: 用前缀比对会把正确答案毙掉、把错误答案放过。所以这里只标记不拦截，
    #: 判断交给二次审核（模型带文化知识判，或人工看一眼）。
    risk_note: Mapped[str | None] = mapped_column(Text)
    #: [{chapter_id, quote}]，人工审核时能溯源
    evidence_json: Mapped[list | None] = mapped_column(JSONB)
    occurrences: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[ReviewStatus] = mapped_column(
        default=ReviewStatus.candidate, nullable=False
    )
    locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
