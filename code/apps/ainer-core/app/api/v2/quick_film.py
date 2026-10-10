"""快速成片（纳逗式一条龙）的接口：给旅拍、相册、短视频等外部系统，不需要小说和分镜表。

    POST /api/v2/studio/quick-films         {"idea", "person": {url|asset_id}, "outfit"?, "scene"?, "shots": 2-4,
                                             "mode": "one_take"|"cuts", "candidates": 1-3}
    GET  /api/v2/studio/quick-films/{id}    进度：step（plan / look / outfit / scene / frame:N / video / concat / done）
                                            和 outputs（定妆照、换装定妆照、场景图、分镜 N、镜头 N、成片，按出来的顺序）
图片先用 POST /api/v2/studio/uploads 传上来拿 asset_id，或者直接给本库 /media 地址。全部本机出，不花钱。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.pipelines import quick_film

router = APIRouter(prefix="/api/v2/studio", tags=["studio-quick-film"])


class MediaIn(BaseModel):
    url: str | None = None
    asset_id: str | None = None


class QuickFilmIn(BaseModel):
    #: 一句话想法（中英文都行）：「她第一次滑雪，从坡顶冲下来，摔了一跤又笑着爬起来」
    idea: str = Field(..., min_length=2, max_length=2000)
    #: 人物照片（一张就够：正脸、光线清楚）
    person: MediaIn
    #: 服装照片（可选）：有就先出换装定妆照
    outfit: MediaIn | None = None
    #: 场景图（可选）：没有就按想法生成一张空镜
    scene: MediaIn | None = None
    shots: int = Field(3, ge=2, le=4)
    #: cuts = 逐镜物理接续与剪辑（默认，首尾帧自然连续，保证物理世界动量守恒与影视效果）；one_take = 几镜叠在一次生成
    mode: str = Field("cuts", pattern="^(cuts|one_take)$")
    #: 每镜分镜图出几张候选，>1 时本机视觉模型对着定妆照挑
    candidates: int = Field(2, ge=1, le=3)


def _url(db: Session, m: MediaIn | None, what: str) -> str | None:
    from app.models import Asset

    if m is None or not (m.url or m.asset_id):
        return None
    if m.asset_id:
        a = db.get(Asset, m.asset_id)
        if a is None:
            raise HTTPException(422, f"{what}：找不到素材 {m.asset_id}")
        return a.url
    url = str(m.url)
    if url.startswith("/media/"):
        from app.config import get_settings

        url = get_settings().public_base_url.rstrip("/") + url
    return url


@router.post("/quick-films", status_code=202)
def create(body: QuickFilmIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    person = _url(db, body.person, "人物照片")
    if not person:
        raise HTTPException(422, "要一张人物照片（url 或 asset_id）")
    return quick_film.start({"idea": body.idea, "person_url": person, "outfit_url": _url(db, body.outfit, "服装照片"),
                             "scene_url": _url(db, body.scene, "场景图"), "shots": body.shots, "mode": body.mode,
                             "candidates": body.candidates})


@router.get("/quick-films/{job_id}")
def status(job_id: str) -> dict[str, Any]:
    job = quick_film.get(job_id)
    if job is None:
        raise HTTPException(404, "没有这个任务（core 重启过？已出的图和视频都在媒体库里）")
    return job


class FilmPlanIn(BaseModel):
    idea: str = Field(..., min_length=2, max_length=2000)
    shots: int = Field(3, ge=2, le=4)
    has_outfit: bool = False
    has_scene: bool = False


@router.post("/film-plans")
def plan_film(body: FilmPlanIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    return quick_film.plan_idea(db, body.idea, body.shots, has_outfit=body.has_outfit, has_scene=body.has_scene)


class ScreenplayExpandIn(BaseModel):
    idea: str = Field(..., min_length=1, max_length=10000)
    genre: str = Field("玄幻修仙逆袭")
    background: list[str] = Field(default_factory=list)
    characters: list[str] = Field(default_factory=list)
    highlights: list[str] = Field(default_factory=list)
    style: str = Field("暗调奇幻 CG")
    episodes: int = Field(35, ge=1, le=120)
    structure: str = Field("五幕式")
    mode: str = Field("domestic")
    target_world: str | None = None


@router.post("/screenplay-expand")
def expand_screenplay_endpoint(body: ScreenplayExpandIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    from app.pipelines import screenplay
    return screenplay.expand_screenplay(db, body.model_dump())

