"""交付投影 —— 一份产出，两种消费方式。

本系统不生成视频。它把一章编译成「首尾帧 + 音频 + 指令」，
交给下游的视频能力去合成。而下游有两类：

  投影 A · native_audio   视频模型自己生成音频（Veo 3 这类）
      交付 首尾帧 + 运镜 + audio_directive（文本 / 音色参考 / 时长约束）
      已生成的对白音频仍然有用：作 voice reference 与时长基准

  投影 B · silent          视频模型只出画面
      交付 首尾帧 + 运镜 + audio_tracks（已生成的音频文件 + 时间码）
      音画合成交给外部 NLE 或 ffmpeg

**两种投影的上游产出完全相同**。不要为它们建两条工作流 ——
差别只在 manifest 的形态，而形态由 Discovery 里模型声明的能力决定。

无论哪种投影，时长权威都是 TTS 的真实时长。带音频的模型也需要一个确定的
时长约束，否则字幕对不上、镜头长度失控。
"""
from __future__ import annotations

import logging
from typing import Any, Literal, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.capability.schemas import Capability, CapabilityCatalog
from app.models import (
    Asset, AudioKind, AudioSpec, CapabilityEndpoint, Chapter, FrameRole, FrameSpec,
    Scene, Shot, ShotPlan, ScriptDoc, WorldEntity,
)

log = logging.getLogger(__name__)

Projection = Literal["native_audio", "silent", "auto"]


def detect_projection(db: Session) -> tuple[Projection, dict[str, Any]]:
    """按 Discovery 判断下游视频模型是否自带音频。

    契约扩展：video.image_to_video 的 ModelDescriptor 可声明
        supports: {native_audio, voice_reference, audio_track_input}
    没声明就按 silent 处理 —— 保守假设不会出错，多生成的音频总能用上。
    """
    endpoints = list(
        db.execute(
            select(CapabilityEndpoint).where(CapabilityEndpoint.enabled.is_(True))
        ).scalars()
    )
    for ep in endpoints:
        raw = ep.caps_cache_json
        if not raw:
            continue
        catalog = CapabilityCatalog.model_validate(raw)
        entry = catalog.get(Capability.video_i2v)
        if entry is None:
            continue
        for model in entry.models:
            supports = dict(getattr(model, "supports", None) or {})
            extra = model.model_dump()
            supports.update(dict(extra.get("supports") or {}))
            if supports.get("native_audio"):
                return "native_audio", {
                    "endpoint": ep.name, "model": model.id, "supports": supports,
                }
    return "silent", {"reason": "未发现声明 native_audio 的 video 模型"}


def _asset_map(db: Session, ids: Sequence[str]) -> dict[str, Asset]:
    clean = [i for i in ids if i]
    if not clean:
        return {}
    return {
        a.id: a
        for a in db.execute(select(Asset).where(Asset.id.in_(clean))).scalars()
    }


def build_manifest(
    db: Session,
    plan: ShotPlan,
    *,
    projection: Projection = "auto",
    include_subtitles: bool = True,
) -> dict[str, Any]:
    """产出交付清单。这是本系统的最终交付物。"""
    detected, detail = detect_projection(db)
    mode: Projection = detected if projection == "auto" else projection

    doc = db.get(ScriptDoc, plan.script_doc_id)
    chapter = db.get(Chapter, doc.chapter_id) if doc else None
    cfg = plan.config_json or {}

    shots = list(
        db.execute(
            select(Shot).where(Shot.shot_plan_id == plan.id).order_by(Shot.order_no)
        ).scalars()
    )
    shot_ids = [s.id for s in shots]

    frames: dict[str, dict[str, FrameSpec]] = {}
    for f in db.execute(
        select(FrameSpec).where(FrameSpec.shot_id.in_(shot_ids))
    ).scalars() if shot_ids else []:
        frames.setdefault(f.shot_id, {})[f.role.value] = f

    audio_by_shot: dict[str, list[AudioSpec]] = {}
    audio_by_scene: dict[str, list[AudioSpec]] = {}
    scene_ids = [s.scene_id for s in shots if s.scene_id]
    for a in db.execute(
        select(AudioSpec).where(
            (AudioSpec.shot_id.in_(shot_ids))
            | ((AudioSpec.shot_id.is_(None)) & (AudioSpec.scene_id.in_(scene_ids)))
        )
    ).scalars() if shot_ids else []:
        if a.shot_id:
            audio_by_shot.setdefault(a.shot_id, []).append(a)
        elif a.scene_id:
            audio_by_scene.setdefault(a.scene_id, []).append(a)

    asset_ids = [
        *(f.asset_id for pair in frames.values() for f in pair.values()),
        *(a.asset_id for lst in audio_by_shot.values() for a in lst),
        *(a.asset_id for lst in audio_by_scene.values() for a in lst),
    ]
    assets = _asset_map(db, asset_ids)

    entities = {
        e.id: e
        for e in db.execute(
            select(WorldEntity).where(WorldEntity.novel_id == chapter.novel_id)
        ).scalars()
    } if chapter else {}

    out_shots: list[dict[str, Any]] = []
    warnings: list[str] = []
    cursor_ms = 0

    for shot in shots:
        pair = frames.get(shot.id, {})
        first = pair.get(FrameRole.first.value)
        last = pair.get(FrameRole.last.value)
        first_asset = assets.get(first.asset_id) if first and first.asset_id else None
        last_asset = assets.get(last.asset_id) if last and last.asset_id else None

        if first_asset is None:
            warnings.append(f"镜头 {shot.order_no} 缺首帧")
        if last_asset is None:
            warnings.append(f"镜头 {shot.order_no} 缺尾帧")

        entry: dict[str, Any] = {
            "index": shot.order_no,
            "shot_id": shot.id,
            "start_ms": cursor_ms,
            "duration_ms": shot.duration_ms,
            "shot_size": shot.shot_size,
            "camera": shot.camera_json or {},
            "description": shot.description,
            "first_frame": first_asset.url if first_asset else None,
            "last_frame": last_asset.url if last_asset else None,
            "motion_prompt": _motion_prompt(db, shot),
            # 首尾帧的完整提示词。下游要重出或改图时靠它，
            # 只给一张图的 URL 是改不动的
            "first_frame_prompt": first.prompt if first else None,
            "last_frame_prompt": last.prompt if last else None,
            "crew": _crew_block(db, shot),
        }

        specs = sorted(
            audio_by_shot.get(shot.id, []),
            key=lambda a: (a.kind != AudioKind.dialogue, a.id),
        )
        local = 0
        directives: list[dict[str, Any]] = []
        tracks: list[dict[str, Any]] = []
        subtitles: list[dict[str, Any]] = []

        for spec in specs:
            if spec.kind not in {AudioKind.dialogue, AudioKind.narration,
                                 AudioKind.sfx}:
                continue
            asset = assets.get(spec.asset_id) if spec.asset_id else None
            dur = spec.duration_ms or (
                int((asset.meta_json or {}).get("duration_ms") or 0) if asset else 0
            )
            speaker = entities.get(spec.entity_id) if spec.entity_id else None
            params = spec.params_json or {}

            if mode == "native_audio":
                # 交给视频模型自己念：给它文本、音色参考与时长约束
                directives.append({
                    "kind": spec.kind.value,
                    "text": spec.text,
                    "speaker": speaker.display_name if speaker else None,
                    "voice_asset_key": params.get("voice_asset_key"),
                    "voice_reference": _first_ref_url(
                        db, params.get("voice_reference_asset_ids") or []
                    ),
                    "emotion": params.get("emotion"),
                    "start_ms": local,
                    "target_duration_ms": dur or None,
                })
            else:
                if asset is None:
                    warnings.append(
                        f"镜头 {shot.order_no} 的{spec.kind.value}音频未生成"
                    )
                tracks.append({
                    "kind": spec.kind.value,
                    "file": asset.url if asset else None,
                    "start_ms": local,
                    "duration_ms": dur or None,
                    "speaker": speaker.display_name if speaker else None,
                })

            if include_subtitles and spec.kind in {
                AudioKind.dialogue, AudioKind.narration
            } and spec.text:
                subtitles.append({
                    "text": spec.text,
                    "start_ms": cursor_ms + local,
                    "end_ms": cursor_ms + local + (dur or 0),
                    "speaker": speaker.display_name if speaker else None,
                })
            local += dur or 0

        if mode == "native_audio":
            entry["audio_directive"] = {
                "mode": "native",
                "lines": directives,
                "ambience_prompt": _scene_prompt(
                    audio_by_scene.get(shot.scene_id, []), AudioKind.ambience
                ),
                "music_prompt": _scene_prompt(
                    audio_by_scene.get(shot.scene_id, []), AudioKind.bgm
                ),
            }
        else:
            entry["audio_tracks"] = tracks
        if subtitles:
            entry["subtitles"] = subtitles

        out_shots.append(entry)
        cursor_ms += shot.duration_ms

    scenes_out: list[dict[str, Any]] = []
    for sid in dict.fromkeys(scene_ids):
        scene = db.get(Scene, sid)
        if scene is None:
            continue
        beds = audio_by_scene.get(sid, [])
        item: dict[str, Any] = {
            "scene_id": sid, "title": scene.title,
            "shot_range": [
                s.order_no for s in shots if s.scene_id == sid
            ][:1] + [
                s.order_no for s in shots if s.scene_id == sid
            ][-1:],
        }
        if mode == "silent":
            for spec in beds:
                asset = assets.get(spec.asset_id) if spec.asset_id else None
                key = "bgm" if spec.kind == AudioKind.bgm else "room_tone"
                item[key] = asset.url if asset else None
        scenes_out.append(item)

    return {
        "chapter": {
            "id": chapter.id if chapter else None,
            "title": chapter.title if chapter else None,
            "novel_id": chapter.novel_id if chapter else None,
        },
        "projection": mode,
        "projection_detected": detected,
        "projection_detail": detail,
        "language": plan.target_language_code,
        "aspect_ratio": cfg.get("aspect_ratio"),
        "director": cfg.get("director_code"),
        "fps": 24,
        "total_duration_ms": cursor_ms,
        "shots": out_shots,
        "scenes": scenes_out,
        "warnings": warnings,
        "notes": (
            "视频合成不在本系统范围内。"
            + ("本清单假定下游视频模型自带音频，对白以指令形式交付，"
               "voice_reference 用于保持音色与素材包一致；"
               "target_duration_ms 是硬约束，不可自行伸缩。"
               if mode == "native_audio" else
               "音频已生成为独立音轨，按 start_ms 对齐即可；"
               "视频模型只需按 duration_ms 出画面。")
        ),
    }


def _motion_prompt(db: Session, shot: Shot) -> str:
    """这一镜的运动，**英文**。

    优先用运动描述那一份（起幅落幅怎么走都写清了），
    没有才回落到分镜的相机字段。

    **不回落到 shot.description** —— 那是中文，
    而视频模型和图像模型一样不认中文：喂中文出来的是纹样不是画面。
    宁可只给「static locked-off」这一句，也不要掺一段读不懂的文字。
    """
    from app.models import ShotMotion

    m = db.execute(
        select(ShotMotion).where(ShotMotion.shot_id == shot.id)
    ).scalars().first()
    if m is not None and m.motion_prompt_en:
        return m.motion_prompt_en
    cam = shot.camera_json or {}
    bits = [str(cam.get("move") or "static").replace("_", " ")]
    if cam.get("speed") is not None:
        bits.append(f"speed {cam['speed']}")
    return ", ".join(bits)


def _crew_block(db: Session, shot: Shot) -> dict[str, Any]:
    """这一镜八个工种的英文产出。

    **交付清单里原来没有制作单** —— 主要交付物不含主要内容。
    下游拿到首尾帧与运动，却拿不到灯光方位、材质、色调、服化、视效，
    只能自己猜，而猜出来的东西跨镜不一致。
    """
    from app.models import CrewSheet

    rows = db.execute(
        select(CrewSheet).where(CrewSheet.shot_id == shot.id)
    ).scalars()
    return {r.role: r.prompt_en for r in rows if r.prompt_en}


def _scene_prompt(specs: Sequence[AudioSpec], kind: AudioKind) -> str | None:
    for spec in specs:
        if spec.kind == kind:
            return (spec.params_json or {}).get("prompt") or spec.text
    return None


def _first_ref_url(db: Session, ids: Sequence[str]) -> str | None:
    if not ids:
        return None
    return db.execute(
        select(Asset.url).where(Asset.id.in_(list(ids))).limit(1)
    ).scalars().first()
