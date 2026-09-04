"""有声书 —— 译本审核通过后，按段落配音。

与分镜配音的区别只在挂载点：
    分镜配音   AudioSpec 挂 shot_id，时长要回填到镜头
    有声书     AudioSpec 只挂 block_id，时长用于章节时间轴与字幕

音色仍来自 voice 素材，与分镜共用同一套 —— 同一个角色在有声书和视频里
必须是同一个嗓子，否则两条产线各说各话。
"""
from __future__ import annotations

import logging
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.capability.schemas import Capability
from app.capability.service import estimate_cost, submit_task
from app.ids import new_id
from app.models import (
    Asset, AssetKind, AssetKindSpec, AssetSource, AssetSpec, AssetVariant,
    AudioKind, AudioSpec, BlockType, Chapter, ScriptBlock, SpecStatus,
    TranslationBlock, WorldEntity, WorldProfile, WorldTransform,
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
    """章节音频时间轴，并返回最新的整章有声书成品。"""
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
        dur = spec.duration_ms or int(
            ((asset.meta_json or {}) if asset is not None else {}).get("duration_ms") or 0
        )
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

    final_output = None
    for asset in db.execute(
        select(Asset).where(
            Asset.novel_id == chapter.novel_id,
            Asset.kind == AssetKind.audio,
        ).order_by(Asset.created_at.desc())
    ).scalars():
        meta = asset.meta_json or {}
        if meta.get("purpose") == "audiobook_final" and meta.get("chapter_id") == chapter.id:
            final_output = {
                "asset_id": asset.id, "url": asset.url, "bytes": asset.bytes,
                "duration_ms": meta.get("duration_ms"),
                "created_at": asset.created_at.isoformat() if asset.created_at else None,
            }
            break

    return {
        "chapter_id": chapter.id, "chapter_title": chapter.title,
        "total_duration_ms": cursor,
        "segments": items,
        "stats": {
            "segments": len(items), "generated": len(items) - missing,
            "missing": missing,
        },
        "final_output": final_output,
        "notes": "可在本页按 start_ms 连续试听，全部段落生成后可导出单个 M4A 成品。",
    }


def render_audiobook(
    db: Session, chapter: Chapter, *, timeout_sec: int = 900,
) -> dict[str, Any]:
    """把章节的分段 TTS 按权威时间顺序混成一个可直接播放的 M4A。"""
    from app.capability.mediastore import store_bytes
    from app.pipelines import cut

    if not cut.ffmpeg_available():
        raise PipelineError("这台机器上没有 ffmpeg，无法导出整章有声书")
    timeline = build_timeline(db, chapter)
    if not timeline["segments"]:
        raise PipelineError("本章还没有有声书音频规格")
    if timeline["stats"]["missing"]:
        raise PipelineError(
            f"还有 {timeline['stats']['missing']} 段音频未生成，不导出一个中间空段的假成品"
        )

    paths: list[Path] = []
    for segment in timeline["segments"]:
        path = cut._local(segment.get("file"))
        if path is None:
            raise PipelineError(f"音频段 #{segment.get('seq_no')} 的本地文件不可用")
        paths.append(path)

    work = Path(tempfile.mkdtemp(prefix="audiobook_"))
    try:
        inputs: list[str] = []
        filters: list[str] = []
        labels: list[str] = []
        for idx, path in enumerate(paths):
            inputs += ["-i", str(path)]
            filters.append(
                f"[{idx}:a]aresample=48000,"
                "aformat=sample_fmts=fltp:channel_layouts=stereo"
                f"[a{idx}]"
            )
            labels.append(f"[a{idx}]")
        graph = ";".join(filters) + ";" + "".join(labels) + (
            f"concat=n={len(paths)}:v=0:a=1,"
            "loudnorm=I=-16:TP=-1.5:LRA=11[out]"
        )
        out = work / "chapter.m4a"
        cut._run([
            "ffmpeg", "-y", *inputs, "-filter_complex", graph,
            "-map", "[out]", "-c:a", "aac", "-b:a", "192k", str(out),
        ], timeout_sec)
        media = store_bytes(out.read_bytes(), mime="audio/mp4")
        meta = {
            "purpose": "audiobook_final", "chapter_id": chapter.id,
            "duration_ms": timeline["total_duration_ms"],
            "segments": len(paths),
        }
        asset = db.execute(
            select(Asset).where(
                Asset.novel_id == chapter.novel_id,
                Asset.url == str(media["url"]),
            )
        ).scalars().first()
        if asset is None:
            asset = Asset(
                id=new_id("as"), kind=AssetKind.audio,
                url=str(media["url"]), sha256=str(media["sha256"]),
                mime=str(media["mime"]), bytes=int(media["bytes"]),
                meta_json=meta, source=AssetSource.generated,
                novel_id=chapter.novel_id,
            )
            db.add(asset)
        else:
            asset.meta_json = meta
        db.flush()
        return {
            "asset_id": asset.id, "url": asset.url, "bytes": asset.bytes,
            "duration_ms": timeline["total_duration_ms"], "segments": len(paths),
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)
