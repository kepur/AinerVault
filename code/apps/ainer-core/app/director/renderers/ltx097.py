"""LTX 0.9.7 成片适配器（V1 启用）。

两步，都走本机能力网关、一个一个跑：
  1) 首帧（可选）：image.image_to_image 把预演第一帧画成成片风格 —— 只在要锁角色身份时用
     （有角色库参考图），并把它钉成视频的首帧
  2) 视频：video.image_to_video ＋ control{type, video, denoise/strength, pin_first}
       v2v              白模重绘：本机 2B 就能跑（实测 6 秒 145 帧约 100 秒）
       depth/pose/canny IC-LoRA：要 13B 0.9.7 底模；网关报未就绪时这里直接说明，不偷偷降级

实测结论（夜巷打斗，2B）：钉住的首帧决定整段的样子 —— 钉灰白模首帧，整段环境都是灰的；
钉一张构图对不上的成片首帧，第 1→2 帧会跳。所以默认不钉，外观交给提示词（denoise 0.92）。
"""
from __future__ import annotations

from typing import Any, Callable

from sqlalchemy.orm import Session

from app.capability.schemas import Capability
from app.director import config
from app.director.renderers.base import BaseRendererAdapter, RenderRequest, RenderResult, RendererError, run_task

FIRST_FRAME_INSTRUCTION = (
    "Render this grey-box 3D previs frame as a finished film frame. {subject} "
    "Keep the camera angle, framing, horizon and every person's position, pose and size exactly the same. "
    "Do not add or remove people."
)


class LTX097Adapter(BaseRendererAdapter):
    name = "ltx_097"
    flag = "ltx097_enabled"
    config_name = "ltx097"

    def control_types(self, db: Session | None = None) -> list[str]:
        """网关当前能跑的控制方式（网关按本机实际权重动态报）。取不到就只报 v2v。"""
        if db is None:
            return ["v2v"]
        try:
            from app.capability.client import CapabilityClient
            from app.capability.router import resolve_one
            ep = resolve_one(db, Capability.video_i2v, self.cfg().get("route_purpose") or "director_final").endpoint
            with CapabilityClient(ep.base_url, auth=ep.auth_json or {}, dialect=ep.dialect or "capability") as c:
                entry = c.capabilities().get(Capability.video_i2v)
            m = entry.default_model() if entry else None
            ct = (m.model_dump() if m else {}).get("control_types")
            if ct:
                return list(ct)
        except Exception:        # noqa: BLE001 —— 探测失败不挡路，真跑时网关会给准确的错误
            pass
        return ["v2v"]

    def validate(self, req: RenderRequest) -> RenderRequest:
        req = super().validate(req)
        if req.control_type == "union":
            raise RendererError("LTX 0.9.7 没有 union control（多控制合一）；那是 LTX 2.x 的能力")
        if not req.control_video:
            raise RendererError("缺控制视频")
        return req

    def build_payload(self, req: RenderRequest) -> dict[str, Any]:
        cfg = self.cfg()
        ctl: dict[str, Any] = {"type": req.control_type, "video": {"url": req.control_video}, "pin_first": req.pin_first}
        if req.control_type == "v2v":
            ctl["denoise"] = req.denoise if req.denoise is not None else float((cfg.get("v2v") or {}).get("denoise", 0.92))
        else:
            ctl["strength"] = req.strength if req.strength is not None else float(cfg.get("control_strength", 1.0))
        payload: dict[str, Any] = {
            "prompt": req.prompt, "negative_prompt": req.negative_prompt or None,
            "duration_ms": int(round(req.duration_sec * 1000)), "fps": req.fps,
            "width": req.resolution[0], "height": req.resolution[1], "style": req.style or "auto",
            "control": ctl, "params": {"seed": req.seed, "steps": int(cfg.get("steps", 8))},
        }
        if req.first_frame:
            payload["first_frame"] = {"url": req.first_frame}
        return {k: v for k, v in payload.items() if v is not None}

    def style_first_frame(self, db: Session, req: RenderRequest, subject: str, **kw) -> str:
        """把预演首帧画成成片风格（带角色参考图时锁身份）。"""
        payload: dict[str, Any] = {
            "image": {"url": req.first_frame}, "width": req.resolution[0], "height": req.resolution[1],
            "prompt": FIRST_FRAME_INSTRUCTION.format(subject=subject.strip()), "style": req.style or "cinematic",
            "params": {"seed": req.seed},
        }
        if req.reference_images:
            payload["reference_images"] = [{"url": u, "role": "identity", "identity": True} for u in req.reference_images[:3]]
        t = run_task(db, Capability.image_i2i, payload, purpose="director_first_frame", timeout_s=900, label="首帧", **kw)
        imgs = (t.result_json or {}).get("images") or []
        if not imgs or not imgs[0].get("url"):
            raise RendererError("首帧没有产出图片")
        return str(imgs[0]["url"])

    def generate(self, db: Session, req: RenderRequest, *, on_progress: Callable[[dict[str, Any]], None] | None = None,
                 cancelled: Callable[[], bool] | None = None, first_frame_subject: str = "") -> RenderResult:
        config.require(self.flag, "LTX 0.9.7 成片")
        req = self.validate(req)
        ready = self.control_types(db)
        if req.control_type not in ready:
            raise RendererError(f"本机还不能用 {req.control_type} 控制（网关报可用：{', '.join(ready)}）。"
                                f"depth/pose/canny 需要 13B 0.9.7 底模 ltxv-13b-0.9.7-distilled；先用 v2v 白模重绘")
        tasks: list[str] = []
        styled = None
        if req.first_frame and req.pin_first and not req.first_frame_styled:
            if on_progress:
                on_progress({"kind": "stage", "stage": "first_frame"})
            styled = self.style_first_frame(db, req, first_frame_subject or req.prompt, on_progress=on_progress, cancelled=cancelled)
            req = req.model_copy(update={"first_frame": styled, "first_frame_styled": True})
        if on_progress:
            on_progress({"kind": "stage", "stage": "video", "control": req.control_type})
        t = run_task(db, self.capability, self.build_payload(req), purpose=self.cfg().get("route_purpose") or "director_final",
                     timeout_s=3600, label="视频", on_progress=on_progress, cancelled=cancelled)
        tasks.append(t.id)
        out = t.result_json or {}
        video = (out.get("video") or {}).get("url")
        if not video:
            raise RendererError("视频任务成功但没有视频")
        return RenderResult(renderer=self.name, video_url=video, first_frame_url=styled,
                            last_frame_url=(out.get("last_frame") or {}).get("url"), task_ids=tasks,
                            meta={"control_type": req.control_type, "gen_task_id": t.id,
                                  "frames": ((out.get("video") or {}).get("meta") or {}).get("frames")})
