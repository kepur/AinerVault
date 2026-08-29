"""导读篇 —— 正文之前先把体系交代清楚。

## 为什么它不是可选的附加功能

修仙的「练气→筑基→金丹→元婴」，科幻的自造技术名词，
在目标语里没有任何对应物。不解释，读者读不懂；
就地解释，正文里每个术语第一次出现都要停下来讲一段，节奏全毁 ——
而这类术语在一本仙侠里有几十个。

日式轻小说英译早就解决了这件事：**正文前放一篇导读**，
把体系一次讲完；正文里就可以直接用音译词，读者已经有挂靠点了。

所以导读**改变了每一处的策略选择**：

    没有导读   境界名只能逐处 gloss_inline，读者每隔两页被打断一次
    有了导读   同样的词可以 preserve，读者读到的是原物

`covers_json` 记的就是「导读讲过哪些词条」，
它会回流到 choose_strategy 的 explained 参数。
不回流的话，导读写了也白写 —— 正文照样逐处解释，
读者读完导读再被解释一遍。

## 与脚注的分工

脚注解决**单点**的典故；导读解决**体系**。
一个成语用脚注，一套境界体系用导读。
拿脚注去讲体系，等于把一篇导读拆成三十条注释散在正文里。
"""
from __future__ import annotations

import enum

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, StdMixin
from app.models.world import ReviewStatus


class PrimerKind(str, enum.Enum):
    """导读讲的是哪一类东西。分开是因为它们的写法完全不同。"""

    #: 体系：境界、修为、力量等级、技术设定。**最需要导读的一类** ——
    #: 它有内部结构，逐处解释永远讲不清「这一级比那一级高多少」
    system = "system"
    #: 称谓与身份：师尊／道友／前辈，宗门辈分
    address = "address"
    #: 度量与货币：里、两、灵石
    measure = "measure"
    #: 世界与地理：九州、修真界的地理格局
    setting = "setting"
    #: 类型约定：这一类作品在目标语里的既有读法
    #: （英语读者读日式轻小说已经习惯了什么，读中式仙侠又该习惯什么）
    convention = "convention"


class WorldPrimer(Base, StdMixin):
    """一次映射的导读篇。

    挂 transform 而不是 novel：同一本书译到不同圈层，
    要讲的东西不一样 —— 译到英语科幻圈层要解释的，
    译到日语轻小说圈层可能读者本来就懂。
    """

    __tablename__ = "world_primers"
    __table_args__ = (
        Index("ix_world_primers_transform", "transform_id", "status"),
    )

    transform_id: Mapped[str] = mapped_column(
        ForeignKey("world_transforms.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    title: Mapped[str | None] = mapped_column(String(256))
    #: 分节的导读正文，[{kind, heading, body, covers:[canonical_key]}]
    sections_json: Mapped[list | None] = mapped_column(JSONB)
    #: 拼好的完整正文，直接放在译本第一章之前
    body: Mapped[str | None] = mapped_column(Text)
    #: **导读讲过哪些词条**（world_lexicon 的 canonical_key）。
    #: 这一栏是导读与正文的接口：讲过的词，正文里可以直接用原物，
    #: 不必再就地解释。不落库的话导读写了也白写
    covers_json: Mapped[list | None] = mapped_column(JSONB)
    #: 读者读完导读要花的力气 —— 太长没人读，太短讲不清。
    #: 词数落库以便审核时一眼看出这两种失败
    word_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    model: Mapped[str | None] = mapped_column(String(128))
    rationale: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ReviewStatus] = mapped_column(
        default=ReviewStatus.candidate, nullable=False
    )
    edited_by_human: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
