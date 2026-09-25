"""预设库：风格、运镜、特效、题材、场景模板、发型、服装、官方角色……

LibTV 的「风格广场／运镜广场／特效广场／爆款预设」都是数据不是代码：一条 = 名字＋封面＋
一段模板（提示词、参数）。这里同一张表按 kind 分，payload_json 放各自的内容。
"""
from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, StdMixin


class Preset(Base, StdMixin):
    __tablename__ = "presets"
    __table_args__ = (UniqueConstraint("kind", "key", name="uq_presets_kind_key"),)

    #: style / camera_move / effect / genre / scene_template / hairstyle / outfit / character / expression
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str | None] = mapped_column(String(64), index=True)
    cover_url: Mapped[str | None] = mapped_column(String(1024))
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    tags_json: Mapped[list | None] = mapped_column(JSONB)
    author: Mapped[str | None] = mapped_column(String(64))
    official: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    commercial: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    uses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sort: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class PresetMark(Base, StdMixin):
    """收藏与最近使用（updated_at 就是最近一次用的时间）。"""

    __tablename__ = "preset_marks"
    __table_args__ = (UniqueConstraint("preset_id", "mark", "workspace_id", name="uq_preset_marks"),)

    preset_id: Mapped[str] = mapped_column(
        ForeignKey("presets.id", ondelete="CASCADE"), nullable=False, index=True)
    #: favorite / recent
    mark: Mapped[str] = mapped_column(String(16), nullable=False)
