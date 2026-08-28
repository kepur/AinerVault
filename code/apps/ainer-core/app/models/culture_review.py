"""文化差异审查：LLM 出报表，人来拍板。

和 review.py 那套的分工不同 —— 那套查的是**违规**：音译残留、
名物没换、锁定译名没用上，都是能机器判定对错的硬伤。

这套查的是**差异**：原文的中国读者读到这里会笑，目标读者不会；
原文的「师父」二字带的敬意，译文的 Master 承载不了；
原文一句「你也配」的杀伤力，译文平白了。这些没有对错，只有判断，
所以流程必须是「模型提方案 → 人裁决」，不能自动改。

裁决四态对应人真实会做的四件事：
    同意        方案照用
    修改        人给一个更好的
    补充        方案对但不完整，加一条
    驳回        方案错了或此处无需处理
「补充」不能省 —— 它是最常见的一种：模型指出了问题、给的解法只对一半，
只有同意/驳回两个选项时，人只能选驳回然后从头写，等于白审一遍。
"""
from __future__ import annotations

import enum

from sqlalchemy import (
    Boolean, ForeignKey, Index, Integer, String, Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, StdMixin


class GapKind(str, enum.Enum):
    """差异类型 —— 决定该由哪条管线去修。"""

    humor_lost = "humor_lost"              # 笑点没了
    emotion_flattened = "emotion_flattened"  # 情绪被抹平
    register_mismatch = "register_mismatch"  # 语体错位（该正式的口语化了）
    relation_lost = "relation_lost"        # 人物关系的亲疏没传达出来
    subtext_lost = "subtext_lost"          # 言外之意丢失
    allusion_opaque = "allusion_opaque"    # 典故目标读者读不懂
    meme_untranslated = "meme_untranslated"  # 梗直译了
    cultural_assumption = "cultural_assumption"  # 依赖源文化常识，目标读者缺前提
    anachronism = "anachronism"            # 用了目标世界观年代不该有的词物
    taboo_shift = "taboo_shift"            # 禁忌尺度错位（源文可说，目标文化冒犯）
    pacing_shift = "pacing_shift"          # 节奏变了（长句拖垮了原文的短促）
    overtranslation = "overtranslation"    # 过度解释，把留白说破了


class Verdict(str, enum.Enum):
    accepted = "accepted"      # 同意，照方案改
    modified = "modified"      # 人改了方案
    supplemented = "supplemented"  # 方案不全，人补了一条
    rejected = "rejected"      # 驳回
    pending = "pending"        # 待裁决


class ReviewRunStatus(str, enum.Enum):
    running = "running"
    completed = "completed"
    failed = "failed"


class CultureReview(Base, StdMixin):
    """一次文化差异审查。一章一次，可重跑。"""

    __tablename__ = "culture_reviews"
    __table_args__ = (
        Index("ix_culture_reviews_scope", "chapter_id", "transform_id", "created_at"),
    )

    chapter_id: Mapped[str] = mapped_column(
        ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False
    )
    transform_id: Mapped[str] = mapped_column(
        ForeignKey("world_transforms.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[ReviewRunStatus] = mapped_column(
        default=ReviewRunStatus.running, nullable=False
    )
    tier: Mapped[str] = mapped_column(String(16), default="critical", nullable=False)
    model: Mapped[str | None] = mapped_column(String(128))
    #: 总体评价：这一章的译本离原文的阅读体验有多远
    verdict_summary: Mapped[str | None] = mapped_column(Text)
    #: 0–100。不是翻译准确度，是「目标读者拿到的体验」的还原度
    fidelity_score: Mapped[int | None] = mapped_column(Integer)
    by_kind_json: Mapped[dict | None] = mapped_column(JSONB)
    findings_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    resolved_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_json: Mapped[dict | None] = mapped_column(JSONB)


class CultureFinding(Base, StdMixin):
    """一条差异发现 + 模型的整改方案 + 人的裁决。"""

    __tablename__ = "culture_findings"
    __table_args__ = (
        Index("ix_culture_findings_review", "review_id", "severity"),
        Index("ix_culture_findings_verdict", "review_id", "verdict"),
    )

    review_id: Mapped[str] = mapped_column(
        ForeignKey("culture_reviews.id", ondelete="CASCADE"), nullable=False
    )
    block_id: Mapped[str | None] = mapped_column(String(32), index=True)
    kind: Mapped[GapKind] = mapped_column(nullable=False)
    #: 1–5。5 = 目标读者会明显觉得不对劲
    severity: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    source_excerpt: Mapped[str | None] = mapped_column(Text)
    target_excerpt: Mapped[str | None] = mapped_column(Text)
    #: 中文读者读到这里得到什么
    source_effect: Mapped[str | None] = mapped_column(Text)
    #: 目标读者读到这里得到什么。两者的落差就是这条 finding
    target_effect: Mapped[str | None] = mapped_column(Text)
    gap_explain: Mapped[str] = mapped_column(Text, nullable=False)
    #: 模型给的整改方案
    proposal: Mapped[str | None] = mapped_column(Text)
    #: 改完之后那一句长什么样，可直接采用
    proposed_text: Mapped[str | None] = mapped_column(Text)
    #: 该由哪条管线去修：lexicon / appellation / meme / device / retranslate
    fix_channel: Mapped[str | None] = mapped_column(String(32))

    verdict: Mapped[Verdict] = mapped_column(default=Verdict.pending, nullable=False)
    #: 人给的最终文本（modified）或补充意见（supplemented）
    human_text: Mapped[str | None] = mapped_column(Text)
    human_note: Mapped[str | None] = mapped_column(Text)
    #: 裁决后是否已落到译文里
    applied: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
