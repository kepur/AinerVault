"""素材的时期演化 —— 同一个人在不同篇章不是同一套素材。

小说是**沿时间展开**的：林凡少年时的脸、衣着、佩刀，
和他中年时不是一回事；老家的院子二十年后还是那个院子。
而 AssetVariant 的唯一键是 (素材, 圈层)，一个素材只有一个形态 ——
用它生成，主角从第一章到最后一章都是同一张脸同一身衣服。

## 核心：把「不变的」与「变的」拆开存

    invariant   跨时期恒定：骨相、五官、瞳色、疤痕胎记
    variant     这一时期特有：发型、服装、随身兵器、气质、年龄感

**拆开是为了让脸保持一致。** 合在一起存的话，每个时期都要重新
描述一遍长相，而「浓眉、左颊一道旧疤」这种描述每写一次就会漂一点，
三个时期下来就是三个人。拆开之后 invariant 逐字复用，
生成时与 variant 拼接 —— 变的只有该变的那部分。

对固定物体（主角老家、祖传的刀）只建一个时期、覆盖全书，
于是「探访故乡」那一镜自然引用到二十章前的同一份素材与同一张参考图。

## 时期从哪来

不是按章节机械切分，而是**由事件触发**：拜师、出师、受伤、
获得新兵器、身份转变。所以 trigger 要记下来 ——
它既是时期的分界依据，也是审核时判断「这里该不该换形态」的凭据。
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


class EpochKind(str, enum.Enum):
    """这一时期为什么与上一期不同 —— 决定该改哪些字段。"""

    baseline = "baseline"        # 首次出场的形态，后续时期以它为基准
    age = "age"                  # 年龄推进：少年 → 青年 → 中年
    status = "status"            # 身份转变：布衣 → 捕快 → 隐居
    gear = "gear"                # 装备更替：换刀、得甲、失了佩剑
    injury = "injury"            # 身体改变：断臂、留疤、白头
    season = "season"            # 场景的季节／天候变化
    ruin = "ruin"                # 场景的损毁或修缮
    disguise = "disguise"        # 易容、伪装 —— 短暂且会还原


#: 各类实体的「不变」字段。生成时逐字复用，是同一性的锚。
INVARIANT_FIELDS: dict[str, tuple[str, ...]] = {
    "character": ("face_shape", "features", "eye_color", "skin_tone",
                  "scars", "build", "height"),
    "location": ("structure", "terrain", "orientation", "materials", "scale"),
    "prop": ("form", "material", "maker_marks"),
    "costume": ("cut", "fabric"),
}

#: 各类实体的「可变」字段。时期之间该变的就是这些。
VARIANT_FIELDS: dict[str, tuple[str, ...]] = {
    "character": ("age_look", "hair", "facial_hair", "garments", "accessories",
                  "carried", "bearing", "condition"),
    "location": ("season", "weather", "lighting", "furnishing", "damage",
                 "occupancy"),
    "prop": ("wear", "ornament", "state"),
    "costume": ("color", "wear", "layering", "season"),
}


class AssetEpoch(Base, StdMixin):
    """一个素材在某个圈层下、某一时期的形态。

    (素材, 圈层, 时期) 唯一。取代了 AssetVariant 的
    「一个素材一个形态」—— 那个仍然保留，作为**基准形态**：
    没有时期数据时回落到它，有时期数据时以时期为准。
    """

    __tablename__ = "asset_epochs"
    __table_args__ = (
        UniqueConstraint("asset_spec_id", "world_profile_id", "epoch_key",
                         name="uq_asset_epoch_spec_profile_key"),
        Index("ix_asset_epoch_lookup", "asset_spec_id", "world_profile_id",
              "from_chapter_order"),
    )

    asset_spec_id: Mapped[str] = mapped_column(
        ForeignKey("asset_specs.id", ondelete="CASCADE"), nullable=False
    )
    world_profile_id: Mapped[str] = mapped_column(
        ForeignKey("world_profiles.id", ondelete="CASCADE"), nullable=False
    )
    #: 时期标识。用语义化的名字而非序号 ——
    #: 「youth」「after_master_died」比「epoch_2」在提示词与审核里都可读
    epoch_key: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[EpochKind] = mapped_column(default=EpochKind.age, nullable=False)
    order_no: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    #: 生效区间（按章节序号）。to 为空表示延续到全书结束 ——
    #: 固定物体只建一个时期、from=1、to 空，于是任何章节都命中它
    from_chapter_order: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    to_chapter_order: Mapped[int | None] = mapped_column(Integer)

    #: 什么事件把它推进到这一期。既是分界依据，
    #: 也是审核时判断「这里该不该换形态」的凭据
    trigger: Mapped[str | None] = mapped_column(Text)
    trigger_chapter_id: Mapped[str | None] = mapped_column(String(32))

    #: 跨时期恒定的部分。**逐字复用，不重新描述** ——
    #: 每写一次就会漂一点，三个时期下来就是三个人
    invariant_json: Mapped[dict | None] = mapped_column(JSONB)
    #: 这一期特有的部分
    variant_json: Mapped[dict | None] = mapped_column(JSONB)

    #: invariant + variant 合成的完整提示词，落库以便审核与比对
    visual_prompt: Mapped[str | None] = mapped_column(Text)
    negative_prompt: Mapped[str | None] = mapped_column(Text)
    #: 该期的参考图。人物的**脸参考**应跨期共用同一张 ——
    #: 换了参考图，脸就会跟着漂
    ref_asset_ids: Mapped[list | None] = mapped_column(JSONB)
    #: 明确指向作为同一性锚点的那张脸/形参考。跨期共用
    identity_ref_asset_id: Mapped[str | None] = mapped_column(String(32))

    status: Mapped[ReviewStatus] = mapped_column(
        default=ReviewStatus.candidate, nullable=False
    )
    locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)


class EpochBinding(Base, StdMixin):
    """镜头实际用了哪个时期的素材。

    单独记一条而不是现算，有两个理由：
      可追溯  出图不对时能查到当时用的是哪一期、为什么选它
      可复用  「探访故乡」要与二十章前同一个场景一致 ——
              查这张表就知道那一镜当时绑的是哪份素材、哪张参考图
    """

    __tablename__ = "epoch_bindings"
    __table_args__ = (
        UniqueConstraint("shot_id", "asset_spec_id", name="uq_epoch_binding_shot_spec"),
        Index("ix_epoch_binding_epoch", "asset_epoch_id"),
    )

    shot_id: Mapped[str] = mapped_column(
        ForeignKey("shots.id", ondelete="CASCADE"), nullable=False
    )
    asset_spec_id: Mapped[str] = mapped_column(
        ForeignKey("asset_specs.id", ondelete="CASCADE"), nullable=False
    )
    asset_epoch_id: Mapped[str | None] = mapped_column(
        ForeignKey("asset_epochs.id", ondelete="SET NULL")
    )
    #: 怎么选中的：by_chapter 按章节区间／reused 复用了历史镜头的绑定／
    #: manual 人工指定／fallback 没有时期数据，回落到基准形态
    resolved_by: Mapped[str] = mapped_column(String(16), default="by_chapter",
                                             nullable=False)
    #: 复用时指向被复用的那个镜头，供人核对一致性
    reused_from_shot_id: Mapped[str | None] = mapped_column(String(32))
    note: Mapped[str | None] = mapped_column(Text)
