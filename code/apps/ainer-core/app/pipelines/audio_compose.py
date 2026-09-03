"""音频编译：从素材包拼装 AudioSpec → TTS → 时长回填。

与画面完全对称：对白的音色不是每次随便挑一个，而是绑定到角色的 voice 素材，
用它的参考音频作 voice reference。音色一致性的根 = 参考音频 + voice_id，
正如视觉一致性的根 = 参考图 + seed。

时长权威链（无论下游视频模型带不带音频，这条链都成立）：
    TTS 真实时长 → AudioSpec.duration_ms → Shot.duration_ms → 视频片段时长
先跑 TTS 拿到真实时长，镜头长度才有依据，字幕才能对得上。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.capability.schemas import Capability
from app.capability.service import estimate_cost, submit_task
from app.ids import new_id
from app.models import (
    Asset, AssetKindSpec, AssetSpec, AssetVariant, AudioKind, AudioSpec, Chapter,
    Scene, ScriptBlock, ScriptDoc, Shot, ShotPlan, SpecStatus, TranslationBlock,
    WorldEntity, WorldProfile, WorldTransform,
)
from app.models.script import BlockType
from app.worldview import resolve
from app.pipelines import casting
from app.pipelines.base import PipelineError

log = logging.getLogger(__name__)

#: 旁白使用的 voice 素材 key。
NARRATOR_KEY = "voice.narrator"


@dataclass
class AudioComposeResult:
    dialogue: int = 0
    narration: int = 0
    scene_bgm: int = 0
    scene_tone: int = 0
    missing_voice: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "dialogue": self.dialogue, "narration": self.narration,
            "scene_bgm": self.scene_bgm, "scene_tone": self.scene_tone,
            "missing_voice": self.missing_voice,
        }


def _audio_variants(
    db: Session, novel_id: str, profile_id: str
) -> dict[str, tuple[AssetSpec, AssetVariant]]:
    rows = db.execute(
        select(AssetSpec, AssetVariant)
        .join(AssetVariant, AssetVariant.asset_spec_id == AssetSpec.id)
        .where(
            AssetSpec.novel_id == novel_id,
            AssetVariant.world_profile_id == profile_id,
            AssetSpec.kind.in_([
                AssetKindSpec.voice, AssetKindSpec.bgm,
                AssetKindSpec.sfx, AssetKindSpec.room_tone,
            ]),
        )
    ).all()
    return {spec.canonical_key: (spec, var) for spec, var in rows}


def _voice_for_entity(
    entity: WorldEntity | None,
    variants: dict[str, tuple[AssetSpec, AssetVariant]],
) -> tuple[AssetSpec, AssetVariant] | None:
    """找角色的音色素材。

    优先看素材是否显式挂在该实体上，再按 voice.<canonical_key> 约定查找。
    """
    if entity is None:
        return None
    for spec, var in variants.values():
        if spec.kind == AssetKindSpec.voice and spec.entity_id == entity.id:
            return (spec, var)
    key = f"voice.{entity.canonical_key.split('.', 1)[-1]}"
    return variants.get(key)


def _voice_params(spec: AssetSpec, var: AssetVariant) -> dict[str, Any]:
    structured = var.structured_json or {}
    params: dict[str, Any] = {}
    if structured.get("emotional_baseline"):
        params["emotion"] = str(structured["emotional_baseline"])
    if structured.get("pace"):
        params["style_prompt"] = f"pace: {structured['pace']}"
    return params


def compile_audio(
    db: Session,
    plan: ShotPlan,
    transform: WorldTransform,
    *,
    include_bgm: bool = True,
    include_room_tone: bool = True,
) -> AudioComposeResult:
    """把分镜编译成音频规格。绑定音色素材，不自由挑音色。"""
    profile = db.get(WorldProfile, transform.target_profile_id)
    if profile is None:
        raise PipelineError("目标世界观档案缺失")

    doc = db.get(ScriptDoc, plan.script_doc_id)
    chapter = db.get(Chapter, doc.chapter_id) if doc else None
    if chapter is None:
        raise PipelineError("分镜对应的章节不存在")

    lang = plan.target_language_code or transform.target_language_code
    # 分镜计划可能指向别的语言版本，此时按语言回落到该语言的映射；
    # 同语言下有多版时 active 优先。
    tf_ids = (
        [transform.id] if lang == transform.target_language_code
        else resolve.transform_ids_for(db, chapter.novel_id, lang)
    )
    variants = _audio_variants(db, chapter.novel_id, profile.id)
    result = AudioComposeResult()

    shots = list(
        db.execute(
            select(Shot).where(Shot.shot_plan_id == plan.id).order_by(Shot.order_no)
        ).scalars()
    )
    if not shots:
        raise PipelineError("分镜没有镜头")

    all_block_ids = [bid for s in shots for bid in (s.block_ids_json or [])]
    blocks = {
        b.id: b
        for b in db.execute(
            select(ScriptBlock).where(ScriptBlock.id.in_(all_block_ids))
        ).scalars()
    } if all_block_ids else {}
    translations = {
        t.script_block_id: t.translated_text or ""
        for t in db.execute(
            select(TranslationBlock).where(
                TranslationBlock.script_block_id.in_(all_block_ids),
                TranslationBlock.transform_id.in_(tf_ids),
            )
        ).scalars()
    } if all_block_ids and tf_ids else {}

    existing = {
        (a.shot_id, a.block_id, a.kind): a
        for a in db.execute(
            select(AudioSpec).where(AudioSpec.shot_id.in_([s.id for s in shots]))
        ).scalars()
    }

    for shot in shots:
        for bid in shot.block_ids_json or []:
            block = blocks.get(bid)
            if block is None or block.block_type in {
                BlockType.action, BlockType.scene_break
            }:
                continue
            text = translations.get(bid) or block.source_text or ""
            if not text.strip():
                continue

            is_dialogue = block.block_type == BlockType.dialogue
            kind = AudioKind.dialogue if is_dialogue else AudioKind.narration

            entity = (
                db.get(WorldEntity, block.speaker_entity_id)
                if block.speaker_entity_id else None
            )
            # 音色的权威是配音表，不是素材。素材只提供参考音频与既有 voice_id ——
            # 前者决定「是谁的嗓子」，后者只是某个引擎上的一次落地。
            cast_row = casting.voice_for(
                db,
                block.speaker_entity_id if is_dialogue else casting.NARRATOR,
                profile.id,
            )
            pair = _voice_for_entity(entity, variants) if is_dialogue else None
            if not is_dialogue:
                pair = pair or variants.get(NARRATOR_KEY)
            elif pair is None and cast_row is None:
                # **对白不回落到旁白音色。** 借旁白的嗓子说台词，
                # 数据上看不出问题，听起来却是旁白在自问自答 ——
                # 这种错比「没有音色」更难发现。宁可缺，也不要错。
                label = (entity.display_name if entity
                         else (block.speaker_tag or "未知说话人"))
                if label not in result.missing_voice:
                    result.missing_voice.append(label)

            params: dict[str, Any] = {}
            voice_ref_ids: list[str] = []
            if pair is not None:
                spec, var = pair
                params.update(_voice_params(spec, var))
                vid = (var.structured_json or {}).get("voice_id")
                if vid:
                    params["voice_id"] = str(vid)
                voice_ref_ids = list(var.ref_asset_ids or [])
                params["voice_asset_key"] = spec.canonical_key
            if cast_row is not None:
                # 配音表后写入，覆盖素材上的旧值：它才是权威
                params.update(casting.casting_params(cast_row))
                if cast_row.voice_asset_id and not voice_ref_ids:
                    voice_ref_ids = [cast_row.voice_asset_id]
            if voice_ref_ids:
                params["voice_reference_asset_ids"] = voice_ref_ids

            row = existing.get((shot.id, bid, kind))
            if row is None:
                row = AudioSpec(
                    id=new_id("au"), shot_id=shot.id, scene_id=shot.scene_id,
                    kind=kind, block_id=bid,
                    entity_id=entity.id if entity else None,
                    text=text, language_code=lang, params_json=params,
                    status=SpecStatus.pending,
                )
                db.add(row)
            else:
                row.text = text
                row.language_code = lang
                row.params_json = params
                row.entity_id = entity.id if entity else None
            if is_dialogue:
                result.dialogue += 1
            else:
                result.narration += 1

    # 场景级：BGM 与环境底噪同场景共用一条，不逐镜生成
    scenes = {
        s.id: s
        for s in db.execute(
            select(Scene).where(Scene.id.in_([sh.scene_id for sh in shots if sh.scene_id]))
        ).scalars()
    }
    scene_existing = {
        (a.scene_id, a.kind): a
        for a in db.execute(
            select(AudioSpec).where(
                AudioSpec.scene_id.in_(list(scenes)), AudioSpec.shot_id.is_(None)
            )
        ).scalars()
    } if scenes else {}

    for scene in scenes.values():
        mood = " ".join(str(x) for x in [scene.mood, scene.weather, scene.time_of_day] if x)
        for enabled, kind, asset_kind, default_ms in (
            (include_bgm, AudioKind.bgm, AssetKindSpec.bgm, 30000),
            (include_room_tone, AudioKind.ambience, AssetKindSpec.room_tone, 20000),
        ):
            if not enabled:
                continue
            pair = next(
                ((sp_, v) for sp_, v in variants.values() if sp_.kind == asset_kind), None
            )
            if pair is None:
                continue
            spec, var = pair
            prompt = ", ".join(
                p for p in [var.visual_prompt, mood, scene.location_text] if p
            )
            row = scene_existing.get((scene.id, kind))
            params = {"asset_key": spec.canonical_key, "duration_ms": default_ms,
                      "prompt": prompt}
            if row is None:
                db.add(AudioSpec(
                    id=new_id("au"), shot_id=None, scene_id=scene.id, kind=kind,
                    text=prompt, language_code=lang, params_json=params,
                    status=SpecStatus.pending,
                ))
            else:
                row.text = prompt
                row.params_json = params
            if kind == AudioKind.bgm:
                result.scene_bgm += 1
            else:
                result.scene_tone += 1

    db.flush()
    return result


@dataclass
class AudioGenResult:
    submitted: int = 0
    skipped: int = 0
    estimated_cost: float | None = None
    requires_confirm: bool = False
    blocked: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "submitted": self.submitted, "skipped": self.skipped,
            "estimated_cost": self.estimated_cost,
            "requires_confirm": self.requires_confirm, "blocked": self.blocked,
        }


def generate_audio(
    db: Session,
    plan: ShotPlan,
    *,
    kinds: Sequence[str] | None = None,
    regenerate: bool = False,
    confirm_cost: bool = False,
    cost_threshold: float = 1.0,
) -> AudioGenResult:
    """提交音频生成。对白带上音色素材的参考音频作 voice reference。"""
    shots = list(
        db.execute(select(Shot).where(Shot.shot_plan_id == plan.id)).scalars()
    )
    shot_ids = [s.id for s in shots]
    scene_ids = [s.scene_id for s in shots if s.scene_id]

    q = select(AudioSpec).where(
        (AudioSpec.shot_id.in_(shot_ids))
        | ((AudioSpec.shot_id.is_(None)) & (AudioSpec.scene_id.in_(scene_ids)))
    )
    if kinds:
        q = q.where(AudioSpec.kind.in_([AudioKind(k) for k in kinds]))
    specs = list(db.execute(q).scalars())

    result = AudioGenResult()
    pending = []
    for spec in specs:
        if spec.asset_id and not regenerate:
            result.skipped += 1
            continue
        if not (spec.text or "").strip():
            continue
        pending.append(spec)
    if not pending:
        return result

    tts_n = sum(
        1 for s in pending if s.kind in {AudioKind.dialogue, AudioKind.narration}
    )
    est = estimate_cost(db, Capability.audio_tts, "dialogue", tts_n) if tts_n else 0.0
    result.estimated_cost = est
    if est is not None and est > cost_threshold and not confirm_cost:
        result.requires_confirm = True
        return result

    doc = db.get(ScriptDoc, plan.script_doc_id)
    chapter = db.get(Chapter, doc.chapter_id) if doc else None

    for spec in pending:
        params = dict(spec.params_json or {})
        if spec.kind in {AudioKind.dialogue, AudioKind.narration}:
            payload: dict[str, Any] = {
                "text": spec.text,
                "language": spec.language_code or "en-US",
                "with_timestamps": True,
                "params": {
                    k: v for k, v in params.items()
                    if k in {"emotion", "speed", "pitch", "volume_db", "style_prompt"}
                },
            }
            if params.get("voice_id"):
                payload["voice_id"] = params["voice_id"]
            # 音色一致性：把素材的参考音频作为 voice reference
            ref_ids = params.get("voice_reference_asset_ids") or []
            ref_url = next(iter(_asset_urls(db, ref_ids)), None)
            if ref_url:
                payload["reference_audio"] = {"url": ref_url}
            cap, purpose = Capability.audio_tts, spec.kind.value
        elif spec.kind == AudioKind.bgm:
            payload = {
                "prompt": params.get("prompt") or spec.text,
                "duration_ms": int(params.get("duration_ms") or 30000),
                "loopable": True, "instrumental": True,
            }
            cap, purpose = Capability.audio_music, "bgm"
        else:
            payload = {
                "prompt": params.get("prompt") or spec.text,
                "duration_ms": int(params.get("duration_ms") or 20000),
            }
            cap, purpose = Capability.audio_sfx, spec.kind.value

        task = submit_task(
            db, cap, payload, purpose=purpose,
            ref_kind="audio_spec", ref_id=spec.id,
            novel_id=chapter.novel_id if chapter else None,
            chapter_id=chapter.id if chapter else None,
            force=regenerate,
        )
        spec.gen_task_id = task.id
        spec.status = SpecStatus.generating
        result.submitted += 1

    db.flush()
    return result


def backfill_durations(db: Session, plan: ShotPlan) -> dict[str, Any]:
    """把 TTS 的真实时长回填到镜头。

    这是时长权威链的落点：镜头长度由配音决定，不由文本估算决定。
    无论下游视频模型带不带音频，这一步都要做 —— 带音频的模型也需要
    一个确定的时长约束，否则字幕对不上。
    """
    shots = list(
        db.execute(
            select(Shot).where(Shot.shot_plan_id == plan.id).order_by(Shot.order_no)
        ).scalars()
    )
    if not shots:
        return {"updated": 0, "shots": 0}

    specs = list(
        db.execute(
            select(AudioSpec).where(
                AudioSpec.shot_id.in_([s.id for s in shots]),
                AudioSpec.kind.in_([AudioKind.dialogue, AudioKind.narration]),
                AudioSpec.duration_ms.is_not(None),
            )
        ).scalars()
    )
    by_shot: dict[str, int] = {}
    for spec in specs:
        by_shot[spec.shot_id] = by_shot.get(spec.shot_id, 0) + int(spec.duration_ms or 0)

    updated = 0
    total_before = total_after = 0
    for shot in shots:
        voiced = by_shot.get(shot.id)
        total_before += shot.duration_ms
        if not voiced:
            total_after += shot.duration_ms
            continue
        # 留一点呼吸：配音前后各 200ms
        target = voiced + 400
        if target != shot.duration_ms:
            shot.duration_ms = max(target, 1200)
            updated += 1
        total_after += shot.duration_ms

    db.flush()
    return {
        "shots": len(shots), "updated": updated,
        "duration_before_ms": total_before, "duration_after_ms": total_after,
        "voiced_shots": len(by_shot),
    }


def _asset_urls(db: Session, ids: Sequence[str]) -> list[str]:
    if not ids:
        return []
    return [
        u for u in db.execute(
            select(Asset.url).where(Asset.id.in_(list(ids)))
        ).scalars() if u
    ]
