"""文化梗词表：网络流行语、亚文化黑话、典故、品牌指涉。

为什么不塞进 world_lexicon —— 那张表管的是「物」：客栈、捕快、长剑，
一物一译，跨章节稳定。梗管的是「用法」，性质完全不同：

  会过期      「绝绝子」三年后没人认识，「醉里挑灯看剑」一千年还在
  分平台      B 站梗和抖音梗不通用，说错平台等于说错圈子
  分圈层      同一句话在饭圈是褒、在游戏圈是贬
  字面无用    「破防了」字面是防御被击穿，实际指情绪失守，直译必错

而且梗是**可复用条目**（一本书里出现十次是同一个梗），
narrative_devices 是**一次性实例**（这一句的这个手法）。两者一对多。

同一个梗在不同目标圈层的渲染也不同：「内卷」到现代美国是 rat race，
到维多利亚英国没有对应词，只能归化成一句描述。所以渲染挂 world_profile。
"""
from __future__ import annotations

import enum

from sqlalchemy import (
    Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, StdMixin
from app.models.narrative_device import DeviceStrategy, PlotLoad, Volatility
from app.models.world import ReviewStatus


class MemeRegister(str, enum.Enum):
    """梗的来源类型 —— 决定该去哪里找目标文化的对应物。"""

    internet_slang = "internet_slang"      # 网络流行语：yyds、破防了、栓Q
    subculture = "subculture"              # 亚文化黑话：二次元、饭圈、游戏圈
    classical_allusion = "classical_allusion"  # 典故：庄周梦蝶、破釜沉舟
    idiom_proverb = "idiom_proverb"        # 成语俗语：塞翁失马
    dialect = "dialect"                    # 方言词：瓷实、嘎哈呢
    brand_ref = "brand_ref"                # 品牌／产品指涉：老干妈、五菱宏光
    media_ref = "media_ref"                # 影视歌曲引用
    historical_event = "historical_event"  # 历史事件指涉
    social_phenomenon = "social_phenomenon"  # 社会现象词：内卷、躺平、鸡娃
    taboo_euphemism = "taboo_euphemism"    # 禁忌与委婉语


class MemeEntry(Base, StdMixin):
    """一个梗的源侧档案。与目标文化无关，先把它是什么说清楚。"""

    __tablename__ = "meme_entries"
    __table_args__ = (
        UniqueConstraint("novel_id", "surface", name="uq_meme_novel_surface"),
        Index("ix_meme_entries_register", "novel_id", "register"),
    )

    novel_id: Mapped[str | None] = mapped_column(
        ForeignKey("novels.id", ondelete="CASCADE")
    )
    surface: Mapped[str] = mapped_column(String(128), nullable=False)
    aliases_json: Mapped[list | None] = mapped_column(JSONB)
    register: Mapped[MemeRegister] = mapped_column(
        default=MemeRegister.internet_slang, nullable=False
    )
    #: 字面义。几乎总是与实际用法脱节 —— 这正是直译会错的原因
    literal_gloss: Mapped[str | None] = mapped_column(Text)
    #: 实际用法、语气、褒贬。翻译真正要传达的是这个
    actual_use: Mapped[str] = mapped_column(Text, nullable=False)
    #: 出处：哪个作品／事件／平台
    origin: Mapped[str | None] = mapped_column(Text)
    origin_year: Mapped[int | None] = mapped_column(Integer)
    #: 流通圈层：饭圈／游戏／职场／通用
    circle: Mapped[str | None] = mapped_column(String(64))
    #: 平台：B站／微博／抖音／贴吧
    platform: Mapped[str | None] = mapped_column(String(64))
    volatility: Mapped[Volatility] = mapped_column(
        default=Volatility.evergreen, nullable=False
    )
    plot_load: Mapped[PlotLoad] = mapped_column(default=PlotLoad.none, nullable=False)
    #: 出现次数与证据，供审核判断值不值得费力处理
    occurrences: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    evidence_json: Mapped[list | None] = mapped_column(JSONB)
    status: Mapped[ReviewStatus] = mapped_column(
        default=ReviewStatus.candidate, nullable=False
    )
    locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class MemeRendering(Base, StdMixin):
    """一个梗在一个目标圈层里怎么呈现。

    挂 world_profile 而非 transform：同一个「内卷」译到现代美国就是 rat race，
    这个结论与源世界观无关，可跨小说复用。
    """

    __tablename__ = "meme_renderings"
    __table_args__ = (
        UniqueConstraint(
            "meme_id", "world_profile_id", name="uq_meme_rendering_meme_profile"
        ),
        Index("ix_meme_renderings_profile", "world_profile_id", "status"),
    )

    meme_id: Mapped[str] = mapped_column(
        ForeignKey("meme_entries.id", ondelete="CASCADE"), nullable=False
    )
    world_profile_id: Mapped[str] = mapped_column(
        ForeignKey("world_profiles.id", ondelete="CASCADE"), nullable=False
    )
    strategy: Mapped[DeviceStrategy] = mapped_column(
        default=DeviceStrategy.substitute, nullable=False
    )
    #: 替换用的目标文本。strategy 为 footnote 时正文不动，这里可为空
    target_text: Mapped[str | None] = mapped_column(Text)
    #: gloss_inline 的行内补充，或 footnote 的注释正文
    gloss_text: Mapped[str | None] = mapped_column(Text)
    #: 为什么选这个策略、这个词。审核时要能判断而不是只能信
    rationale: Mapped[str | None] = mapped_column(Text)
    #: 目标圈层里等价物的候选，供人工挑
    candidates_json: Mapped[list | None] = mapped_column(JSONB)
    #: 目标文化里也是网络梗时记下它的时效，避免译出一个更快过期的东西
    target_volatility: Mapped[Volatility | None] = mapped_column()
    status: Mapped[ReviewStatus] = mapped_column(
        default=ReviewStatus.candidate, nullable=False
    )
    locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
