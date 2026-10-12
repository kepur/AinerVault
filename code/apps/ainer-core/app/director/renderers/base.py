"""渲染器适配层的统一接口。

Director Core 只和这一层说话：给 RenderRequest（提示词、控制视频、首帧、参考图、种子、分辨率），
拿回 RenderResult（成片地址）。LTX 0.9.7 → 2.5、以后换 Wan / Hunyuan，都只是多一个适配器。
适配器之下走能力网关（capability），core 不直接碰 ComfyUI、不碰模型文件。
"""
from __future__ import annotations

import time
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.capability.schemas import Capability
from app.capability.service import cancel_task, poll_task, submit_task
from app.director import config
from app.models import GenTask, TaskStatus

TERMINAL = {TaskStatus.succeeded, TaskStatus.failed, TaskStatus.cancelled}

ControlType = Literal["v2v", "depth", "pose", "canny", "union", "layout"]


class RenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    renderer: Literal["ltx_097", "ltx_25"] = "ltx_097"
    prompt: str
    negative_prompt: str = ""
    control_type: ControlType = "v2v"
    #: 控制视频（v2v 用预演/白模；depth/pose/canny 用对应通道）
    control_video: str
    #: 其它通道（LTX 2.5 union control 同时吃多种）
    control_videos: dict[str, str] = Field(default_factory=dict)
    #: 首帧：预演第一帧（要先画成成片风格）或已经画好的首帧
    first_frame: str | None = None
    first_frame_styled: bool = False
    #: 把首帧钉死（锁角色身份时用；不钉则外观交给提示词，整段更连贯）
    pin_first: bool = False
    reference_images: list[str] = Field(default_factory=list)
    seed: int | None = None
    fps: int = 24
    resolution: tuple[int, int] = (768, 448)
    duration_sec: float = Field(6.0, gt=0, le=20)
    denoise: float | None = Field(None, ge=0.3, le=1.0)
    strength: float | None = Field(None, ge=0, le=2)
    style: str | None = None                 # 工作台画风：photoreal / anime / cinematic / auto
    #: 声音：generate = 模型现场生成（脚步、击打、环境声）；none = 只出画面；
    #: drive = 用 audio_track（这一镜按角色音色配好的台词轨）驱动口型和表演，角色音色前后一致（LTX 2.5 a2v）
    audio_mode: Literal["generate", "none", "drive"] = "generate"
    audio_track: str | None = None


class RenderResult(BaseModel):
    renderer: str
    video_url: str | None = None
    first_frame_url: str | None = None
    last_frame_url: str | None = None
    task_ids: list[str] = Field(default_factory=list)
    mock: bool = False
    meta: dict[str, Any] = Field(default_factory=dict)


class RendererError(RuntimeError):
    pass


class BaseRendererAdapter:
    name = "base"
    flag = ""
    config_name = ""
    capability = Capability.video_i2v

    def cfg(self) -> dict[str, Any]:
        return config.load(self.config_name) if self.config_name else {}

    def enabled(self) -> bool:
        return config.enabled(self.flag)

    def validate(self, req: RenderRequest) -> RenderRequest:
        w, h = req.resolution
        return req.model_copy(update={"resolution": (max(256, w // 32 * 32), max(256, h // 32 * 32))})

    def build_payload(self, req: RenderRequest) -> dict[str, Any]:
        raise NotImplementedError

    def generate(self, db: Session, req: RenderRequest, *, on_progress: Callable[[dict[str, Any]], None] | None = None,
                 cancelled: Callable[[], bool] | None = None) -> RenderResult:
        raise NotImplementedError

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "enabled": self.enabled(), "flag": self.flag}


def run_task(db: Session, cap: Capability, payload: dict[str, Any], *, purpose: str, timeout_s: float = 3600,
             on_progress: Callable[[dict[str, Any]], None] | None = None,
             cancelled: Callable[[], bool] | None = None, label: str = "") -> GenTask:
    """提交一个能力任务并轮询到结束（本机队列里一个一个跑，轮询只是等）。"""
    task = submit_task(db, cap, payload, purpose=purpose, force=True, ref_kind="director_job")
    db.commit()
    t0 = time.time()
    while task.status not in TERMINAL:
        if cancelled and cancelled():
            cancel_task(db, task)          # 网关上的任务一起停，不然 GPU 一直被占着
            db.commit()
            raise RendererError("任务被取消")
        if time.time() - t0 > timeout_s:
            raise RendererError(f"{label or cap.value} 超过 {int(timeout_s)} 秒没完成")
        time.sleep(4)
        task = poll_task(db, db.get(GenTask, task.id))
        db.commit()
        if on_progress:
            on_progress({"kind": "task", "label": label, "status": task.status.value, "elapsed": int(time.time() - t0)})
    if task.status != TaskStatus.succeeded:
        err = task.error_json or {}
        raise RendererError(f"{label or cap.value} 失败：{err.get('message') or task.status.value}")
    return task
