"""时期解析与素材复用。

三件事：
    resolve_epoch    这一章该用哪一期的素材
    compose_prompt   把 invariant 与 variant 拼成提示词
    find_reusable    这个场景以前出现过吗，出现过就复用同一份

## 为什么复用要单独做

「探访故乡」那一镜要和二十章前的老家长得一样。
不复用的话，两次各自生成，两个院子只是「都叫老家」而已 ——
读者/观众会立刻看出这不是同一个地方。

复用不是省钱，是**一致性的唯一保证**：同一份素材、同一张参考图、
同一段提示词，才谈得上同一个地方。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.ids import new_id
from app.models import (
    INVARIANT_FIELDS, VARIANT_FIELDS, AssetEpoch, AssetSpec, AssetVariant,
    Chapter, EpochBinding, EpochKind, ReviewStatus, ScriptDoc, Shot, ShotPlan,
    WorldEntity,
)

log = logging.getLogger(__name__)


def resolve_epoch(
    db: Session, subject_key: str, profile_id: str, chapter_order: int | None,
) -> AssetEpoch | None:
    """取该章节该用的那一期。subject_key 是素材 id 或人物 id。

    区间匹配：from ≤ 章节 ≤ to，to 为空表示延续到全书结束。
    命中多个时取 order_no 最大的 —— 后设的时期覆盖先设的，
    「断臂之后」应该压过「中年」。
    """
    if chapter_order is None:
        chapter_order = 1
    rows = list(db.execute(
        select(AssetEpoch).where(
            AssetEpoch.subject_key == subject_key,
            AssetEpoch.world_profile_id == profile_id,
            AssetEpoch.from_chapter_order <= chapter_order,
            or_(AssetEpoch.to_chapter_order.is_(None),
                AssetEpoch.to_chapter_order >= chapter_order),
        ).order_by(AssetEpoch.order_no.desc())
    ).scalars())
    return rows[0] if rows else None


def compose_epoch_prompt(epoch: AssetEpoch, kind: str = "character") -> str:
    """把不变与可变拼成完整提示词。

    **顺序固定：invariant 在前。** 图像模型对前面的词更敏感，
    把同一性锚点放前面，衣着道具放后面 —— 换了衣服脸还是那张脸。
    反过来放，生成的结果会更像「一个穿着某某衣服的人」
    而不是「某某人穿了衣服」。
    """
    inv = epoch.invariant_json or {}
    var = epoch.variant_json or {}
    parts: list[str] = []
    for key in INVARIANT_FIELDS.get(kind, ()):
        v = inv.get(key)
        if v:
            parts.append(str(v))
    for key in VARIANT_FIELDS.get(kind, ()):
        v = var.get(key)
        if v:
            parts.append(str(v))
    # 结构化字段之外自由填的，也带上
    for extra in (inv, var):
        for k, v in extra.items():
            if k not in INVARIANT_FIELDS.get(kind, ()) and \
               k not in VARIANT_FIELDS.get(kind, ()) and v:
                parts.append(str(v))
    return ", ".join(p for p in parts if p)


def subject_of(db: Session, key: str) -> tuple[AssetSpec | WorldEntity | None, str]:
    """这个 subject_key 指的是素材还是人物，以及它叫什么。

    真查一次而不是看 id 前缀 —— 前缀是 ids 模块的实现细节，
    改了前缀这里会静默地把人物当成素材，而症状要到出图时才显现。
    """
    spec = db.get(AssetSpec, key)
    if spec is not None:
        return spec, spec.display_name
    ent = db.get(WorldEntity, key)
    if ent is not None:
        return ent, ent.display_name
    return None, key


@dataclass
class ReuseHit:
    shot_id: str
    epoch_id: str | None
    chapter_order: int | None
    note: str


def find_reusable(
    db: Session, subject_key: str, epoch_id: str | None, *,
    exclude_shot: str | None = None,
) -> ReuseHit | None:
    """这份素材以前哪个镜头用过。

    优先同一期的绑定 —— 同一期意味着形态相同，
    直接复用它当时的参考图，「探访故乡」才会和二十章前是同一个院子。
    """
    q = select(EpochBinding).where(EpochBinding.subject_key == subject_key)
    if epoch_id:
        q = q.where(EpochBinding.asset_epoch_id == epoch_id)
    if exclude_shot:
        q = q.where(EpochBinding.shot_id != exclude_shot)
    rows = list(db.execute(q.order_by(EpochBinding.created_at.asc())).scalars())
    if not rows:
        return None
    first = rows[0]
    shot = db.get(Shot, first.shot_id)
    order = None
    if shot is not None:
        plan = db.get(ShotPlan, shot.shot_plan_id)
        doc = db.get(ScriptDoc, plan.script_doc_id) if plan else None
        ch = db.get(Chapter, doc.chapter_id) if doc else None
        order = ch.order_no if ch else None
    return ReuseHit(
        shot_id=first.shot_id, epoch_id=first.asset_epoch_id,
        chapter_order=order,
        note=f"第 {order} 章的镜头用过同一期素材" if order else "此前的镜头用过",
    )


@dataclass
class BindResult:
    shots: int = 0
    bound: int = 0
    reused: int = 0
    fallback: int = 0
    missing_epoch: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "shots": self.shots, "bound": self.bound, "reused": self.reused,
            "fallback": self.fallback, "missing_epoch": self.missing_epoch,
        }


def bind_epochs(
    db: Session, plan: ShotPlan, profile_id: str, spec_ids_by_shot: dict[str, list[str]],
) -> BindResult:
    """为一个分镜计划的每个镜头绑定素材时期。

    没有时期数据时回落到基准形态（AssetVariant）并记 fallback ——
    **不是静默跳过**：回落意味着这个素材全书一个样，
    如果它其实是个会变的人物，那就是个需要人看一眼的问题。
    """
    doc = db.get(ScriptDoc, plan.script_doc_id)
    chapter = db.get(Chapter, doc.chapter_id) if doc else None
    order = chapter.order_no if chapter else None

    result = BindResult()
    existing = {
        (b.shot_id, b.subject_key): b
        for b in db.execute(
            select(EpochBinding).where(
                EpochBinding.shot_id.in_(list(spec_ids_by_shot))
            )
        ).scalars()
    }

    for shot_id, spec_ids in spec_ids_by_shot.items():
        result.shots += 1
        for spec_id in spec_ids:
            epoch = resolve_epoch(db, spec_id, profile_id, order)
            reuse = find_reusable(db, spec_id, epoch.id if epoch else None,
                                  exclude_shot=shot_id)
            row = existing.get((shot_id, spec_id))
            if row is None:
                subject, _name = subject_of(db, spec_id)
                is_entity = isinstance(subject, WorldEntity)
                row = EpochBinding(
                    id=new_id("eb"), shot_id=shot_id, subject_key=spec_id,
                    asset_spec_id=None if is_entity else spec_id,
                    entity_id=spec_id if is_entity else None,
                )
                db.add(row)
                existing[(shot_id, spec_id)] = row
            row.asset_epoch_id = epoch.id if epoch else None
            if epoch is None:
                row.resolved_by = "fallback"
                row.note = "该素材没有时期数据，用基准形态 —— 全书一个样"
                result.fallback += 1
                _subject, name = subject_of(db, spec_id)
                if name not in result.missing_epoch:
                    result.missing_epoch.append(name)
            elif reuse is not None:
                row.resolved_by = "reused"
                row.reused_from_shot_id = reuse.shot_id
                row.note = reuse.note
                result.reused += 1
            else:
                row.resolved_by = "by_chapter"
                row.reused_from_shot_id = None
                row.note = f"第 {order} 章落在「{epoch.display_name}」区间"
            result.bound += 1

    db.flush()
    return result


def seed_baseline_epoch(
    db: Session, spec: AssetSpec, variant: AssetVariant, kind: str,
) -> AssetEpoch:
    """从已有的基准形态生成第一期。

    存量数据都只有 AssetVariant。直接要求全部重填时期不现实，
    所以把它作为 baseline 收进来、覆盖全书 ——
    需要分期的素材再往上加，不需要的（老家、祖传的刀）就此打住。
    """
    row = db.execute(
        select(AssetEpoch).where(
            AssetEpoch.subject_key == spec.id,
            AssetEpoch.world_profile_id == variant.world_profile_id,
            AssetEpoch.epoch_key == "baseline",
        )
    ).scalars().first()
    if row is not None:
        return row

    structured = variant.structured_json or {}
    inv_keys = set(INVARIANT_FIELDS.get(kind, ()))
    var_keys = set(VARIANT_FIELDS.get(kind, ()))
    row = AssetEpoch(
        id=new_id("ae"), subject_key=spec.id, asset_spec_id=spec.id,
        world_profile_id=variant.world_profile_id,
        epoch_key="baseline", display_name="基准形态",
        kind=EpochKind.baseline, order_no=0,
        from_chapter_order=1, to_chapter_order=None,
        invariant_json={k: v for k, v in structured.items() if k in inv_keys} or None,
        variant_json={k: v for k, v in structured.items() if k in var_keys} or None,
        visual_prompt=variant.visual_prompt,
        negative_prompt=variant.negative_prompt,
        ref_asset_ids=variant.ref_asset_ids,
        identity_ref_asset_id=(variant.ref_asset_ids or [None])[0],
        status=variant.status if variant.status is not ReviewStatus.locked
        else ReviewStatus.approved,
        rationale="由基准形态迁移而来，覆盖全书；需要分期的素材再往上加",
    )
    db.add(row)
    db.flush()
    return row
