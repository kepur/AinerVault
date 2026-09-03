"""素材参考图 —— 一致性的根。

先把「文士长袍长什么样」定死，后面几百个镜头都引它，一致性才有根。
所以参考图必须先于分镜生成，而不是跟着镜头按需生成。

生成顺序是有依赖的：
  1  style 素材   全书画风基调，无参考图，纯 t2i
  2  其余素材     以 style 的成图作 style reference，画风才统一
  3  人物         以 costume 变体 + style 作 ref
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.capability.schemas import Capability
from app.capability.service import estimate_cost, submit_task
from app.worldview.asset_requirements import is_audio_kind
from app.models import (
    Asset, AssetKindSpec, AssetSpec, AssetVariant, ReviewStatus, WorldProfile,
    WorldTransform,
)
from app.pipelines.base import PipelineError, as_text, checkpoint

log = logging.getLogger(__name__)

#: 生成顺序。style 必须最先 —— 它是其余视觉素材的 style reference。
KIND_ORDER: tuple[AssetKindSpec, ...] = (
    AssetKindSpec.style,
    AssetKindSpec.location,
    AssetKindSpec.costume,
    AssetKindSpec.prop,
    AssetKindSpec.creature,
    AssetKindSpec.ambience,
    # 音频素材无依赖顺序，排在视觉之后
    AssetKindSpec.voice,
    AssetKindSpec.room_tone,
    AssetKindSpec.sfx,
    AssetKindSpec.bgm,
)

#: 音色样本用的试听句。要覆盖常见音素且有情绪落点，
#: 太短听不出音色，太长浪费额度。
VOICE_SAMPLE_TEXT: dict[str, str] = {
    "ja": "こんばんは。ずいぶん早かったですね。雨の中、よくいらっしゃいました。",
    "zh": "你来了。这么快就到了，路上可还顺利？",
    "en": "You've come. That was quicker than I expected — was the road clear?",
    "ko": "오셨군요. 생각보다 빨리 도착하셨네요.",
}

#: 音频素材的默认时长
AUDIO_DURATION_MS: dict[str, int] = {
    AssetKindSpec.sfx.value: 2500,
    AssetKindSpec.bgm.value: 30000,
    AssetKindSpec.room_tone.value: 20000,
}

#: 各类素材的参考图尺寸。场景要宽，服装道具要方。
KIND_SIZE: dict[str, tuple[int, int]] = {
    AssetKindSpec.style.value: (1280, 720),
    AssetKindSpec.location.value: (1280, 720),
    AssetKindSpec.ambience.value: (1280, 720),
    AssetKindSpec.costume.value: (1024, 1024),
    AssetKindSpec.prop.value: (1024, 1024),
    AssetKindSpec.creature.value: (1024, 1024),
    AssetKindSpec.expression.value: (1024, 1024),
    AssetKindSpec.action.value: (1024, 1024),
}

#: 参考图的画面约定 —— 定妆图/设定图，不是剧照
KIND_FRAMING: dict[str, str] = {
    AssetKindSpec.style.value:
        "style reference plate, representative scene, no characters in focus",
    AssetKindSpec.location.value:
        "establishing view of the empty location, no people, eye-level, natural light",
    AssetKindSpec.costume.value:
        "costume reference sheet, full-length front view on a neutral grey backdrop, "
        "garment clearly visible, no face detail",
    AssetKindSpec.prop.value:
        "single object on neutral grey backdrop, three-quarter view, even lighting, "
        "no hands, no background clutter",
    AssetKindSpec.creature.value:
        "full-body side view on neutral backdrop, natural stance",
    AssetKindSpec.ambience.value:
        "atmosphere plate, empty scene showing the light and weather quality only",
}


@dataclass
class RefResult:
    submitted: int = 0
    skipped_existing: int = 0
    skipped_unapproved: int = 0
    estimated_cost: float | None = None
    requires_confirm: bool = False
    tasks: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "submitted": self.submitted,
            "skipped_existing": self.skipped_existing,
            "skipped_unapproved": self.skipped_unapproved,
            "estimated_cost": self.estimated_cost,
            "requires_confirm": self.requires_confirm,
            "tasks": self.tasks,
        }


def compose_ref_prompt(
    spec: AssetSpec, variant: AssetVariant, profile: WorldProfile
) -> tuple[str, str]:
    """拼参考图 prompt。

    全部来自 asset_variant 的结构化字段与世界观约束 —— 这里不自由发挥，
    否则同一件长袍在参考图和镜头里会长成两个样子。
    """
    visual = profile.visual_json or {}
    axes = profile.axes_json or {}

    parts: list[str] = []
    framing = KIND_FRAMING.get(spec.kind.value)
    if framing:
        parts.append(framing)

    if variant.visual_prompt:
        parts.append(variant.visual_prompt.strip())

    # 结构化字段逐项进 prompt，比整段自然语言可控
    structured = variant.structured_json or {}
    for key, value in structured.items():
        val = as_text(value)
        if val:
            parts.append(f"{key.replace('_', ' ')}: {val}")

    era = axes.get("era_span")
    if isinstance(era, list) and len(era) == 2:
        parts.append(f"period-accurate to {era[0]}-{era[1]}")
    if axes.get("region"):
        parts.append(f"region: {axes['region']}")

    do = [str(x) for x in (visual.get("visual_do") or [])][:6]
    if do and spec.kind != AssetKindSpec.style:
        parts.append("world consistency: " + ", ".join(do))

    positive = ", ".join(p for p in parts if p)

    neg_parts: list[str] = []
    if variant.negative_prompt:
        neg_parts.append(variant.negative_prompt.strip())
    neg_parts.extend(str(x) for x in (visual.get("visual_dont") or [])[:8])
    neg_parts.extend(["text", "watermark", "signature", "collage", "multiple views"])
    negative = ", ".join(dict.fromkeys(p for p in neg_parts if p))

    return positive, negative


def _voice_sample_text(language: str) -> str:
    return VOICE_SAMPLE_TEXT.get(language[:2].lower(), VOICE_SAMPLE_TEXT["en"])


def compose_audio_ref_request(
    spec: AssetSpec, variant: AssetVariant, profile: WorldProfile, language: str
) -> tuple[Capability, str, dict[str, Any]]:
    """音频素材的参考样本请求。

    音色素材生成的是「试听句」—— 它既是审听依据，也是后续所有对白的
    voice reference。视觉素材的参考图是什么地位，它就是什么地位。
    """
    structured = variant.structured_json or {}
    descriptor = ", ".join(
        f"{k.replace('_', ' ')}: {v}" for k, v in structured.items() if as_text(v)
    )
    kind = spec.kind

    if kind == AssetKindSpec.voice:
        params: dict[str, Any] = {}
        voice_id = (variant.structured_json or {}).get("voice_id")
        payload: dict[str, Any] = {
            "text": _voice_sample_text(language),
            "language": language,
            "with_timestamps": False,
            "params": params,
        }
        if voice_id:
            payload["voice_id"] = str(voice_id)
        if descriptor:
            params["style_prompt"] = descriptor
        if structured.get("emotional_baseline"):
            params["emotion"] = str(structured["emotional_baseline"])
        return Capability.audio_tts, "voice_ref", payload

    prompt = ", ".join(p for p in [variant.visual_prompt, descriptor] if p)
    era = (profile.axes_json or {}).get("era_span")
    if isinstance(era, list) and len(era) == 2:
        prompt += f", period-accurate to {era[0]}-{era[1]}"
    duration = AUDIO_DURATION_MS.get(kind.value, 5000)

    if kind == AssetKindSpec.bgm:
        return Capability.audio_music, "bgm", {
            "prompt": prompt, "duration_ms": duration,
            "loopable": True, "instrumental": True,
        }
    # sfx 与 room_tone 都走 audio.sfx
    return Capability.audio_sfx, kind.value, {
        "prompt": prompt, "duration_ms": duration,
    }


def _style_refs(db: Session, transform: WorldTransform) -> list[str]:
    """取该世界观下 style 素材已生成的参考图，作为其余素材的 style reference。"""
    rows = db.execute(
        select(AssetVariant, AssetSpec)
        .join(AssetSpec, AssetSpec.id == AssetVariant.asset_spec_id)
        .where(
            AssetVariant.world_profile_id == transform.target_profile_id,
            AssetSpec.novel_id == transform.novel_id,
            AssetSpec.kind == AssetKindSpec.style,
        )
    ).all()
    out: list[str] = []
    for variant, _spec in rows:
        out.extend(variant.ref_asset_ids or [])
    return out[:2]


def _asset_urls(db: Session, asset_ids: Sequence[str]) -> list[str]:
    if not asset_ids:
        return []
    rows = db.execute(
        select(Asset.url).where(Asset.id.in_(list(asset_ids)))
    ).scalars().all()
    return [u for u in rows if u]


def generate_refs(
    db: Session,
    transform: WorldTransform,
    *,
    variant_ids: Sequence[str] | None = None,
    kinds: Sequence[str] | None = None,
    require_approved: bool = True,
    regenerate: bool = False,
    n: int = 1,
    confirm_cost: bool = False,
    cost_threshold: float = 1.0,
) -> RefResult:
    """为素材变体生成参考图。

    require_approved 默认 True —— 没审核过的变体不该烧钱生成图，
    字段还没填全的更不该。
    """
    profile = db.get(WorldProfile, transform.target_profile_id)
    if profile is None:
        raise PipelineError("目标世界观档案缺失")

    q = (
        select(AssetVariant, AssetSpec)
        .join(AssetSpec, AssetSpec.id == AssetVariant.asset_spec_id)
        .where(
            AssetVariant.world_profile_id == profile.id,
            AssetSpec.novel_id == transform.novel_id,
        )
    )
    if variant_ids:
        q = q.where(AssetVariant.id.in_(list(variant_ids)))
    if kinds:
        q = q.where(AssetSpec.kind.in_([AssetKindSpec(k) for k in kinds]))

    rows = list(db.execute(q).all())
    result = RefResult()

    pending: list[tuple[AssetVariant, AssetSpec]] = []
    for variant, spec in rows:
        if require_approved and variant.status == ReviewStatus.candidate:
            result.skipped_unapproved += 1
            continue
        if variant.missing_fields:
            result.skipped_unapproved += 1
            continue
        if variant.ref_asset_ids and not regenerate:
            result.skipped_existing += 1
            continue
        pending.append((variant, spec))

    if not pending:
        return result

    # 成本闸门：生成很贵，批量前先给预估
    visual_n = sum(1 for _v, sp_ in pending if not is_audio_kind(sp_.kind.value))
    unit_total = estimate_cost(db, Capability.image_t2i, "asset_ref", visual_n * n)
    result.estimated_cost = unit_total
    if unit_total is not None and unit_total > cost_threshold and not confirm_cost:
        result.requires_confirm = True
        return result

    # style 先行：它是其余素材的 style reference
    order = {k.value: i for i, k in enumerate(KIND_ORDER)}
    pending.sort(key=lambda pair: order.get(pair[1].kind.value, 99))

    style_ref_urls = _asset_urls(db, _style_refs(db, transform))

    language = transform.target_language_code

    for variant, spec in pending:
        # ── 音频素材：参考物是音色样本，不是图 ──
        if is_audio_kind(spec.kind.value):
            cap, purpose, payload = compose_audio_ref_request(
                spec, variant, profile, language
            )
            task = submit_task(
                db, cap, payload, purpose=purpose,
                ref_kind="asset_variant", ref_id=variant.id,
                novel_id=transform.novel_id,
            )
            result.submitted += 1
            checkpoint(db)   # 这一张已经付过费了，先落库
            result.tasks.append({
                "variant_id": variant.id, "asset": spec.display_name,
                "kind": spec.kind.value, "capability": cap.value,
                "gen_task_id": task.id, "status": task.status.value,
            })
            continue

        positive, negative = compose_ref_prompt(spec, variant, profile)
        width, height = KIND_SIZE.get(spec.kind.value, (1024, 1024))

        refs: list[dict[str, Any]] = []
        if spec.kind != AssetKindSpec.style:
            for url in style_ref_urls:
                refs.append({
                    "ref": {"url": url}, "role": "style", "weight": 0.45,
                    "tag": "world_style",
                })

        payload: dict[str, Any] = {
            "prompt": positive,
            "negative_prompt": negative,
            "width": width, "height": height, "n": n,
        }
        if refs:
            payload["reference_images"] = refs

        task = submit_task(
            db, Capability.image_t2i, payload,
            purpose="asset_ref",
            ref_kind="asset_variant", ref_id=variant.id,
            novel_id=transform.novel_id, force=regenerate,
        )
        variant.gen_note = None if not hasattr(variant, "gen_note") else None
        result.submitted += 1
        checkpoint(db)   # 同上
        result.tasks.append({
            "variant_id": variant.id,
            "asset": spec.display_name,
            "kind": spec.kind.value,
            "gen_task_id": task.id,
            "status": task.status.value,
        })

        # style 图一旦落地，立刻纳入后续素材的 style reference
        if spec.kind == AssetKindSpec.style:
            db.flush()
            new_urls = _asset_urls(db, _collect_task_assets(db, task.id))
            style_ref_urls = (style_ref_urls + new_urls)[:2]

    db.flush()
    return result


def _collect_task_assets(db: Session, gen_task_id: str) -> list[str]:
    return list(
        db.execute(
            select(Asset.id).where(Asset.gen_task_id == gen_task_id)
        ).scalars()
    )


def attach_ref_assets(db: Session, variant_id: str) -> list[str]:
    """把该变体对应任务产出的图挂到 ref_asset_ids 上。

    回调落库后调用；也可由前端在任务完成时触发。
    """
    from app.models import GenTask, TaskStatus

    variant = db.get(AssetVariant, variant_id)
    if variant is None:
        raise PipelineError("asset variant not found")

    tasks = db.execute(
        select(GenTask).where(
            GenTask.ref_kind == "asset_variant",
            GenTask.ref_id == variant_id,
            GenTask.status == TaskStatus.succeeded,
        ).order_by(GenTask.finished_at.desc())
    ).scalars().all()

    asset_ids: list[str] = []
    for t in tasks:
        asset_ids.extend(_collect_task_assets(db, t.id))
    if asset_ids:
        merged = list(dict.fromkeys([*(variant.ref_asset_ids or []), *asset_ids]))
        variant.ref_asset_ids = merged
        db.flush()
    return variant.ref_asset_ids or []


def sync_all_refs(db: Session, transform: WorldTransform) -> dict[str, int]:
    """批量把已完成任务的产图挂回变体。轮询/回调之后调一次。"""
    rows = db.execute(
        select(AssetVariant.id)
        .join(AssetSpec, AssetSpec.id == AssetVariant.asset_spec_id)
        .where(
            AssetVariant.world_profile_id == transform.target_profile_id,
            AssetSpec.novel_id == transform.novel_id,
        )
    ).scalars().all()
    attached = 0
    for vid in rows:
        before = db.get(AssetVariant, vid).ref_asset_ids or []
        after = attach_ref_assets(db, vid)
        if len(after) > len(before):
            attached += 1
    return {"variants_updated": attached, "checked": len(rows)}
