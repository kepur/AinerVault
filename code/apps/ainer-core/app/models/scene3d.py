"""3D-BOX 预演：场景项目与对话。

一个场景项目 = 一个小小的虚拟工程：files_json 里是场景脚本（scene.js）和智能体的笔记，
脚本在沙箱里跑出场景文档（compiled_json），前端只渲染文档。导演在台上手动拖动的改动
存在 overrides_json（按物体/机位 id），脚本重跑后覆盖回去 —— 手改和智能体改互不冲掉。
"""
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, StdMixin


class SceneProject(Base, StdMixin):
    __tablename__ = "scene_projects"

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    #: 可选：挂到哪部小说／哪个分镜计划／哪场戏，导出的预演视频跟着走
    novel_id: Mapped[str | None] = mapped_column(String(32), index=True)
    shot_plan_id: Mapped[str | None] = mapped_column(String(32), index=True)
    scene_id: Mapped[str | None] = mapped_column(String(32))
    template: Mapped[str | None] = mapped_column(String(64))
    #: 虚拟文件系统 {路径: 内容}；scene.js 是入口
    files_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: 手动改动 {objects:{id:{pos,rot,scale,color,hidden}}, cameras:{id:{keys,lens}}, cuts:[…]}
    overrides_json: Mapped[dict | None] = mapped_column(JSONB)
    #: 最近一次编译出的场景文档与诊断
    compiled_json: Mapped[dict | None] = mapped_column(JSONB)
    diagnostics_json: Mapped[dict | None] = mapped_column(JSONB)
    #: 文件历史 [{at, by, note, files}]，最多留 40 版
    versions_json: Mapped[list | None] = mapped_column(JSONB)
    settings_json: Mapped[dict | None] = mapped_column(JSONB)
    seed: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    thumb_url: Mapped[str | None] = mapped_column(String(1024))


class SceneMessage(Base, StdMixin):
    """对话记录：用户的话、智能体的话、每一步工具调用。"""

    __tablename__ = "scene_messages"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("scene_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    run_id: Mapped[str | None] = mapped_column(String(32), index=True)
    #: user / assistant / tool / error
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    meta_json: Mapped[dict | None] = mapped_column(JSONB)
