"""创作画布（ainer-studio ?view=flow）的画布文档，和画布上跑的出片工作流。

一个章节可以有很多张画布：
  plan   整章总览：一份分镜计划一张（部分唯一索引），和「分镜画布」一一对应，章节视频从这里串起来
  scene  场次画布：按剧本场次自动分，长场次再按镜头数切段（scope_json 记着它管哪些镜头）
  custom 自建画布：任意镜头集合，或者不挂分镜的空白画布（旅拍、相册、外部系统调用）

doc_json 只存布局：节点位置、引用（shot / scene / 角色视角 / 3D-BOX 项目 …）、用户自己连的边和少量视图状态。
派生节点的内容每次从后端现取 —— 画布不当第二份数据源（HANDOVER §3.2）。
不放进 ShotPlan.config_json：PATCH /image-style 会整段重写它（shots.py），画布一保存就可能被冲掉。

version 是乐观锁：每次 PUT 带 base_version，对不上就 409，前端提示「画布在别处被改过」。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, StdMixin


class StudioBoard(Base, StdMixin):
    __tablename__ = "studio_boards"
    #: 整章总览一份计划只许一张（两个标签页同时首存时后到的撞索引 → 409）；场次画布、自建画布不限
    __table_args__ = (
        Index("uq_studio_boards_plan_overview", "shot_plan_id", unique=True, postgresql_where=text("kind = 'plan'")),
    )

    #: plan / scene / custom（见文件头）
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="plan", server_default=text("'plan'"))
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default=text("''"))
    #: 计划删了画布跟着删；自建的空白画布可以不挂计划
    shot_plan_id: Mapped[str | None] = mapped_column(
        ForeignKey("shot_plans.id", ondelete="CASCADE"), index=True)
    #: 冗余：按章节、按小说列画布用；计划换章节不可能，所以不怕不一致
    chapter_id: Mapped[str | None] = mapped_column(String(32), index=True)
    novel_id: Mapped[str | None] = mapped_column(String(32), index=True)
    #: 这张画布管哪些镜头 {"scene_ids": [...], "shot_ids": [...]}；整章总览为空 = 全部
    scope_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    #: 同一章里的排序（自动分的按场次顺序）
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    #: auto（按场次自动分的）/ user（画布上新建的）/ api（外部系统建的）
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="auto", server_default=text("'auto'"))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    #: schema = "ainer.board/v1"，形状见前端 src/canvas/model.ts 的 CanvasDoc
    doc_json: Mapped[dict] = mapped_column(JSONB, nullable=False)


class StudioRun(Base, StdMixin):
    """画布上的「一键出片」：一组镜头按顺序走 配音 → 3D 导演出片（LLM 搭白模/运镜 → Blender → 身份首帧 → LTX 2.5）。

    状态全在库里（items_json 每镜一条），core 重启后后台线程接着推进，不丢进度。
    一次只推进一镜：导演任务本来就在单线程队列里串行，一镜跑完再交下一镜，片子能一条条先出来。
    """
    __tablename__ = "studio_runs"

    board_id: Mapped[str | None] = mapped_column(ForeignKey("studio_boards.id", ondelete="SET NULL"), index=True)
    shot_plan_id: Mapped[str] = mapped_column(ForeignKey("shot_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    #: queued / running / succeeded / failed / cancelled（failed = 有镜头失败；其余镜头照样跑完）
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued", index=True)
    #: fast（768×448，默认）/ hd（1024×576）
    profile: Mapped[str] = mapped_column(String(16), nullable=False, default="fast")
    #: {"audio": "auto|generate|none", "only_missing": bool, "reuse_scene": bool}
    options_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: [{"shot_id", "order_no", "step": "audio|director|done", "status", "error", "blender_job_id", "started_at", "finished_at"}]
    items_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    error: Mapped[str | None] = mapped_column(String(500))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StudioNodeRun(Base, StdMixin):
    """画布上一个配方节点的一次运行（服务端执行器 pipelines/canvas_exec.py）。

    纳逗式画布的每个生成节点都带配方（提示词 + @引用 + 参数）；执行器按配方在后端跑，
    关了浏览器照跑，结果先落这里，前端轮询 node-runs 再填回节点的 media。
    为什么不直接改画布文档：文档有乐观锁，浏览器开着时后端一写就和前端的防抖保存撞 409；
    而且一个节点重跑多次，每次跑的是哪一版配方、出了什么，都要留底（换回旧图、判断「配方改过该重跑」）。

    一个节点可以有很多行（每跑一次一行），「当前结果」= 最近一次 succeeded 的那行。
    """
    __tablename__ = "studio_node_runs"
    __table_args__ = (
        # node-runs 接口按画布取每个节点最近一次：(board_id, node_id, created_at) 正好覆盖
        Index("ix_studio_node_runs_board_node_created", "board_id", "node_id", "created_at"),
    )

    #: 画布删了运行记录跟着删（结果的媒体是 Asset，还在媒体库里）
    board_id: Mapped[str] = mapped_column(
        ForeignKey("studio_boards.id", ondelete="CASCADE"), nullable=False, index=True)
    #: 画布文档里的节点 id（自由节点是随机 id，想法画布是 idea:frame:1 这类稳定 id）
    node_id: Mapped[str] = mapped_column(String(120), nullable=False)
    #: 配方的 op：image / video / sheet / concat / last_frame / one_take
    op: Mapped[str] = mapped_column(String(16), nullable=False)
    #: queued / waiting / running / succeeded / failed / cancelled / skipped
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued", index=True)
    #: 跑的那一版配方的哈希：和节点现在的配方对不上 = 配方改过、该重跑
    recipe_hash: Mapped[str | None] = mapped_column(String(64))
    #: 跑的那一版配方快照（开跑时从库里的文档取，不是排队时）
    recipe_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    #: 交给能力层的 gen_tasks id（count>1 时几条；sheet 的面板任务由 char_sheet 自己管，不记在这）
    task_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    #: 0–100；拿不到真进度时为空（不编一个按时间推的数）
    progress: Mapped[int | None] = mapped_column(Integer)
    #: 给人看的当前步骤：「三视图 2/3」「出图中 · 已 40 秒」
    step: Mapped[str | None] = mapped_column(String(200))
    error: Mapped[str | None] = mapped_column(String(500))
    #: 主产物（前端 MediaRef 形状：url 一律同源 /media/…）
    media_json: Mapped[dict | None] = mapped_column(JSONB)
    #: 其余产物 [{label, media}]：count>1 的其余几张、sheet 的各面板（label = 面板 key）
    extra_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
