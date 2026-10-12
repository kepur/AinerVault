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
        if req.audio_mode == "drive":
            # a2v：台词轨驱动口型。网关的 a2v 管线不吃 IC-LoRA，白模的站位和机位靠首帧（身份首帧就是按预演画的）带进来
            if not req.audio_track:
                raise RendererError("配音驱动（audio_mode=drive）要给台词轨 audio_track")
            if not req.first_frame:
                raise RendererError("配音驱动没有白模控制，必须钉一张首帧（身份首帧）")
            if req.duration_sec > 20:
                raise RendererError("LTX 2.5 单段最长 20 秒")
            return req
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
        if req.control_type == "layout" and not (req.first_frame and req.first_frame_styled):
            # Layout-To-Render：白模视频定机位/走位，首帧定画风与人物 —— 没有成片风格首帧就只会出灰模
            raise RendererError("layout 控制需要已画成成片风格的首帧（first_frame_styled）")
        if req.duration_sec > 20:
            raise RendererError("LTX 2.5 单段最长 20 秒")
        return req

    def build_payload(self, req: RenderRequest) -> dict[str, Any]:
        cfg = self.cfg()
        if req.audio_mode == "drive":
            w, h = req.resolution
            payload = {
                "prompt": req.prompt, "duration_ms": int(round(req.duration_sec * 1000)),
                "fps": req.fps or int(cfg.get("fps", 24)), "width": w, "height": h, "style": req.style or None,
                "first_frame": {"url": req.first_frame},
                "audio": {"mode": "drive", "track": {"url": req.audio_track}},
                "quality": "final",                # a2v 没有分阶段续跑
                "params": {"seed": req.seed},
            }
            return {k: v for k, v in payload.items() if v is not None}
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
        if uc.get("conditioning_strength") is not None:
            ctl["conditioning_strength"] = float(uc["conditioning_strength"])
        if uc.get("fidelity"):
            ctl["fidelity"] = str(uc["fidelity"])
        w, h = req.resolution
        payload: dict[str, Any] = {
            "prompt": req.prompt, "negative_prompt": req.negative_prompt or None,
            "duration_ms": int(round(req.duration_sec * 1000)), "fps": req.fps or int(cfg.get("fps", 24)),
            "width": w, "height": h, "control": ctl, "style": req.style or None,
            # LTX-2.5 自带同步音轨（脚步、击打、环境声）；关掉就只出画面
            "audio": {"mode": "generate" if cfg.get("audio", True) and req.audio_mode != "none" else "none"},
            "params": {"seed": req.seed},
        }
        # **Blender 的首帧是灰的，默认不当锚点。** 2B 上实测过：钉灰首帧整段发灰。
        # 只有已经画成成片风格的首帧、且明确要钉（锁角色身份）时才给
        if req.first_frame and req.first_frame_styled and (req.pin_first or req.control_type == "layout"):
            payload["first_frame"] = {"url": req.first_frame}
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
                            meta={"control_type": "a2v" if req.audio_mode == "drive" else req.control_type,
                                  "audio_mode": req.audio_mode})
