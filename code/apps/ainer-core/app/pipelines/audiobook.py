"""有声书 —— 译本审核通过后，按段落配音。

与分镜配音的区别只在挂载点：
    分镜配音   AudioSpec 挂 shot_id，时长要回填到镜头
    有声书     AudioSpec 只挂 block_id，时长用于章节时间轴与字幕

音色仍来自 voice 素材，与分镜共用同一套 —— 同一个角色在有声书和视频里
必须是同一个嗓子，否则两条产线各说各话。
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
    Asset, AssetKindSpec, AssetSpec, AssetVariant, AudioKind, AudioSpec, BlockType,
    Chapter, ScriptBlock, SpecStatus, TranslationBlock, WorldEntity, WorldProfile,
    WorldTransform,
)
from app.pipelines import casting
from app.pipelines.base import PipelineError, checkpoint

log = logging.getLogger(__name__)

NARRATOR_KEY = "voice.narrator"


@dataclass
class AudiobookResult:
    narration: int = 0
    dialogue: int = 0
    skipped_untranslated: int = 0
    missing_voice: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "narration": self.narration, "dialogue": self.dialogue,
            "skipped_untranslated": self.skipped_untranslated,
            "missing_voice": self.missing_voice,
        }


def _voice_index(
    db: Session, novel_id: str, profile_id: str
) -> dict[str, tuple[AssetSpec, AssetVariant]]:
    rows = db.execute(
        select(AssetSpec, AssetVariant)
        .join(AssetVariant, AssetVariant.asset_spec_id == AssetSpec.id)
        .where(
            AssetSpec.novel_id == novel_id,
            AssetVariant.world_profile_id == profile_id,
            AssetSpec.kind == AssetKindSpec.voice,
        )
    ).all()
    return {spec.canonical_key: (spec, var) for spec, var in rows}


def compile_audiobook(
    db: Session, chapter: Chapter, transform: WorldTransform,
) -> AudiobookResult:
    """把译本编译成有声书音频规格。"""
    from app.pipelines.prose import active_prose_doc

    doc = active_prose_doc(db, chapter.id)
    if doc is None:
        raise PipelineError("该章节还没有译本分块")

    profile = db.get(WorldProfile, transform.target_profile_id)
    lang = transform.target_language_code
    voices = _voice_index(db, chapter.novel_id, profile.id)

    blocks = list(
        db.execute(
            select(ScriptBlock).where(ScriptBlock.script_doc_id == doc.id)
            .order_by(ScriptBlock.seq_no)
        ).scalars()
    )
    trans = {
        t.script_block_id: t
        for t in db.execute(
            select(TranslationBlock).where(
                TranslationBlock.script_block_id.in_([b.id for b in blocks]),
                TranslationBlock.transform_id == transform.id,
            )
        ).scalars()
    }
    existing = {
        (a.block_id, a.kind): a
        for a in db.execute(
            select(AudioSpec).where(
                AudioSpec.block_id.in_([b.id for b in blocks]),
                AudioSpec.shot_id.is_(None), AudioSpec.scene_id.is_(None),
            )
        ).scalars()
    }

    result = AudiobookResult()
    for block in blocks:
        tb = trans.get(block.id)
        text = (tb.translated_text if tb else "") or ""
        if not text.strip():
            result.skipped_untranslated += 1
            continue

        is_dialogue = block.block_type == BlockType.dialogue
        kind = AudioKind.dialogue if is_dialogue else AudioKind.narration

        entity = (
            db.get(WorldEntity, block.speaker_entity_id)
            if block.speaker_entity_id else None
        )
        pair = None
        if entity is not None:
            pair = next(
                (
                    (sp_, v) for sp_, v in voices.values()
                    if sp_.entity_id == entity.id
                ),
                voices.get(f"voice.{entity.canonical_key.split('.', 1)[-1]}"),
            )
        # 音色权威是配音表 —— 有声书与分镜必须查同一张表，
        # 否则同一个角色在两条产线上是两个嗓子
        cast_row = casting.voice_for(
            db, block.speaker_entity_id if is_dialogue else casting.NARRATOR,
            profile.id,
        )
        if not is_dialogue:
            pair = pair or voices.get(NARRATOR_KEY)
        elif pair is None and cast_row is None:
            # 对白不借旁白的嗓子。见 audio_compose 里同一处的说明
            label = entity.display_name if entity else (block.speaker_tag or "未知")
            if label not in result.missing_voice:
                result.missing_voice.append(label)

        params: dict[str, Any] = {}
        if pair is not None:
            spec, var = pair
            structured = var.structured_json or {}
            params["voice_asset_key"] = spec.canonical_key
            if structured.get("voice_id"):
                params["voice_id"] = str(structured["voice_id"])
            if structured.get("emotional_baseline"):
                params["emotion"] = str(structured["emotional_baseline"])
            if var.ref_asset_ids:
                params["voice_reference_asset_ids"] = list(var.ref_asset_ids)
        if cast_row is not None:
            params.update(casting.casting_params(cast_row))
            if cast_row.voice_asset_id and not params.get(
                    "voice_reference_asset_ids"):
                params["voice_reference_asset_ids"] = [cast_row.voice_asset_id]

        row = existing.get((block.id, kind))
        if row is None:
            db.add(AudioSpec(
                id=new_id("ab"), shot_id=None, scene_id=None, kind=kind,
                block_id=block.id, entity_id=entity.id if entity else None,
                text=text, language_code=lang, params_json=params,
                status=SpecStatus.pending,
            ))
        else:
            row.text = text
            row.language_code = lang
            row.params_json = params
            row.entity_id = entity.id if entity else None

        if is_dialogue:
            result.dialogue += 1
        else:
            result.narration += 1

    db.flush()
    return result


@dataclass
class AudiobookGenResult:
    submitted: int = 0
    skipped: int = 0
    estimated_cost: float | None = None
    requires_confirm: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "submitted": self.submitted, "skipped": self.skipped,
            "estimated_cost": self.estimated_cost,
            "requires_confirm": self.requires_confirm,
        }


def generate_audiobook(
    db: Session, chapter: Chapter, *, regenerate: bool = False,
    confirm_cost: bool = False, cost_threshold: float = 1.0,
) -> AudiobookGenResult:
    """提交有声书 TTS。"""
    specs = _chapter_specs(db, chapter)
    result = AudiobookGenResult()
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

    est = estimate_cost(db, Capability.audio_tts, "narration", len(pending))
    result.estimated_cost = est
    if est is not None and est > cost_threshold and not confirm_cost:
        result.requires_confirm = True
        return result

    for spec in pending:
        params = dict(spec.params_json or {})
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
        ref_ids = params.get("voice_reference_asset_ids") or []
        url = db.execute(
            select(Asset.url).where(Asset.id.in_(ref_ids)).limit(1)
        ).scalars().first() if ref_ids else None
        if url:
            payload["reference_audio"] = {"url": url}

        task = submit_task(
            db, Capability.audio_tts, payload, purpose=spec.kind.value, force=regenerate,
            ref_kind="audio_spec", ref_id=spec.id,
            novel_id=chapter.novel_id, chapter_id=chapter.id,
        )
        spec.gen_task_id = task.id
        spec.status = SpecStatus.generating
        result.submitted += 1
        checkpoint(db)   # 这一条已经付过费了，先落库

    db.flush()
    return result


def _chapter_specs(db: Session, chapter: Chapter) -> list[AudioSpec]:
    from app.pipelines.prose import active_prose_doc

    doc = active_prose_doc(db, chapter.id)
    if doc is None:
        return []
    block_ids = [
        b.id for b in db.execute(
            select(ScriptBlock).where(ScriptBlock.script_doc_id == doc.id)
        ).scalars()
    ]
    if not block_ids:
        return []
    return list(
        db.execute(
            select(AudioSpec).where(
                AudioSpec.block_id.in_(block_ids),
                AudioSpec.shot_id.is_(None), AudioSpec.scene_id.is_(None),
            )
        ).scalars()
    )


def build_timeline(db: Session, chapter: Chapter) -> dict[str, Any]:
    """章节音频时间轴。交付给拼接工具，本系统不做音频合成。"""
    from app.pipelines.prose import active_prose_doc

    doc = active_prose_doc(db, chapter.id)
    if doc is None:
        raise PipelineError("该章节还没有译本分块")

    blocks = {
        b.id: b
        for b in db.execute(
            select(ScriptBlock).where(ScriptBlock.script_doc_id == doc.id)
            .order_by(ScriptBlock.seq_no)
        ).scalars()
    }
    specs = sorted(
        _chapter_specs(db, chapter),
        key=lambda s: blocks[s.block_id].seq_no if s.block_id in blocks else 0,
    )
    asset_ids = [s.asset_id for s in specs if s.asset_id]
    assets = {
        a.id: a
        for a in db.execute(select(Asset).where(Asset.id.in_(asset_ids))).scalars()
    } if asset_ids else {}

    entities = {
        e.id: e.display_name
        for e in db.execute(
            select(WorldEntity).where(WorldEntity.novel_id == chapter.novel_id)
        ).scalars()
    }

    cursor = 0
    items: list[dict[str, Any]] = []
    missing = 0
    for spec in specs:
        asset = assets.get(spec.asset_id) if spec.asset_id else None
        dur = spec.duration_ms or int((asset.meta_json or {}).get("duration_ms") or 0)
        if asset is None:
            missing += 1
        block = blocks.get(spec.block_id)
        items.append({
            "block_id": spec.block_id,
            "seq_no": block.seq_no if block else None,
            "kind": spec.kind.value,
            "speaker": entities.get(spec.entity_id) if spec.entity_id else None,
            "voice_asset_key": (spec.params_json or {}).get("voice_asset_key"),
            "text": spec.text,
            "file": asset.url if asset else None,
            "start_ms": cursor,
            "duration_ms": dur or None,
        })
        cursor += dur or 0

    return {
        "chapter_id": chapter.id, "chapter_title": chapter.title,
        "total_duration_ms": cursor,
        "segments": items,
        "stats": {
            "segments": len(items), "generated": len(items) - missing,
            "missing": missing,
        },
        "notes": "音频拼接不在本系统范围内。按 start_ms 顺序拼接即可。",
    }
