"""站位 —— 3D 导演台读写的那份数据。

多人镜的首帧走分区身份：人偶管站位，每人的区域管身份。站位默认由表演单
自动推出（source=auto，见 pipelines/blocking.py）；导演在 3D 台上拖过之后
写回这里，标成 source=stage —— 此后重新绑定不会再用自动摆位覆盖它。

存在首帧 FrameSpec.params_json["regional"] 里，不另建表：它本来就是那一帧的
出图输入，和提示词、参考图放在一起，改了什么、什么时候失效都跟着那一帧走。

导演台上的相机运动写在 Shot.camera_json["rig"]：视频请求的 camera 参数与
英文运镜描述、尾帧「镜头怎么变了」都从这里取（cut.apply_rig / frame_compose.camera_change）。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import FrameRole, FrameSpec, Shot

router = APIRouter(prefix="/api/v2", tags=["blocking"])


class FigureIn(BaseModel):
    entity_id: str
    x: float = Field(ge=0, le=1)
    top: float = Field(ge=-0.5, le=1.5)
    bottom: float = Field(ge=0, le=3)
    width: float = Field(gt=0, le=1)


class BlockingIn(BaseModel):
    figures: list[FigureIn]
    #: 导演台的完整场面（演员 3D 站位＋运镜）。原样存，下次打开导演台还原
    stage3d: dict[str, Any] | None = None
    #: 编译好的运镜：move / video_move / description_en / path / lens… 写进 Shot.camera_json["rig"]
    camera: dict[str, Any] | None = None


#: 站位几何的四个量。身份字段（脸、外观、名字）不在其中 —— 那些跟设定走
_GEOMETRY = ("x", "top", "bottom", "width")


def _geometry(figures: list[dict[str, Any]]) -> list[tuple]:
    return [(f.get("entity_id"), *(round(float(f.get(k) or 0), 3) for k in _GEOMETRY))
            for f in figures]


def _cast(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """这场戏里能摆的全部人：绑定时自动摆位的那一份。

    **不能拿当前 figures 认人。** 起幅画面里可以少人（导演把谁摆出了画），
    但他仍在这场戏里；只按 figures 认，摆出画一次就再也摆不回来 ——
    下次保存带上他会被当成「计划外的人」拒掉，全摆出画则整镜报「没有分区计划」。
    """
    return plan.get("auto_figures") or plan.get("figures") or []


def _invalidate_downstream(db: Session, shot: Shot) -> None:
    """首帧或运镜变了，由它派生的东西都是旧的。

    尾帧是在首帧上编辑出来的；视频吃首尾帧和运镜。两者都没有「跟着首帧失效」
    的机制 —— 首帧重出之后，旧尾帧、旧视频照样挂着，合成时就是新首帧接旧视频。
    尾帧打「旧图」标，视频按镜头挂、没有旧标，直接摘掉，videos:generate
    按「还没有视频」会重新挑中它。
    """
    last = db.execute(select(FrameSpec).where(
        FrameSpec.shot_id == shot.id, FrameSpec.role == FrameRole.last,
    )).scalars().first()
    if last is not None and last.asset_id:
        last.params_json = {**(last.params_json or {}), "needs_regeneration": True}
    shot.video_asset_id = None


def _first_frame(db: Session, shot_id: str) -> FrameSpec:
    if db.get(Shot, shot_id) is None:
        raise HTTPException(status_code=404, detail="shot not found")
    frame = db.execute(select(FrameSpec).where(
        FrameSpec.shot_id == shot_id, FrameSpec.role == FrameRole.first,
    )).scalars().first()
    if frame is None:
        raise HTTPException(status_code=404, detail="这一镜还没有首帧规格")
    return frame


@router.get("/shots/{shot_id}/blocking")
def get_blocking(shot_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """这一镜的站位。没有分区计划（单人、特写、缺空景或缺参考脸）时 figures 为空。"""
    frame = _first_frame(db, shot_id)
    params = frame.params_json or {}
    plan = params.get("regional") or {}
    shot = db.get(Shot, shot_id)
    regional = bool(_cast(plan))
    if regional:
        cast = _cast(plan)
    else:
        from app.pipelines.frame_compose import stage_cast
        cast = stage_cast(db, shot)
    return {
        "shot_id": shot_id,
        # 这一镜的首帧是否按站位出（分区身份）。不是的话导演台只定运镜
        "regional": regional,
        "source": plan.get("source"),
        "plate_url": plan.get("plate_url"),
        "preview_url": params.get("regional_preview_url"),
        "figures": plan.get("figures") or [],
        # 全部可摆的人（含被摆出画的），导演台按它还原演员
        "cast": cast,
        "stage3d": params.get("stage3d"),
        "camera": (shot.camera_json or {}).get("rig"),
    }


@router.put("/shots/{shot_id}/blocking")
def put_blocking(shot_id: str, body: BlockingIn,
                 db: Session = Depends(get_db)) -> dict[str, Any]:
    """导演手摆的站位。只能挪人，不能加人。

    **不能加计划外的人。** 每个人的区域要带他自己的脸和外观描述，这些是
    绑定时从设定里取的；这里凭空加一个人，他的区域里就只有一个人偶和
    空描述 —— 模型会在那里随便画一个陌生人。要加人先去改表演单再重新绑定。
    """
    frame = _first_frame(db, shot_id)
    shot = db.get(Shot, shot_id)
    params = dict(frame.params_json or {})
    plan = dict(params.get("regional") or {})
    cast = _cast(plan)
    known = {f["entity_id"]: f for f in cast}
    figures: list[dict[str, Any]] = []
    moved = False
    if not known:
        # 没有分区计划（单人、特写、缺空景或缺参考脸）：首帧不按站位出，
        # 导演台在这一镜只定运镜。连运镜都没带，就是没什么可存的
        if body.camera is None:
            raise HTTPException(status_code=409, detail={
                "code": "NO_REGIONAL_PLAN",
                "message": "这一镜没有分区计划（单人、特写、缺空景或缺参考脸），没有可摆的人偶",
            })
    else:
        # 起幅画面里可以少人（导演把谁摆出了画），不能多出计划外的人
        unknown = [f.entity_id for f in body.figures if f.entity_id not in known]
        if unknown:
            raise HTTPException(status_code=422, detail={
                "code": "UNKNOWN_FIGURE",
                "message": "不能加计划外的人：先改表演单再重新绑定",
                "entity_ids": unknown,
            })
        for f in body.figures:
            base = known[f.entity_id]
            if f.bottom <= f.top:
                raise HTTPException(status_code=422, detail=f"{base.get('name')}：脚底要在头顶下面")
            figures.append({**base, "x": f.x, "top": f.top, "bottom": f.bottom, "width": f.width})
        moved = _geometry(figures) != _geometry(plan.get("figures") or [])
        plan["auto_figures"] = cast
        plan["figures"] = figures
        plan["source"] = "stage"
        params["regional"] = plan
    if body.stage3d is not None:
        params["stage3d"] = body.stage3d
    rig_changed = False
    if body.camera is not None:
        cam = dict(shot.camera_json or {})
        rig_changed = cam.get("rig") != body.camera
        cam["rig"] = body.camera
        shot.camera_json = cam
    # 只在真变了的时候作废：导演打开导演台、什么都没动、点了保存，
    # 不该把出好的首帧、尾帧、视频全打成旧的
    if moved and frame.asset_id:
        params["needs_regeneration"] = True
    if moved or rig_changed:
        _invalidate_downstream(db, shot)
    frame.params_json = params
    # **先提交再回应。** get_db 的 commit 在响应发出之后才跑（FastAPI 0.133 的
    # yield 依赖默认挂在请求级退出栈上）。导演台「保存并重出首帧」是保存一返回
    # 就发出图请求 —— 出图那边读到的还是旧站位，落库时整段 params_json
    # 覆盖回去，导演刚摆的站位就悄悄没了。端到端实测撞上过一次：
    # 保存返回「运镜已变」，紧接着读库，运镜不在、旧视频也还挂着
    db.commit()
    return {"shot_id": shot_id, "regional": bool(known),
            "source": "stage" if known else None, "figures": figures, "cast": cast,
            "plate_url": plan.get("plate_url"), "preview_url": params.get("regional_preview_url"),
            "stage3d": params.get("stage3d"), "camera": (shot.camera_json or {}).get("rig"),
            "moved": moved, "rig_changed": rig_changed,
            "needs_regeneration": bool(params.get("needs_regeneration"))}


@router.delete("/shots/{shot_id}/blocking")
def reset_blocking(shot_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """放弃导演台：站位回到自动摆位，运镜摘掉。

    自动摆位是第一次手摆前存下的那份（auto_figures），这里直接换回去，
    不用等下次绑定 —— 否则「恢复自动」之后看到的还是手摆的站位，
    只是标签变成了 auto。
    """
    frame = _first_frame(db, shot_id)
    shot = db.get(Shot, shot_id)
    params = dict(frame.params_json or {})
    plan = dict(params.get("regional") or {})
    moved = False
    if plan:
        auto = plan.pop("auto_figures", None)
        if auto is not None:
            moved = _geometry(auto) != _geometry(plan.get("figures") or [])
            plan["figures"] = auto
        plan["source"] = "auto"
        params["regional"] = plan
    params.pop("stage3d", None)
    had_rig = "rig" in (shot.camera_json or {})
    if had_rig:
        cam = dict(shot.camera_json or {})
        cam.pop("rig", None)
        shot.camera_json = cam
    if moved and frame.asset_id:
        params["needs_regeneration"] = True
    if moved or had_rig:
        _invalidate_downstream(db, shot)
    frame.params_json = params
    db.commit()   # 同 put_blocking：回应之前落库
    return {"shot_id": shot_id, "source": "auto", "figures": plan.get("figures") or [],
            "moved": moved}
