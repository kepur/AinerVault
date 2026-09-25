"""Director Core：场景协议快照、渲染任务、产物。

一次「渲控制素材」或「出成片」= 一个任务；任务的输入里有当时的协议快照和烘焙数据的位置，
事后改了场景也不影响已经出好的素材（素材能追溯到它是按哪一版场景渲的）。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, StdMixin


class DirectorScene(Base, StdMixin):
    """一份 Ainer Scene Protocol v1 场景。

    source=3dbox：从 3D-BOX 项目导出（项目是真身，这里是导出时的快照，重导出会更新）；
    source=llm / api：协议是真身（JSON 优先），会生成一个 3D-BOX 项目方便在台上看和改。
    """

    __tablename__ = "director_scenes"

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="api")
    box_project_id: Mapped[str | None] = mapped_column(String(32), index=True)
    protocol_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: 生成它的那句话、LLM 的备注
    prompt: Mapped[str | None] = mapped_column(Text)
    notes_json: Mapped[dict | None] = mapped_column(JSONB)


class DirectorJob(Base, StdMixin):
    """渲染任务：blender_render（控制素材）/ final_render（成片）/ ue_render（V1 关闭）。"""

    __tablename__ = "director_jobs"

    scene_id: Mapped[str | None] = mapped_column(ForeignKey("director_scenes.id", ondelete="SET NULL"), index=True)
    parent_id: Mapped[str | None] = mapped_column(String(32), index=True)
    job_type: Mapped[str] = mapped_column(String(24), nullable=False)
    #: queued / running / succeeded / failed / cancelled
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued", index=True)
    #: blender / ltx_097 / ltx_25 / ue
    backend: Mapped[str] = mapped_column(String(16), nullable=False)
    input_json: Mapped[dict | None] = mapped_column(JSONB)
    progress_json: Mapped[dict | None] = mapped_column(JSONB)
    output_manifest_json: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DirectorOutput(Base, StdMixin):
    """任务产物：preview / clay / depth / pose / canny / first_frame / camera_json / motion_json / blend / final。"""

    __tablename__ = "director_outputs"

    job_id: Mapped[str] = mapped_column(ForeignKey("director_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    #: 任务目录里的相对路径（全部产物都在）
    path: Mapped[str] = mapped_column(String(512), nullable=False)
    #: 视频、图片另存一份进媒体库（稳定的 /media 地址，网关和前端都拿它）
    asset_id: Mapped[str | None] = mapped_column(String(32))
    url: Mapped[str | None] = mapped_column(String(1024))
    bytes: Mapped[int | None] = mapped_column(Integer)
    meta_json: Mapped[dict | None] = mapped_column(JSONB)
