"""LTX 2.5 成片适配器（V1 关闭：feature_flags.ltx25_enabled=false）。

已经做好：参数校验、新版控制 payload（union control：深度＋骨架＋边缘同时喂、各自强度；
motion track 运动轨迹；首帧；参考图；音轨开关）、mock 返回。没做：真推理 —— 开关打开且
网关有了 LTX-2.5 工作流（22B 底模＋IC-LoRA Union-Control）之后，generate 走的就是这份 payload。

切换时上层不用动：同一个 RenderRequest，renderer 从 ltx_097 换成 ltx_25。
"""
from __future__ import annotations

from typing import Any, Callable

from sqlalchemy.orm import Session

from app.director import config
from app.director.renderers.base import BaseRendererAdapter, RenderRequest, RenderResult, RendererError, run_task

UNION_TYPES = ("depth", "pose", "canny")


class LTX25Adapter(BaseRendererAdapter):
    name = "ltx_25"
    flag = "ltx25_enabled"
    config_name = "ltx25"

    def validate(self, req: RenderRequest) -> RenderRequest:
        req = super().validate(req)
        cfg = self.cfg()
        if req.control_type == "union":
            vids = {k: v for k, v in req.control_videos.items() if k in UNION_TYPES and v}
            if not vids:
                raise RendererError("union control 至少要给 depth / pose / canny 里的一路控制视频（control_videos）")
            allowed = set((cfg.get("union_control") or {}).get("types") or UNION_TYPES)
            bad = set(vids) - allowed
            if bad:
                raise RendererError(f"union control 不支持：{', '.join(sorted(bad))}")
        elif not req.control_video:
            raise RendererError("缺控制视频")
        if req.duration_sec > 20:
            raise RendererError("LTX 2.5 单段最长 20 秒")
        return req

    def build_payload(self, req: RenderRequest) -> dict[str, Any]:
        cfg = self.cfg()
        uc = cfg.get("union_control") or {}
        if req.control_type == "union":
            ctl: dict[str, Any] = {
                "type": "union",
                "videos": {k: {"url": v} for k, v in req.control_videos.items() if k in UNION_TYPES and v},
                "strengths": {k: float((uc.get("strengths") or {}).get(k, 1.0)) for k in req.control_videos if k in UNION_TYPES},
            }
        else:
            ctl = {"type": req.control_type, "video": {"url": req.control_video},
                   "strength": req.strength if req.strength is not None else 1.0}
        mt = cfg.get("motion_track") or {}
        if mt.get("enabled"):
            ctl["motion_track"] = True
        w, h = req.resolution
        payload: dict[str, Any] = {
            "model_family": "ltx-2.5", "prompt": req.prompt, "negative_prompt": req.negative_prompt or None,
            "duration_ms": int(round(req.duration_sec * 1000)), "fps": req.fps or int(cfg.get("fps", 24)),
            "width": w, "height": h, "control": ctl, "audio": bool(cfg.get("audio", False)),
            "params": {"seed": req.seed},
        }
        if req.first_frame:
            payload["first_frame"] = {"url": req.first_frame}
            payload["control"]["pin_first"] = req.pin_first
        if req.reference_images:
            payload["reference_images"] = [{"url": u, "role": "identity", "identity": True} for u in req.reference_images[:4]]
        return {k: v for k, v in payload.items() if v is not None}

    def mock_generate(self, req: RenderRequest) -> RenderResult:
        """不跑推理：返回一个假的结果（测试、联调前端用）。"""
        req = self.validate(req)
        return RenderResult(renderer=self.name, video_url=None, mock=True,
                            meta={"payload": self.build_payload(req), "note": "LTX 2.5 未启用：这是 mock"})

    def generate(self, db: Session, req: RenderRequest, *, on_progress: Callable[[dict[str, Any]], None] | None = None,
                 cancelled: Callable[[], bool] | None = None, **_: Any) -> RenderResult:
        config.require(self.flag, "LTX 2.5 成片")
        req = self.validate(req)
        t = run_task(db, self.capability, self.build_payload(req), purpose=self.cfg().get("route_purpose") or "director_final_ltx25",
                     timeout_s=5400, label="LTX 2.5 视频", on_progress=on_progress, cancelled=cancelled)
        out = t.result_json or {}
        return RenderResult(renderer=self.name, video_url=(out.get("video") or {}).get("url"), task_ids=[t.id],
                            meta={"control_type": req.control_type})
