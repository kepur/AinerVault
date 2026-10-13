"""空间世界（World DB）：小说里“地方”的唯一真相源。

注意与 ``models/world.py`` 区分：那里的 World* 是**世界观转译**（中国古代→昭和日本），
这里是**空间**世界：区域、chunk 栅格、地标、通路、资产实例、带出处的事实、章节增量与版本，
以及“一场戏只演一次”的表演和逐镜机位（take）。

坐标：米，Z 向上（与 Blender 一致）。设计见 docs/studio/world_greybox_pipeline.md。
"""
from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, StdMixin

#: 版本区间的“仍然有效”
OPEN_VERSION = 2_147_483_647


class SpatialWorld(Base, StdMixin):
    __tablename__ = "world_spaces"

    novel_id: Mapped[str | None] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    units: Mapped[str] = mapped_column(String(8), default="m", nullable=False)
    up_axis: Mapped[str] = mapped_column(String(2), default="Z", nullable=False)
    chunk_size_m: Mapped[float] = mapped_column(Float, default=8.0, nullable=False)
    current_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    style_ref: Mapped[dict | None] = mapped_column(JSONB)


class WorldVersion(Base, StdMixin):
    __tablename__ = "world_versions"
    __table_args__ = (UniqueConstraint("world_id", "n", name="uq_world_version_n"),)

    world_id: Mapped[str] = mapped_column(ForeignKey("world_spaces.id", ondelete="CASCADE"), nullable=False)
    n: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_n: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)
    delta_id: Mapped[str | None] = mapped_column(String(32))


class _Versioned:
    valid_from_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    valid_to_version: Mapped[int] = mapped_column(Integer, default=OPEN_VERSION, nullable=False)


class WorldRegion(Base, StdMixin, _Versioned):
    __tablename__ = "world_regions"
    __table_args__ = (UniqueConstraint("world_id", "stable_key", "valid_from_version", name="uq_world_region_key"),)

    world_id: Mapped[str] = mapped_column(ForeignKey("world_spaces.id", ondelete="CASCADE"), nullable=False, index=True)
    stable_key: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str | None] = mapped_column(String(256))
    kind: Mapped[str] = mapped_column(String(32), default="room", nullable=False)
    parent_id: Mapped[str | None] = mapped_column(String(32))
    #: {"min": [x, y, z], "max": [x, y, z]}
    bounds_aabb: Mapped[dict] = mapped_column(JSONB, nullable=False)
    anchor_xform: Mapped[dict | None] = mapped_column(JSONB)
    lod: Mapped[str] = mapped_column(String(4), default="L0", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="provisional", nullable=False)
    locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    aliases: Mapped[list | None] = mapped_column(JSONB)
    description: Mapped[str | None] = mapped_column(Text)
    geometry_rev: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class WorldChunk(Base, StdMixin):
    __tablename__ = "world_chunks"
    __table_args__ = (
        UniqueConstraint("world_id", "region_id", "cx", "cy", name="uq_world_chunk_cell"),
        Index("ix_world_chunk_grid", "world_id", "cx", "cy"),
    )

    world_id: Mapped[str] = mapped_column(ForeignKey("world_spaces.id", ondelete="CASCADE"), nullable=False)
    region_id: Mapped[str] = mapped_column(ForeignKey("world_regions.id", ondelete="CASCADE"), nullable=False)
    cx: Mapped[int] = mapped_column(Integer, nullable=False)
    cy: Mapped[int] = mapped_column(Integer, nullable=False)
    lod: Mapped[str] = mapped_column(String(4), default="L0", nullable=False)
    rev: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class WorldLandmark(Base, StdMixin, _Versioned):
    __tablename__ = "world_landmarks"
    __table_args__ = (UniqueConstraint("region_id", "key", "valid_from_version", name="uq_world_landmark_key"),)

    region_id: Mapped[str] = mapped_column(ForeignKey("world_regions.id", ondelete="CASCADE"), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), default="spot", nullable=False)
    pos: Mapped[list] = mapped_column(JSONB, nullable=False)
    facing_deg: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    size: Mapped[list | None] = mapped_column(JSONB)
    description: Mapped[str | None] = mapped_column(Text)


class WorldPortal(Base, StdMixin, _Versioned):
    __tablename__ = "world_portals"

    world_id: Mapped[str] = mapped_column(ForeignKey("world_spaces.id", ondelete="CASCADE"), nullable=False, index=True)
    from_region_id: Mapped[str] = mapped_column(ForeignKey("world_regions.id", ondelete="CASCADE"), nullable=False)
    to_region_id: Mapped[str] = mapped_column(ForeignKey("world_regions.id", ondelete="CASCADE"), nullable=False)
    landmark_id: Mapped[str | None] = mapped_column(String(32))
    traversable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class WorldAsset(Base, StdMixin):
    __tablename__ = "world_assets"

    world_id: Mapped[str] = mapped_column(ForeignKey("world_spaces.id", ondelete="CASCADE"), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)          # building / prop / character / structure
    name: Mapped[str | None] = mapped_column(String(256))
    dims_m: Mapped[list | None] = mapped_column(JSONB)                    # [w, d, h]
    front_axis: Mapped[str] = mapped_column(String(4), default="-Y", nullable=False)
    rig: Mapped[str | None] = mapped_column(String(32))                   # mixamo / null
    mesh_path: Mapped[str | None] = mapped_column(Text)
    entity_id: Mapped[str | None] = mapped_column(String(64))             # 角色/道具对应的剧情实体
    meta: Mapped[dict | None] = mapped_column(JSONB)


class WorldInstance(Base, StdMixin, _Versioned):
    __tablename__ = "world_instances"
    __table_args__ = (UniqueConstraint("region_id", "key", "valid_from_version", name="uq_world_instance_key"),)

    region_id: Mapped[str] = mapped_column(ForeignKey("world_regions.id", ondelete="CASCADE"), nullable=False, index=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("world_assets.id", ondelete="CASCADE"), nullable=False)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    #: {"pos": [x,y,z], "rot_deg": [rx,ry,rz], "scale": [sx,sy,sz]}
    xform: Mapped[dict] = mapped_column(JSONB, nullable=False)
    collision: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    nav_flags: Mapped[dict | None] = mapped_column(JSONB)
    rev: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class WorldFact(Base, StdMixin):
    __tablename__ = "world_facts"
    __table_args__ = (Index("ix_world_fact_subject", "world_id", "subject_key"),)

    world_id: Mapped[str] = mapped_column(ForeignKey("world_spaces.id", ondelete="CASCADE"), nullable=False)
    subject_kind: Mapped[str] = mapped_column(String(16), nullable=False)  # region / instance / landmark / world
    subject_key: Mapped[str] = mapped_column(String(128), nullable=False)
    predicate: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[dict | list | str | float | None] = mapped_column(JSONB)
    source: Mapped[str] = mapped_column(String(16), default="inferred", nullable=False)  # explicit / inferred / user
    chapter_id: Mapped[str | None] = mapped_column(String(32))
    evidence_span: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    version_n: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class WorldDelta(Base, StdMixin):
    __tablename__ = "world_deltas"

    world_id: Mapped[str] = mapped_column(ForeignKey("world_spaces.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter_id: Mapped[str | None] = mapped_column(String(32), index=True)
    base_version: Mapped[int] = mapped_column(Integer, nullable=False)
    ops: Mapped[list] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="proposed", nullable=False)
    result_version: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)
    report: Mapped[dict | None] = mapped_column(JSONB)


class WorldPerformance(Base, StdMixin):
    """一场戏只演一次。tracks: {actor_key: {entity_id, asset_key, keys:[{t_ms,pos,yaw_deg}], clips:[{clip,start_ms,end_ms,target?}]}}"""

    __tablename__ = "world_performances"
    __table_args__ = (Index("ix_world_perf_scene", "world_id", "scene_key"),)

    world_id: Mapped[str] = mapped_column(ForeignKey("world_spaces.id", ondelete="CASCADE"), nullable=False)
    world_version: Mapped[int] = mapped_column(Integer, nullable=False)
    scene_key: Mapped[str] = mapped_column(String(64), nullable=False)
    region_key: Mapped[str] = mapped_column(String(128), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    fps: Mapped[int] = mapped_column(Integer, default=24, nullable=False)
    tracks: Mapped[dict] = mapped_column(JSONB, nullable=False)
    mood: Mapped[dict | None] = mapped_column(JSONB)
    director_scene_id: Mapped[str | None] = mapped_column(String(32))
    check_report: Mapped[dict | None] = mapped_column(JSONB)
    rev: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class WorldTake(Base, StdMixin):
    """一镜 = 同一表演的时间窗 + 一台相机。camera: {pos, target, lens_mm, move:{type, amount}}"""

    __tablename__ = "world_takes"
    __table_args__ = (UniqueConstraint("performance_id", "shot_key", name="uq_world_take_shot"),)

    performance_id: Mapped[str] = mapped_column(ForeignKey("world_performances.id", ondelete="CASCADE"), nullable=False, index=True)
    shot_key: Mapped[str] = mapped_column(String(128), nullable=False)
    order_no: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    camera: Mapped[dict] = mapped_column(JSONB, nullable=False)
    route: Mapped[str | None] = mapped_column(String(32))
    fps: Mapped[int] = mapped_column(Integer, default=8, nullable=False)
    focus: Mapped[list | None] = mapped_column(JSONB)
    mood: Mapped[str | None] = mapped_column(String(32))
    frozen_deps: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), default="planned", nullable=False)
    outputs: Mapped[dict | None] = mapped_column(JSONB)


class WorldGreyboxSwitch(Base, StdMixin):
    """world-greybox 闭环的**可选**开关（默认关；原动态漫剧/导演管线是默认路径）。

    scope_kind：novel / chapter / production / plan / shot；越具体越优先（shot > plan > chapter/production > novel）。
    fallback_to_original：greybox 闸门不过时这一镜回退原管线的成片。总开关在 feature_flags.yaml 的 world_greybox_enabled。
    """

    __tablename__ = "world_greybox_switches"
    __table_args__ = (UniqueConstraint("scope_kind", "scope_id", name="uq_world_greybox_scope"),)

    scope_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_id: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    fallback_to_original: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)


class WorldPipelineRun(Base, StdMixin):
    """一次 world-greybox 闭环运行（可续跑）：config 描述输入，state 存逐镜尝试/QA/选择。"""

    __tablename__ = "world_pipeline_runs"

    world_id: Mapped[str] = mapped_column(ForeignKey("world_spaces.id", ondelete="CASCADE"), nullable=False, index=True)
    scope_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)  # pending/running/done/failed/cancelled
    progress: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    state: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    out_dir: Mapped[str] = mapped_column(Text, nullable=False)
