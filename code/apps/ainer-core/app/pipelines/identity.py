"""身份锚 —— 把「同一个人」从文字变成事实。

## 为什么文字一致还不够

时期把「不变的部分逐字复用」做成了纪律：三期用的是同一句
「浓眉，左颊一道旧疤」。但那仍然只是**文字**。
拿同一句话生成三次，出来是三张脸 —— 图像模型对同一段描述的采样
本来就是发散的，而人脸恰恰是人眼最挑剔的部分。

所以跨期同一性的真正落点是一张**共用的脸参考图**：
第一期生成它，后续各期把它作参考图带上，脸就锁住了。
文字负责说清「是什么样」，参考图负责保证「每次都是那一个」。

## 锚必须是素颜半身像，不能是剧照

锚会被后续每一期引用。如果它是「少年林凡穿粗布短打持木剑」的全身像，
那身衣服和那把剑会跟着渗进中年林凡的每一张图 ——
而衣着兵器恰恰是**该变的**那部分。

所以锚只用 invariant 那七项（骨相、五官、瞳色、肤色、疤痕、体型、身高），
构图固定为正面素颜半身、中性光、纯色背景。
不是为了好看，是为了**它不携带任何该变的信息**。

## 一个人只能有一个锚

各期用不同的参考图，等于没有参考图。这条是覆写而不是报警：
锚分叉不是「需要人看一眼」的问题，是直接导致脸漂的错误，
而正确答案没有歧义 —— 最早那一期的锚就是锚。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.capability.schemas import Capability
from app.capability.service import estimate_cost, submit_task
from app.models import (
    INVARIANT_FIELDS, Asset, AssetEpoch, EntityKind, GenTask, TaskStatus,
    WorldEntity, WorldProfile,
)
from app.pipelines.base import PipelineError

log = logging.getLogger(__name__)

CHAR_INVARIANT = INVARIANT_FIELDS["character"]

#: 锚图的构图。**固定不变** —— 锚之间的差别只该来自这个人本身，
#: 不该来自构图、光线、背景。同一套构图下，两张锚的差别就是两张脸的差别。
ANCHOR_FRAMING = (
    "neutral front-facing bust portrait, head and shoulders only, "
    "even soft frontal lighting, plain mid-grey seamless background, "
    "relaxed neutral expression, no costume detail, no props, no background scene, "
    "sharp facial detail, photographic reference sheet"
)
ANCHOR_NEGATIVE = (
    "full body, costume, armour, weapon, props, scenery, dramatic lighting, "
    "strong shadows, motion, action pose, text, watermark, multiple people"
)


@dataclass
class AnchorResult:
    submitted: int = 0
    skipped_has_anchor: int = 0
    skipped_no_epoch: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    estimated_cost: float | None = None
    requires_confirm: bool = False
    tasks: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "submitted": self.submitted,
            "skipped_has_anchor": self.skipped_has_anchor,
            "skipped_no_epoch": self.skipped_no_epoch,
            "blocked": self.blocked,
            "estimated_cost": self.estimated_cost,
            "requires_confirm": self.requires_confirm,
            "tasks": self.tasks,
        }


def epochs_of(db: Session, entity_id: str, profile_id: str) -> list[AssetEpoch]:
    """这个人在这个圈层下的全部时期，按章节先后。"""
    return list(db.execute(
        select(AssetEpoch).where(
            AssetEpoch.subject_key == entity_id,
            AssetEpoch.world_profile_id == profile_id,
        ).order_by(AssetEpoch.from_chapter_order, AssetEpoch.order_no)
    ).scalars())


def compose_anchor_prompt(epoch: AssetEpoch) -> str:
    """锚图提示词 = 不变项 + 固定构图。

    **不带 variant。** 带上的话，第一期的衣着兵器会渗进后续每一期，
    而那正是该变的部分。锚只回答「这张脸长什么样」。
    """
    inv = epoch.invariant_json or {}
    bits = [str(inv[f]).strip() for f in CHAR_INVARIANT
            if str(inv.get(f) or "").strip()]
    if not bits:
        return ""
    return ", ".join(bits) + ", " + ANCHOR_FRAMING


def enforce_single_anchor(
    db: Session, novel_id: str, profile_id: str,
) -> list[dict[str, Any]]:
    """一个人一个锚。分叉的按最早那一期抹平。

    覆写而不是报警：锚分叉直接导致脸漂，而正确答案没有歧义。
    """
    ents = {
        e.id: e for e in db.execute(
            select(WorldEntity).where(
                WorldEntity.novel_id == novel_id,
                WorldEntity.kind == EntityKind.character,
            )
        ).scalars()
    }
    if not ents:
        return []
    rows = list(db.execute(
        select(AssetEpoch).where(
            AssetEpoch.world_profile_id == profile_id,
            AssetEpoch.entity_id.in_(list(ents)),
        ).order_by(AssetEpoch.subject_key, AssetEpoch.from_chapter_order,
                   AssetEpoch.order_no)
    ).scalars())

    by_entity: dict[str, list[AssetEpoch]] = {}
    for r in rows:
        by_entity.setdefault(r.entity_id, []).append(r)

    fixes: list[dict[str, Any]] = []
    for eid, group in by_entity.items():
        anchor = next((r.identity_ref_asset_id for r in group
                       if r.identity_ref_asset_id), None)
        if not anchor:
            continue
        for r in group:
            if r.identity_ref_asset_id == anchor:
                continue
            was = r.identity_ref_asset_id
            r.identity_ref_asset_id = anchor
            fixes.append({
                "entity": ents[eid].display_name, "epoch": r.epoch_key,
                "detail": (
                    f"「{r.display_name}」用的是"
                    + (f"另一张脸参考（{was}）" if was else "空的脸参考")
                    + "，已改为与最早一期同一张 —— 各期用不同的参考图，"
                      "等于没有参考图"
                ),
            })
    db.flush()
    return fixes


def generate_anchors(
    db: Session, novel_id: str, profile: WorldProfile, *,
    entity_ids: Sequence[str] | None = None, regenerate: bool = False,
    confirm_cost: bool = False, cost_threshold: float = 1.0,
) -> AnchorResult:
    """为每个有时期的角色生成一张脸参考图。

    只提交，不等结果 —— 与素材参考图同一套两段式：
    generate 提交任务，sync 把产图挂回去。
    """
    q = select(WorldEntity).where(
        WorldEntity.novel_id == novel_id,
        WorldEntity.kind == EntityKind.character,
    )
    if entity_ids:
        q = q.where(WorldEntity.id.in_(list(entity_ids)))
    ents = list(db.execute(q).scalars())
    if not ents:
        raise PipelineError("这本书还没有人物实体")

    result = AnchorResult()
    pending: list[tuple[WorldEntity, AssetEpoch, str]] = []
    for ent in ents:
        group = epochs_of(db, ent.id, profile.id)
        if not group:
            result.skipped_no_epoch.append(ent.display_name)
            continue
        if any(r.identity_ref_asset_id for r in group) and not regenerate:
            result.skipped_has_anchor += 1
            continue
        first = group[0]
        prompt = compose_anchor_prompt(first)
        if not prompt:
            # 没有不变项就没有可锚的东西 —— 生成一张也锁不住什么
            result.blocked.append(
                f"{ent.display_name}：时期里没有不变项（骨相五官疤痕都空着），"
                f"锚图无从生成")
            continue
        pending.append((ent, first, prompt))

    if not pending:
        return result

    est = estimate_cost(db, Capability.image_t2i, "identity_ref", len(pending))
    result.estimated_cost = est
    if est is not None and est > cost_threshold and not confirm_cost:
        result.requires_confirm = True
        return result

    for ent, epoch, prompt in pending:
        task = submit_task(
            db, Capability.image_t2i,
            {
                "prompt": prompt,
                "negative_prompt": ANCHOR_NEGATIVE,
                # 方图：锚是头肩像，宽画幅只会填进背景
                "width": 1024, "height": 1024,
                "params": {"seed": None},
            },
            purpose="identity_ref",
            ref_kind="identity_anchor", ref_id=ent.id,
            novel_id=novel_id,
        )
        result.submitted += 1
        result.tasks.append({
            "entity": ent.display_name, "entity_id": ent.id,
            "epoch": epoch.epoch_key, "gen_task_id": task.id,
            "status": task.status.value, "prompt": prompt,
        })
    db.flush()
    return result


def sync_anchors(
    db: Session, novel_id: str, profile: WorldProfile,
) -> dict[str, Any]:
    """把生成好的锚图挂到该角色的**每一期**上。

    挂到每一期而不是只挂第一期 —— resolve_epoch 取到哪一期，
    出图时就从哪一期读锚。只挂第一期的话，中年林凡那一镜取到的锚是空的，
    于是它从文字重新生成一张脸，而那正是要避免的。
    """
    ents = {
        e.id: e for e in db.execute(
            select(WorldEntity).where(
                WorldEntity.novel_id == novel_id,
                WorldEntity.kind == EntityKind.character,
            )
        ).scalars()
    }
    tasks = list(db.execute(
        select(GenTask).where(
            GenTask.ref_kind == "identity_anchor",
            GenTask.ref_id.in_(list(ents)),
            GenTask.status == TaskStatus.succeeded,
        ).order_by(GenTask.finished_at.asc())
    ).scalars()) if ents else []

    anchored, epochs_touched = 0, 0
    pending: list[str] = []
    for task in tasks:
        asset_id = db.execute(
            select(Asset.id).where(Asset.gen_task_id == task.id).limit(1)
        ).scalars().first()
        if not asset_id:
            continue
        group = epochs_of(db, task.ref_id, profile.id)
        if not group:
            continue
        for row in group:
            if row.identity_ref_asset_id == asset_id:
                continue
            row.identity_ref_asset_id = asset_id
            epochs_touched += 1
        anchored += 1

    for eid, ent in ents.items():
        group = epochs_of(db, eid, profile.id)
        if group and not any(r.identity_ref_asset_id for r in group):
            pending.append(ent.display_name)

    fixes = enforce_single_anchor(db, novel_id, profile.id)
    db.flush()
    return {
        "anchored": anchored, "epochs_updated": epochs_touched,
        "still_missing": pending, "rule_fixes": fixes,
    }


def anchor_status(
    db: Session, novel_id: str, profile_id: str,
) -> dict[str, Any]:
    """锚的体检：谁有、谁没有、谁分叉了。"""
    ents = {
        e.id: e for e in db.execute(
            select(WorldEntity).where(
                WorldEntity.novel_id == novel_id,
                WorldEntity.kind == EntityKind.character,
            )
        ).scalars()
    }
    items, issues = [], []
    for eid, ent in ents.items():
        group = epochs_of(db, eid, profile_id)
        if not group:
            continue
        anchors = {r.identity_ref_asset_id for r in group
                   if r.identity_ref_asset_id}
        url = None
        if len(anchors) == 1:
            url = db.execute(
                select(Asset.url).where(Asset.id == next(iter(anchors)))
            ).scalars().first()
        if len(anchors) > 1:
            issues.append({
                "type": "anchor_split", "entity": ent.display_name,
                "detail": "各期用了不同的脸参考图 —— 等于没有参考图",
            })
        elif not anchors:
            issues.append({
                "type": "no_anchor", "entity": ent.display_name,
                "detail": f"{len(group)} 期都没有脸参考图 —— "
                          f"跨期同一性目前只靠文字，而同一段描述生成三次是三张脸",
            })
        items.append({
            "entity_id": eid, "name": ent.display_name,
            "epochs": len(group),
            "anchor_asset_id": next(iter(anchors), None),
            "anchor_url": url,
            "covered": len([r for r in group if r.identity_ref_asset_id]),
        })
    items.sort(key=lambda i: (i["anchor_asset_id"] is not None, i["name"]))
    return {
        "entities": len(items),
        "with_anchor": len([i for i in items if i["anchor_asset_id"]]),
        "items": items, "issues": issues,
    }
