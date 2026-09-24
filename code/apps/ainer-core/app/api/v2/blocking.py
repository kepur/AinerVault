"""站位 —— 3D 导演台读写的那份数据。

多人镜的首帧走分区身份：人偶管站位，每人的区域管身份。站位默认由表演单
自动推出（source=auto，见 pipelines/blocking.py）；导演在 3D 台上拖过之后
写回这里，标成 source=stage —— 此后重新绑定不会再用自动摆位覆盖它。

存在首帧 FrameSpec.params_json["regional"] 里，不另建表：它本来就是那一帧的
出图输入，和提示词、参考图放在一起，改了什么、什么时候失效都跟着那一帧走。
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
    return {
        "shot_id": shot_id,
        "source": plan.get("source"),
        "plate_url": plan.get("plate_url"),
        "preview_url": params.get("regional_preview_url"),
        "figures": plan.get("figures") or [],
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
    params = dict(frame.params_json or {})
    plan = dict(params.get("regional") or {})
    known = {f["entity_id"]: f for f in plan.get("figures") or []}
    if not known:
        raise HTTPException(status_code=409, detail={
            "code": "NO_REGIONAL_PLAN",
            "message": "这一镜没有分区计划（单人、特写、缺空景或缺参考脸），没有可摆的人偶",
        })
    unknown = [f.entity_id for f in body.figures if f.entity_id not in known]
    if unknown:
        raise HTTPException(status_code=422, detail={
            "code": "UNKNOWN_FIGURE",
            "message": "不能加计划外的人：先改表演单再重新绑定",
            "entity_ids": unknown,
        })
    figures = []
    for f in body.figures:
        base = known[f.entity_id]
        if f.bottom <= f.top:
            raise HTTPException(status_code=422, detail=f"{base.get('name')}：脚底要在头顶下面")
        figures.append({**base, "x": f.x, "top": f.top, "bottom": f.bottom, "width": f.width})
    plan["figures"] = figures
    plan["source"] = "stage"
    params["regional"] = plan
    # 站位变了，已出的首帧就是旧的：让「旧图」闸门拦下它，重新出
    if frame.asset_id:
        params["needs_regeneration"] = True
    frame.params_json = params
    db.flush()
    return {"shot_id": shot_id, "source": "stage", "figures": figures,
            "needs_regeneration": bool(params.get("needs_regeneration"))}


@router.delete("/shots/{shot_id}/blocking")
def reset_blocking(shot_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """放弃手摆，下次绑定时回到按表演单自动摆位。"""
    frame = _first_frame(db, shot_id)
    params = dict(frame.params_json or {})
    plan = dict(params.get("regional") or {})
    if plan:
        plan["source"] = "auto"
        params["regional"] = plan
        frame.params_json = params
        db.flush()
    return {"shot_id": shot_id, "source": "auto"}
