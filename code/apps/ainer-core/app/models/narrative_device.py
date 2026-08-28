"""叙事装置 —— 笑点、泪点、修辞的「机制」层。

跨文化改编真正的难点不是词，是**为什么好笑、为什么动人**。

    原文   我不是针对你，我是说在座的各位都是垃圾
    机制   扬抑反转：先做出缓和姿态，再把打击面扩大到全场
    英伦   I mean no offence to you personally — I mean it to everyone in this room.

机制能跨文化，文本不能。所以抽离时要抽机制，重写时按机制在目标文化里重造。
文化依赖度高的（谐音、典故、方言梗）标记为需要功能替代，而非硬翻。
"""
from __future__ import annotations

from enum import Enum

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, StdMixin


class DeviceType(str, Enum):
    """装置类型。决定重写时该用什么手法在目标文化里重造。"""

    pun = "pun"                    # 谐音 / 双关
    wordplay = "wordplay"          # 文字游戏
    misdirection = "misdirection"  # 误导后反转
    exaggeration = "exaggeration"  # 夸张
    understatement = "understatement"  # 反讽式轻描淡写
    irony = "irony"                # 反讽
    callback = "callback"          # 回扣前文
    cultural_ref = "cultural_ref"  # 典故 / 文化引用
    idiom = "idiom"                # 成语 / 俗语
    register_shift = "register_shift"  # 语体突变（文白夹杂、正式转粗口）
    repetition = "repetition"      # 重复与递进
    juxtaposition = "juxtaposition"  # 并置反差
    dramatic_irony = "dramatic_irony"  # 观众知情而角色不知
    foreshadow = "foreshadow"      # 伏笔
    sensory = "sensory"            # 感官细节堆叠


class DeviceEffect(str, Enum):
    """这个装置要达成什么效果 —— 重写后必须命中同样的效果。"""

    humor = "humor"
    tension = "tension"
    warmth = "warmth"
    grief = "grief"
    awe = "awe"
    dread = "dread"
    relief = "relief"
    irony = "irony"
    intimacy = "intimacy"
    contempt = "contempt"


class CulturalLoad(str, Enum):
    """文化依赖度 —— 决定改编策略。

    low     机制本身跨文化通用，直接重铸即可
    medium  需要换一个目标文化里的等价物
    high    深度绑定源文化（谐音、典故、方言），只能功能替代或补偿
    """

    low = "low"
    medium = "medium"
    high = "high"


class DeviceStrategy(str, Enum):
    """改编策略。high 文化依赖的装置不该硬翻。"""

    preserve = "preserve"      # 直接重铸，机制照搬
    substitute = "substitute"  # 换成目标文化的等价装置
    compensate = "compensate"  # 此处丢失，在附近补一个同效果的
    relocate = "relocate"      # 移到别处实现
    drop = "drop"              # 放弃（只在低价值时）


class NarrativeDevice(Base, StdMixin):
    """一处叙事装置。抽离于原文，重写时按机制在目标文化里重造。"""

    __tablename__ = "narrative_devices"
    __table_args__ = (
        Index("ix_narrative_devices_chapter", "chapter_id"),
        Index("ix_narrative_devices_block", "block_id"),
        Index("ix_narrative_devices_load", "cultural_load"),
    )

    chapter_id: Mapped[str] = mapped_column(
        ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False
    )
    block_id: Mapped[str | None] = mapped_column(String(32))
    beat_id: Mapped[str | None] = mapped_column(String(32))

    device_type: Mapped[DeviceType] = mapped_column(nullable=False)
    effect: Mapped[DeviceEffect] = mapped_column(nullable=False)
    cultural_load: Mapped[CulturalLoad] = mapped_column(
        default=CulturalLoad.medium, nullable=False
    )
    strategy: Mapped[DeviceStrategy] = mapped_column(
        default=DeviceStrategy.substitute, nullable=False
    )

    #: 原文里承载这个装置的文字
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    #: 机制说明 —— 语言无关，说清「为什么好笑/动人」。重写时照这个造。
    mechanism: Mapped[str] = mapped_column(Text, nullable=False)
    #: 铺垫在哪、爆点在哪
    setup: Mapped[str | None] = mapped_column(Text)
    punch: Mapped[str | None] = mapped_column(Text)
    #: 强度 1–5，决定这处丢了要不要补偿
    intensity: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    #: 依赖哪些源文化知识才能 get
    depends_on: Mapped[list | None] = mapped_column(JSONB)
    #: 目标文化下的重铸方案（阶段 2 产出）
    target_plan: Mapped[str | None] = mapped_column(Text)
    #: 该装置是否已在译文中命中（阶段 4 校验产出）
    landed: Mapped[bool | None] = mapped_column()
    landed_note: Mapped[str | None] = mapped_column(Text)


class BackTranslationCheck(Base, StdMixin):
    """回译校验 —— 把译文译回源语言，与原文骨架比对。

    这是质量闭环的最后一环：译文读着通顺不代表情节没丢。
    只有把成品回译再与骨架逐点比对，才知道哪个情节点、哪个情绪拐点没了。
    """

    __tablename__ = "back_translation_checks"
    __table_args__ = (
        Index("ix_bt_checks_chapter", "chapter_id", "target_language_code"),
    )

    chapter_id: Mapped[str] = mapped_column(
        ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False
    )
    transform_id: Mapped[str | None] = mapped_column(String(32))
    target_language_code: Mapped[str] = mapped_column(String(16), nullable=False)

    #: 覆盖率：骨架里的情节点有多少在译文中还在
    beat_coverage: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    #: 装置命中率：抽出的笑点/泪点有多少在译文中重铸成功
    device_landing: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    #: 情绪曲线相关度
    emotion_match: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    missing_beats: Mapped[list | None] = mapped_column(JSONB)
    lost_devices: Mapped[list | None] = mapped_column(JSONB)
    added_content: Mapped[list | None] = mapped_column(JSONB)
    notes: Mapped[str | None] = mapped_column(Text)
    passed: Mapped[bool] = mapped_column(default=False, nullable=False)
