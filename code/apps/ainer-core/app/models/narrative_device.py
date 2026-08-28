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
    """改编策略阶梯。从「照搬」到「舍弃」，代价递增。

    「能不能翻」不是是非题，是选哪一档的问题。选错的代价不对称：
    该 substitute 的用了 footnote，读者出戏；
    该 gloss 的用了 preserve，读者一脸茫然还以为自己没读懂。

    前四档不出戏 —— 读者读到的仍是故事：
      preserve    直接重铸，机制照搬。机制本身跨文化通用时用。
      substitute  换成目标文化里承担同样功能的等价物。
      transplant  整体移植：换一个目标文化的梗，字面全变、效果对齐。
      naturalize  归化重写：整段按目标文化的表达习惯重来，不留源文痕迹。

    中间两档要付出「读者意识到这是译文」的代价：
      gloss_inline 行内轻注：在句子里自然带出必要背景，不加括号不打断。
                   代价最小的解释手段，但会让句子变长、节奏变慢。
      footnote     脚注：正文保留原样，注释单列。信息最完整、出戏最狠，
                   只用于「这个典故本身就是内容」的场合。

    最后两档是止损：
      compensate  此处认赔，在附近补一个同效果的装置，总量守恒。
      relocate    移到别处实现。
      omit        舍弃。强行保留反而伤害阅读时才用。
    """

    preserve = "preserve"
    substitute = "substitute"
    transplant = "transplant"
    naturalize = "naturalize"
    gloss_inline = "gloss_inline"
    footnote = "footnote"
    compensate = "compensate"
    relocate = "relocate"
    omit = "omit"


#: 策略 → 给模型看的中文说明。**唯一一份**。
#: 之前 devices.py 和 translate.py 各存一份，策略从 5 档扩到 9 档时
#: 只改了枚举，两份映射都没跟上 —— 而它们用 `[key]` 索引，
#: 漏一档不是显示不全，是直接 KeyError 把整次翻译打挂。
STRATEGY_BRIEF: dict[str, str] = {
    "preserve": "照机制直接重铸",
    "substitute": "换成目标文化里承担同样功能的等价物",
    "transplant": "换一个目标文化自己的梗，字面全变、效果对齐",
    "naturalize": "按目标文化的表达习惯重写，不留源文痕迹",
    "gloss_inline": "行内轻注：把必要背景自然编进句子，不加括号不打断",
    "footnote": "正文保留原样，注释单列",
    "compensate": "此处认赔，在邻近处补一个同效果的",
    "relocate": "移到附近合适的位置实现",
    "omit": "舍弃，不留字面翻译",
}


def strategy_brief(strategy: "DeviceStrategy", target_display: str = "目标") -> str:
    """取策略说明。用 get 兜底 —— 新增枚举忘了配文案时应该降级，不该崩。"""
    text = STRATEGY_BRIEF.get(strategy.value, strategy.value)
    return text.replace("目标文化", f"{target_display}文化")


class PlotLoad(str, Enum):
    """这处装置承载多少情节。决定「能不能舍」。

    纯修辞的笑点舍了只是可惜；伏笔舍了，后文的回扣就落空 ——
    读者不会觉得「这里少了个梗」，只会觉得「后面那段莫名其妙」。
    所以承载情节的装置永远不能 omit，宁可 footnote。
    """

    none = "none"          # 纯修辞，舍了只损失趣味
    flavor = "flavor"      # 塑造人物或氛围，舍了角色变薄
    setup = "setup"        # 伏笔，后文有回扣，舍了后文断裂
    pivot = "pivot"        # 情节转折本身就靠它，绝不可舍


class Volatility(str, Enum):
    """时效性。网络梗会过期 —— 三年后没人知道「绝绝子」是什么。

    高时效的梗直译到目标语言更糟：目标读者既不懂源文化，
    这个梗在源文化里也快死了，等于为一个即将消失的东西付出理解成本。
    """

    evergreen = "evergreen"  # 成语、经典典故，几百年不变
    decade = "decade"        # 一代人的共同记忆
    years = "years"          # 几年热度的流行语
    months = "months"        # 短命网络梗


def choose_strategy(
    load: CulturalLoad, plot: PlotLoad, vol: Volatility,
) -> DeviceStrategy:
    """三维定策略。只看文化依赖度会做出两类错判。

    第一类：高依赖 + 承载情节。按依赖度该「舍了补偿」，
    但那是伏笔 —— 舍了后文回扣就落空。这种宁可 footnote 出戏，
    也不能让读者在三十页后遇到一个没有来处的呼应。

    第二类：高依赖 + 短命网络梗。按依赖度该费力找等价物，
    可这梗在源文化里都快死了，值不上目标读者的理解成本 ——
    直接归化重写，读者拿到的是效果，不是考古。

    返回的是默认值，人工与模型都可覆盖。
    """
    # 情节转折靠它 —— 无论多难翻都必须让读者拿到，代价其次
    if plot is PlotLoad.pivot:
        return (
            DeviceStrategy.substitute if load is not CulturalLoad.high
            else DeviceStrategy.gloss_inline
        )
    # 伏笔要留住指向性，等价物找不到就轻注，绝不舍
    if plot is PlotLoad.setup and load is CulturalLoad.high:
        return DeviceStrategy.gloss_inline
    # 短命梗不值得考古，直接按目标习惯重写
    if vol in (Volatility.months, Volatility.years) and load is CulturalLoad.high:
        return DeviceStrategy.naturalize
    return {
        CulturalLoad.low: DeviceStrategy.preserve,
        CulturalLoad.medium: DeviceStrategy.substitute,
        CulturalLoad.high: (
            DeviceStrategy.transplant if plot is PlotLoad.flavor
            else DeviceStrategy.compensate
        ),
    }[load]


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
    #: 承载多少情节 —— 决定「能不能舍」
    plot_load: Mapped[PlotLoad] = mapped_column(default=PlotLoad.none, nullable=False)
    #: 时效性 —— 短命网络梗不值得让目标读者付理解成本
    volatility: Mapped[Volatility] = mapped_column(
        default=Volatility.evergreen, nullable=False
    )
    #: 走 gloss_inline / footnote 时的注释文本
    gloss_text: Mapped[str | None] = mapped_column(Text)
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
