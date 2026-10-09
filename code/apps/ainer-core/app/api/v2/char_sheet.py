"""标准定妆照的接口：给角色库、旅拍 / 相册等外部系统直接出一张「角色定妆照」拼版（画布不走这里，走执行器 op=sheet）。

    POST /api/v2/studio/char-sheets        {"person": {url|asset_id}, "name"?, "look"?, "preset"?: "standard"|"quick", "seed"?}
                                           → 202 {id, state, progress, step}
    GET  /api/v2/studio/char-sheets/{id}   → {id, state: running|done|failed, progress, step, error, sheet, panels, missing}

人物照片先用 POST /api/v2/studio/uploads 传上来拿 asset_id，或者直接给本库 /media 地址。
全部本机 FLUX 编辑出（不花钱），标准版 16 格约 8–10 分钟，快速版 4 格约 2–3 分钟。
状态只放内存：core 重启后查不到，用同样的参数再交一次，已出好的格命中幂等直接复用。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.pipelines import char_sheet

router = APIRouter(prefix="/api/v2/studio", tags=["studio-char-sheet"])


class MediaIn(BaseModel):
    url: str | None = None
    asset_id: str | None = None


class CanonicalBinding(BaseModel):
    entity_id: str = Field(min_length=1, max_length=32)
    epoch_id: str = Field(min_length=1, max_length=32)
    base_revision: str = Field(min_length=1, max_length=80)


class CharSheetIn(BaseModel):
    #: 人物照片（一张就够：正脸、光线清楚）
    person: MediaIn
    binding: CanonicalBinding | None = None
    #: 写在拼版标题上（「角色定妆照 · 名字」），不进提示词
    name: str = Field("", max_length=40)
    #: 服装与发型（英文最好），写进前视图的提示词；不给就沿用照片里的穿着
    look: str = Field("", max_length=400)
    preset: str = Field("standard", pattern="^(standard|quick)$")
    #: 种子基数：不给用固定值（同样输入出同样的图）；想换一版就换一个数
    seed: int | None = Field(None, ge=0, le=2**31 - 1)


def _person_url(db: Session, m: MediaIn) -> str:
    from app.models import Asset

    if m.asset_id:
        a = db.get(Asset, m.asset_id)
        if a is None:
            raise HTTPException(422, f"人物照片：找不到素材 {m.asset_id}")
        url = a.url
    elif m.url:
        url = m.url
    else:
        raise HTTPException(422, "要一张人物照片（url 或 asset_id）")
    # 交给后台线程之前先认一遍地址：外部地址、库里没有的文件当场 422，别等线程跑起来才失败
    try:
        return char_sheet.resolve_person(url)
    except char_sheet.SheetError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/char-sheets", status_code=202)
def create(body: CharSheetIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    person = _person_url(db, body.person)
    if body.binding:
        from app.production import service as production
        from app.models import Asset, AssetEpoch, EntityKind, WorldEntity
        try:
            ent = production.get(db, WorldEntity, body.binding.entity_id)
            if ent.kind != EntityKind.character:
                raise production.ProductionError("kind_not_supported", "16 格标准包目前适用于角色")
            if body.person.asset_id:
                production.get(db, Asset, body.person.asset_id, ent.workspace_id)
            epoch = production.choose_epoch(db, ent,
                production.get(db, AssetEpoch, body.binding.epoch_id, ent.workspace_id).world_profile_id,
                body.binding.epoch_id)
            if epoch.locked:
                raise production.ProductionError("pack_locked", "当前造型已锁定，请先解除锁定", 409)
            if body.binding.base_revision != production.pack_data(db, ent, epoch)["revision"]:
                raise production.ProductionError("revision_conflict", "标准包已变化，请刷新后生成", 409)
        except production.ProductionError as exc:
            raise HTTPException(exc.status, {"code": exc.code, "message": str(exc)}) from exc
    st = char_sheet.start({"person_url": person, "name": body.name.strip(), "look": body.look.strip(),
                           "preset": body.preset, "seed": body.seed,
                           "canonical_binding": body.binding.model_dump() if body.binding else None})
    return {k: st.get(k) for k in ("id", "state", "progress", "step")}


@router.get("/char-sheets/{job_id}")
def status(job_id: str) -> dict[str, Any]:
    st = char_sheet.job(job_id)
    if st is None:
        raise HTTPException(404, "没有这个任务（core 重启过？同样的参数再交一次，已出的格会直接复用）")
    return {k: st.get(k) for k in ("id", "state", "progress", "step", "error", "sheet", "panels", "missing", "preset")}
