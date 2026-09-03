"""音频与交付：编译 → TTS → 时长回填 → manifest。

本系统不生成视频。交付物是「首尾帧 + 音频 + 指令」，
按下游视频模型是否自带音频投影成两种 manifest。
"""
from __future__ import annotations

import subprocess

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.capability.errors import CapabilityError
from app.db import get_db
from app.models import (
    AudioKind, AudioSpec, ReviewStatus, Scene, Shot, ShotPlan, VoiceCasting,
    WorldEntity, WorldProfile, WorldTransform,
)
from app.pipelines import audio_compose as ac
from app.pipelines import casting, delivery
from app.pipelines.base import PipelineError
from app.worldview.voice import VOCAB, VoiceSpec

router = APIRouter(prefix="/api/v2", tags=["audio"])


def _plan(db: Session, plan_id: str) -> ShotPlan:
    p = db.get(ShotPlan, plan_id)
    if p is None:
        raise HTTPException(status_code=404, detail="shot plan not found")
    return p


class CompileIn(BaseModel):
    transform_id: str
    include_bgm: bool = True
    include_room_tone: bool = True


@router.post("/shot-plans/{plan_id}/audio:compile")
def compile_audio(plan_id: str, body: CompileIn, db: Session = Depends(get_db)) -> dict:
    """把分镜编译成音频规格。对白绑定角色的 voice 素材，不自由挑音色。"""
    plan = _plan(db, plan_id)
    t = db.get(WorldTransform, body.transform_id)
    if t is None:
        raise HTTPException(status_code=404, detail="transform not found")
    try:
        return ac.compile_audio(
            db, plan, t, include_bgm=body.include_bgm,
            include_room_tone=body.include_room_tone,
        ).as_dict()
    except PipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class AudioGenIn(BaseModel):
    kinds: list[str] = Field(default_factory=list)
    regenerate: bool = False
    confirm_cost: bool = False


@router.post("/shot-plans/{plan_id}/audio:generate")
def generate_audio(plan_id: str, body: AudioGenIn,
                   db: Session = Depends(get_db)) -> dict:
    """提交音频生成。对白带上素材的参考音频作 voice reference。"""
    plan = _plan(db, plan_id)
    return ac.generate_audio(
        db, plan, kinds=body.kinds or None,
        regenerate=body.regenerate, confirm_cost=body.confirm_cost,
    ).as_dict()


@router.post("/shot-plans/{plan_id}/audio:backfill-durations")
def backfill_durations(plan_id: str, db: Session = Depends(get_db)) -> dict:
    """把 TTS 真实时长回填到镜头。

    时长权威链的落点。无论下游视频模型带不带音频都要做 ——
    带音频的模型也需要确定的时长约束，否则字幕对不上。
    """
    return ac.backfill_durations(db, _plan(db, plan_id))


@router.get("/shot-plans/{plan_id}/audio")
def list_audio(plan_id: str, kind: str | None = Query(None),
               db: Session = Depends(get_db)) -> dict:
    plan = _plan(db, plan_id)
    shots = list(
        db.execute(
            select(Shot).where(Shot.shot_plan_id == plan.id).order_by(Shot.order_no)
        ).scalars()
    )
    order = {s.id: s.order_no for s in shots}
    scene_ids = [s.scene_id for s in shots if s.scene_id]

    q = select(AudioSpec).where(
        (AudioSpec.shot_id.in_(list(order)))
        | ((AudioSpec.shot_id.is_(None)) & (AudioSpec.scene_id.in_(scene_ids)))
    )
    if kind:
        q = q.where(AudioSpec.kind == AudioKind(kind))
    rows = list(db.execute(q).scalars())

    items = []
    for a in rows:
        params = a.params_json or {}
        items.append({
            "id": a.id, "kind": a.kind.value,
            "shot_order": order.get(a.shot_id),
            "scene_id": a.scene_id,
            "text": (a.text or "")[:120],
            "language": a.language_code,
            "voice_asset_key": params.get("voice_asset_key"),
            "voice_id": params.get("voice_id"),
            "has_voice_reference": bool(params.get("voice_reference_asset_ids")),
            "duration_ms": a.duration_ms,
            "asset_id": a.asset_id, "status": a.status.value,
        })
    items.sort(key=lambda x: (x["shot_order"] is None, x["shot_order"] or 0))
    voiced = sum(1 for i in items if i["asset_id"])
    return {
        "items": items,
        "stats": {
            "total": len(items), "generated": voiced,
            "with_voice_reference": sum(1 for i in items if i["has_voice_reference"]),
            "total_voiced_ms": sum(i["duration_ms"] or 0 for i in items),
        },
    }


# ── 交付 ──────────────────────────────────────────────────────────────────────

@router.get("/delivery/projection")
def get_projection(db: Session = Depends(get_db)) -> dict:
    """探测下游视频模型是否自带音频。

    contract 扩展：video.image_to_video 的模型可声明
      supports: {native_audio, voice_reference, audio_track_input}
    未声明按 silent 处理 —— 保守假设不会出错，多生成的音频总能用上。
    """
    mode, detail = delivery.detect_projection(db)
    return {"projection": mode, "detail": detail}


@router.get("/shot-plans/{plan_id}/manifest")
def get_manifest(
    plan_id: str,
    projection: str = Query("auto", pattern="^(auto|native_audio|silent)$"),
    subtitles: bool = Query(True),
    db: Session = Depends(get_db),
) -> dict:
    """交付清单 —— 本系统的最终产出。

    projection=auto 按 Discovery 自动判断；也可强制指定，
    两种投影的上游产出完全相同，只是清单形态不同。
    """
    return delivery.build_manifest(
        db, _plan(db, plan_id), projection=projection,  # type: ignore[arg-type]
        include_subtitles=subtitles,
    )


# ── 配音 ──────────────────────────────────────────────────────────────────────

class CastIn(BaseModel):
    profile_id: str
    entity_ids: list[str] = Field(default_factory=list)
    force: bool = False


@router.post("/novels/{novel_id}/casting:run")
def run_casting(novel_id: str, body: CastIn,
                db: Session = Depends(get_db)) -> dict:
    """给全书说过话的角色定音色。

    整本一起配 —— 可辨识是角色之间的关系，一次配一个没法保证。
    """
    profile = db.get(WorldProfile, body.profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="world profile not found")
    try:
        return casting.cast_voices(
            db, novel_id, profile,
            entity_ids=body.entity_ids or None, force=body.force,
        ).as_dict()
    except PipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/novels/{novel_id}/casting:derive-epochs")
def derive_epoch_voices(novel_id: str, profile_id: str = Query(...),
                        db: Session = Depends(get_db)) -> dict:
    """按素材时期推出各期音色。不调模型 —— 年龄对嗓子的影响是规律的。"""
    profile = db.get(WorldProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="world profile not found")
    try:
        return casting.cast_epoch_voices(db, novel_id, profile)
    except PipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class BindVoicesIn(BaseModel):
    profile_id: str
    endpoint_id: str | None = None
    overwrite: bool = False


@router.post("/novels/{novel_id}/casting:bind-engine-voices")
def bind_engine_voices(novel_id: str, body: BindVoicesIn,
                       db: Session = Depends(get_db)) -> dict:
    """把配音表落到某家 TTS 引擎的具体音色上。

    权威依然是配音表里的声学描述 —— 这一步只是「在这家引擎上用哪把嗓子」，
    换引擎重跑一次即可，不需要重配全书。
    """
    from app.capability.client import CapabilityClient
    from app.capability.service import resolve_one
    from app.capability.schemas import Capability
    from app.models import CapabilityEndpoint

    if body.endpoint_id:
        ep = db.get(CapabilityEndpoint, body.endpoint_id)
        if ep is None:
            raise HTTPException(status_code=404, detail="endpoint not found")
    else:
        ep = resolve_one(db, Capability.audio_tts, "dialogue").endpoint
    with CapabilityClient(ep.base_url, auth=ep.auth_json or {},
                          dialect=ep.dialect or "capability") as c:
        try:
            voices = c.voices()
        except CapabilityError as exc:
            raise HTTPException(status_code=502,
                                detail=f"取音色清单失败：{exc}") from exc
    if not voices:
        raise HTTPException(
            status_code=422,
            detail=f"端点 {ep.name} 没有可用音色清单，无法落地")
    return casting.bind_engine_voices(
        db, novel_id=novel_id, profile_id=body.profile_id,
        engine=ep.dialect or ep.name, voices=voices, overwrite=body.overwrite)


@router.get("/novels/{novel_id}/casting")
def get_casting(novel_id: str, profile_id: str = Query(...),
                db: Session = Depends(get_db)) -> dict:
    """配音表 + 体检。撞声、声线漂移、缺项、没配到的说话人。"""
    profile = db.get(WorldProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="world profile not found")

    rows = list(db.execute(
        select(VoiceCasting)
        .where(VoiceCasting.world_profile_id == profile_id)
        .order_by(VoiceCasting.cast_key, VoiceCasting.epoch_key)
    ).scalars())
    ents = {
        e.id: e for e in db.execute(
            select(WorldEntity).where(WorldEntity.novel_id == novel_id)
        ).scalars()
    }
    lines, _co, _basis = casting.speaking_roles(db, novel_id)

    items = []
    for r in rows:
        spec = VoiceSpec.from_json(r.timbre_json)
        ent = ents.get(r.cast_key)
        items.append({
            "id": r.id, "cast_key": r.cast_key, "epoch_key": r.epoch_key,
            "name": "旁白" if r.cast_key == casting.NARRATOR else (
                ent.display_name if ent else r.cast_key),
            "lines": lines.get(r.cast_key, 0),
            "timbre": spec.as_dict(),
            "describe": spec.describe(),
            "speech_habits": r.speech_habits,
            "rationale": r.rationale,
            "voice_ref": r.voice_ref, "voice_engine": r.voice_engine,
            "tts_params": casting.casting_params(r),
            "status": r.status.value, "locked": r.locked,
            "edited_by_human": r.edited_by_human,
            "model": r.model,
        })
    items.sort(key=lambda i: (-i["lines"], i["cast_key"], i["epoch_key"]))
    return {
        "profile": {"id": profile.id, "display_name": profile.display_name},
        "items": items,
        "audit": casting.audit_casting(db, novel_id, profile),
        "vocab": {k: list(v) for k, v in VOCAB.items()},
    }


class CastPatch(BaseModel):
    timbre: dict | None = None
    speech_habits: str | None = None
    voice_ref: str | None = None
    voice_engine: str | None = None
    status: str | None = None
    locked: bool | None = None


@router.patch("/voice-castings/{casting_id}")
def patch_casting(casting_id: str, body: CastPatch,
                  db: Session = Depends(get_db)) -> dict:
    """人工改音色。改过的标记 edited_by_human，重跑配音不覆盖。"""
    row = db.get(VoiceCasting, casting_id)
    if row is None:
        raise HTTPException(status_code=404, detail="voice casting not found")
    if body.timbre is not None:
        spec = VoiceSpec.from_json({**(row.timbre_json or {}), **body.timbre})
        bad = spec.off_vocab()
        if bad:
            # 术语表是白名单。放行一个越界取值，撞声检测就再也比不了它
            raise HTTPException(status_code=422,
                                detail=f"取值不在术语表里：{'、'.join(bad)}")
        row.timbre_json = spec.as_dict()
        row.edited_by_human = True
    for f in ("speech_habits", "voice_ref", "voice_engine"):
        v = getattr(body, f)
        if v is not None:
            setattr(row, f, v)
            row.edited_by_human = True
    if body.status:
        try:
            row.status = ReviewStatus(body.status)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="unknown status") from exc
    if body.locked is not None:
        row.locked = body.locked
    db.flush()
    return {"ok": True, "id": row.id, "edited_by_human": row.edited_by_human}


@router.post("/shot-plans/{plan_id}/soundscape:compile")
def compile_soundscape(plan_id: str, transform_id: str = Query(...),
                       db: Session = Depends(get_db)) -> dict:
    """把声音制作单编译成环境音／配乐／音效的生成规格。

    这一步修的是一处「存了没人读」：声音那一份制作单里每一镜都写清了
    环境底噪、音效点、画外声、配乐，而音频编译走的是另一条路 ——
    它去找音频素材，找不到就静默跳过。于是全库跑下来
    AudioSpec 里只有对白和旁白。
    """
    from app.pipelines import soundscape

    plan = _plan(db, plan_id)
    t = db.get(WorldTransform, transform_id)
    if t is None:
        raise HTTPException(status_code=404, detail="transform not found")
    try:
        return soundscape.compile_soundscape(db, plan, t).as_dict()
    except PipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ── 剪辑台 ────────────────────────────────────────────────────────────────────

class RenderIn(BaseModel):
    voiceover: bool = False
    width: int = 1280
    height: int = 720
    fps: int = 24


@router.get("/shot-plans/{plan_id}/timeline")
def get_timeline(plan_id: str, voiceover: bool = Query(False),
                 db: Session = Depends(get_db)) -> dict:
    """可播放的时间线。轨道排开、按时间码对齐。"""
    from app.pipelines import cut

    return cut.build_timeline(db, _plan(db, plan_id), voiceover=voiceover)


@router.post("/shot-plans/{plan_id}/render")
def render_cut(plan_id: str, body: RenderIn, db: Session = Depends(get_db)) -> dict:
    """把时间线渲成一支 mp4。"""
    from app.pipelines import cut

    if not cut.ffmpeg_available():
        raise HTTPException(
            status_code=422,
            detail="这台机器上没有 ffmpeg。剪辑台仍可在浏览器里预览播放，"
                   "导出成片需要先装 ffmpeg。")
    try:
        return cut.render(db, _plan(db, plan_id), voiceover=body.voiceover,
                          width=body.width, height=body.height, fps=body.fps)
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
