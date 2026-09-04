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
import re
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
from app.pipelines.base import PipelineError, checkpoint
from app.pipelines.entity_epochs import AGE_EN_KEY, EN_KEY

log = logging.getLogger(__name__)

CHAR_INVARIANT = INVARIANT_FIELDS["character"]

#: 地区代码 → 英文族裔词。圈层档案的 axes.region 是机读的 ISO 码，
#: 拼成英文不需要问模型 —— 规则能算准的就不该花一次调用。
_DEMONYM = {
    "RU": "Russian", "GB": "British", "UK": "British", "US": "American",
    "FR": "French", "DE": "German", "JP": "Japanese", "CN": "Chinese",
    "KR": "Korean", "IN": "Indian", "ES": "Spanish", "MX": "Mexican",
    "BR": "Brazilian", "PT": "Portuguese", "IT": "Italian", "SA": "Arab",
    "EG": "Egyptian", "TR": "Turkish", "BD": "Bengali", "VN": "Vietnamese",
}


def _ordinal(n: int) -> str:
    """1 → 1st，21 → 21st。硬拼 "th" 会写出 21th ——
    它出现在每一张身份锚与人物参考的提示词里，
    图像模型对一个不存在的词只能瞎猜年代。
    """
    if 11 <= n % 100 <= 13:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def era_phrase(profile: WorldProfile) -> str:
    """圈层 → 一句英文的年代族裔。

    「帝俄晚期」在提示词里必须写成 late 19th century Russian ——
    图像模型不认中文，也不认 ru_imperial 这种内部代码。
    取区间中点定世纪与前后半段：1855–1917 的中点 1886 落在 19 世纪后半。
    """
    axes = profile.axes_json or {}
    who = _DEMONYM.get(str(axes.get("region") or "").upper(), "")
    span = axes.get("era_span")
    era = ""
    if isinstance(span, list) and len(span) == 2:
        try:
            mid = (int(span[0]) + int(span[1])) // 2
        except (TypeError, ValueError):
            mid = 0
        if mid:
            century = mid // 100 + 1
            half = "early" if mid % 100 < 34 else (
                "mid" if mid % 100 < 67 else "late")
            era = f"{half} {_ordinal(century)} century"
    return " ".join(x for x in (era, who) if x)


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

#: 参考集每张单独生成、单独引用，而不是九宫格拼贴 ——
#: 拼成一张图，模型不知道该抄里面哪一个人。
#:
#: 视角分两个轴，缺哪个轴都会漏一类镜头：
#:   **朝向**  正面／左前四分之三／左侧面。镜头人物朝哪边，就引哪一张。
#:   **景别**  近景另有一张头肩像。三张全身参考在特写里等于没有 ——
#:             脸只占参考图的百分之几，模型只能自己把五官放大重画，
#:             于是全片最该认得出人的那几个镜头恰恰最不像。
#:
#: 顺序即优先级：额度有限时先出前三张，头肩像排在严格侧面之前 ——
#: 特写比正侧面常见得多。
CHARACTER_REFERENCE_VIEWS = (
    "front", "three_quarter_left", "bust", "profile_left",
)
REFERENCE_VIEW_CN = {
    "front": "正面全身",
    "three_quarter_left": "左前四分之三",
    "bust": "头肩近景",
    "profile_left": "左侧面",
}
REFERENCE_REF_KINDS = {
    "front": "character_ref_front",
    "three_quarter_left": "character_ref_3q_left",
    "bust": "character_ref_bust",
    "profile_left": "character_ref_profile_left",
}

#: 引用头肩像的景别。特写与大特写画的是脸，全身参考帮不上忙
CLOSE_SHOT_SIZES = frozenset({"ecu", "cu"})
REF_KIND_TO_VIEW = {v: k for k, v in REFERENCE_REF_KINDS.items()}
CHARACTER_REFERENCE_NEGATIVE = (
    "different person, changed facial identity, changed body proportions, "
    "changed hairstyle, changed wardrobe, changed accessories, action pose, "
    "dramatic perspective, dramatic lighting, cropped feet, collage, split screen, "
    "multiple views, multiple people, text, labels, watermark"
)

_IDENTITY_CN = ("sex", "face_shape", "features", "eye_color", "skin_tone", "scars")
_SILHOUETTE_CN = ("build", "height", "age_look", "bearing")
_WARDROBE_CN = ("hair", "facial_hair", "garments", "accessories", "carried", "condition")


def _fields_text(data: dict[str, Any], fields: Sequence[str]) -> str:
    return "；".join(str(data.get(k) or "").strip() for k in fields
                     if str(data.get(k) or "").strip())


def reference_elements(epoch: AssetEpoch) -> dict[str, dict[str, str]]:
    """把时期字段整理成可审核的三要素，中英各一份。

    旧数据只有两条英文权威：invariant._en 与 variant._en。没有凭空拆词；
    `identity` 保留前者，`wardrobe` 保留后者，silhouette 的英文在旧数据中
    只能诚实标成复用不变项与年龄。下一次重划时期仍可无损升级结构。
    """
    inv = dict(epoch.invariant_json or {})
    var = dict(epoch.variant_json or {})
    inv_en = str(inv.get(EN_KEY) or "").strip()
    var_en = str(var.get(EN_KEY) or "").strip()
    age_en = str(var.get(AGE_EN_KEY) or "").strip()
    return {
        "identity": {
            "cn": _fields_text(inv, _IDENTITY_CN),
            "en": inv_en,
        },
        "silhouette": {
            "cn": _fields_text({**inv, **var}, _SILHOUETTE_CN),
            "en": ", ".join(dict.fromkeys(x for x in (age_en, inv_en) if x)),
        },
        "wardrobe": {
            "cn": _fields_text(var, _WARDROBE_CN),
            "en": var_en,
        },
    }


def compose_character_reference_prompt(
    epoch: AssetEpoch, profile: WorldProfile | None, view: str,
) -> str:
    """三视角提示词。

    正面图从素颜身份锚扩成这一时期的完整人物，因此只补身体、发型、衣着；
    两张转角图则只说“转到这个角度”，不重新描述人物。这沿用了
    Higgsfield 的关键纪律：参考图负责静态身份，i2v/i2i 提示只写变化。
    """
    if view not in CHARACTER_REFERENCE_VIEWS:
        raise ValueError(f"unknown character reference view: {view}")
    if view == "bust":
        # 近景参考不是把全身图裁一刀，是**重新取景**：
        # 裁出来的脸只有几十个像素，放大回去还是糊的。
        return (
            "Reframe the exact same character from the input reference as a "
            "head-and-shoulders portrait, chest up, filling the frame. "
            "Preserve the exact facial identity, apparent age, hairstyle, "
            "hairline, facial hair, skin tone and the collar, neckline and "
            "accessories of the same outfit. Neutral expression, head straight "
            "to camera, eye-level 85mm portrait photography, even soft neutral "
            "lighting, plain mid-grey seamless background, "
            "sharp skin texture and pores, no retouching."
        )
    if view != "front":
        angle = {
            "three_quarter_left": "a left three-quarter view (about 45 degrees)",
            "profile_left": "a strict left profile view (about 90 degrees)",
        }[view]
        return (
            f"Rotate the exact same character from the input reference to {angle}. "
            "Preserve the exact facial identity, body proportions, apparent age, "
            "hairstyle, wardrobe, accessories, footwear, materials and colors. "
            "Neutral relaxed standing pose, arms naturally separated from the torso, "
            "full body from head to feet, eye-level 85mm reference photography, "
            "even soft neutral lighting, plain mid-grey seamless background, sharp detail."
        )

    var = dict(epoch.variant_json or {})
    wardrobe = str(var.get(EN_KEY) or "").strip()
    age = str(var.get(AGE_EN_KEY) or "").strip()
    era = era_phrase(profile) if profile is not None else ""
    specifics = ", ".join(dict.fromkeys(x for x in (age, era, wardrobe) if x))
    if not specifics:
        return ""
    return (
        "Create a full-body front-view character model reference of the exact same "
        "person shown in the input identity portrait. Preserve the exact facial identity. "
        f"Apply only this period-specific body, hair and wardrobe design: {specifics}. "
        "Neutral relaxed standing pose, arms naturally separated from the torso, "
        "full body from head to feet, eye-level 85mm reference photography, "
        "even soft neutral lighting, plain mid-grey seamless background, sharp material detail."
    )


def preferred_reference_view(facing: str | None, shot_size: str | None = None) -> str:
    """(朝向, 景别) → 参考集里的具体一张。右侧面允许镜像使用左侧面。

    **景别先判。** 特写画的是脸，给它一张全身参考等于没给 ——
    脸只占参考图的百分之几，模型只能自己把五官放大重画，
    于是全片最该认得出人的那几个镜头恰恰最不像。
    """
    if str(shot_size or "") in CLOSE_SHOT_SIZES:
        return "bust"
    return {
        "to_camera": "front",
        "three_quarter": "three_quarter_left",
        "profile_left": "profile_left",
        "profile_right": "profile_left",
        "away": "three_quarter_left",
    }.get(str(facing or ""), "three_quarter_left")


def character_reference_asset_id(
    epoch: AssetEpoch, facing: str | None, shot_size: str | None = None,
) -> str | None:
    views = dict((epoch.reference_set_json or {}).get("views") or {})
    preferred = preferred_reference_view(facing, shot_size)
    # 回落顺序也随景别走：近景没有头肩像时宁可用正面，
    # 也不要一张侧身全身 —— 那张连脸都不完整
    tail = (("front", "three_quarter_left", "profile_left")
            if preferred == "bust"
            else ("three_quarter_left", "front", "bust", "profile_left"))
    for key in (preferred, *tail):
        item = views.get(key)
        if isinstance(item, dict) and item.get("asset_id"):
            return str(item["asset_id"])
    return None


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


@dataclass
class CharacterReferenceResult:
    submitted: int = 0
    skipped: int = 0
    blocked: list[str] = field(default_factory=list)
    estimated_cost: float | None = None
    requires_confirm: bool = False
    tasks: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "submitted": self.submitted, "skipped": self.skipped,
            "blocked": self.blocked, "estimated_cost": self.estimated_cost,
            "requires_confirm": self.requires_confirm, "tasks": self.tasks,
        }


def epochs_of(db: Session, entity_id: str, profile_id: str) -> list[AssetEpoch]:
    """这个人在这个圈层下的全部时期，按章节先后。"""
    return list(db.execute(
        select(AssetEpoch).where(
            AssetEpoch.subject_key == entity_id,
            AssetEpoch.world_profile_id == profile_id,
        ).order_by(AssetEpoch.from_chapter_order, AssetEpoch.order_no)
    ).scalars())


_SEX_NOUN = {"male": "man", "female": "woman", "child": "child"}


def compose_anchor_prompt(epoch: AssetEpoch,
                          profile: WorldProfile | None = None) -> str:
    """锚图提示词 = 不变项（英文）+ 固定构图。

    **必须是英文。** 实跑时把中文外貌描述直接喂给 SDXL，
    出来的是一整版汉字纹样 —— 一张脸都没有。
    图像模型不认中文，而中文那几项是给人审核用的。

    **不带 variant。** 带上的话，第一期的衣着兵器会渗进后续每一期，
    而那正是该变的部分。锚只回答「这张脸长什么样」。
    """
    inv = epoch.invariant_json or {}
    en = str(inv.get(EN_KEY) or "").strip()
    if not en:
        return ""
    # 性别与年代族裔排最前。都不是「脸的特征」，但少了任何一个，
    # 模型会自己挑一个 —— 实跑时沈砚（男，帝俄晚期）出来是张现代女性的脸
    age = str((epoch.variant_json or {}).get(AGE_EN_KEY) or "").strip()
    era = era_phrase(profile) if profile is not None else ""
    noun = _SEX_NOUN.get(str(inv.get("sex") or "").strip().lower(), "")
    # 年龄短语常常自带 man／woman（「man in his late fifties」），
    # 再补一个就成了「man in his late fifties, ... Russian man」。
    # 重复对模型无害，但读起来像没校对过 —— 而这段提示词是要给人看的
    if noun and re.search(rf"\b{noun}\b", age, re.I):
        noun = ""
    lead = " ".join(x for x in (era, noun) if x)
    parts = [p for p in (age, lead, en) if p]
    return ", ".join(parts) + ", " + ANCHOR_FRAMING


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
        prompt = compose_anchor_prompt(first, profile)
        if not prompt:
            # 没有不变项就没有可锚的东西 —— 生成一张也锁不住什么
            result.blocked.append(
                f"{ent.display_name}：时期里没有英文不变项 —— "
                f"图像模型不认中文（喂中文出来的是汉字纹样不是脸），"
                f"重跑一次「划分时期」补上 invariant_en")
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


def _asset_url(db: Session, asset_id: str | None) -> str | None:
    if not asset_id:
        return None
    return db.execute(
        select(Asset.url).where(Asset.id == asset_id)
    ).scalars().first()


def _reference_doc(epoch: AssetEpoch) -> dict[str, Any]:
    current = dict(epoch.reference_set_json or {})
    current["elements"] = reference_elements(epoch)
    current["views"] = dict(current.get("views") or {})
    return current


def generate_character_references(
    db: Session, novel_id: str, profile: WorldProfile, *,
    entity_ids: Sequence[str] | None = None,
    views: Sequence[str] | None = None,
    regenerate: bool = False,
    confirm_cost: bool = False,
    cost_threshold: float = 1.0,
) -> CharacterReferenceResult:
    """从脸锚顺序派生每一期的三视角人物参考。

    一次调用只推进一个依赖层：没有正面图时先做正面；正面落地后再做两个
    转角。不能在同一批里让侧面引用一个尚未产生的 URL。
    """
    requested = tuple(dict.fromkeys(views or CHARACTER_REFERENCE_VIEWS))
    bad = [v for v in requested if v not in CHARACTER_REFERENCE_VIEWS]
    if bad:
        raise PipelineError(f"未知人物参考视角：{'、'.join(bad)}")

    q = select(WorldEntity).where(
        WorldEntity.novel_id == novel_id,
        WorldEntity.kind == EntityKind.character,
    )
    if entity_ids:
        q = q.where(WorldEntity.id.in_(list(entity_ids)))
    entities = list(db.execute(q).scalars())
    if not entities:
        raise PipelineError("这本书还没有人物实体")

    result = CharacterReferenceResult()
    pending: list[tuple[WorldEntity, AssetEpoch, str, str, str]] = []
    for ent in entities:
        epochs = epochs_of(db, ent.id, profile.id)
        if not epochs:
            result.blocked.append(f"{ent.display_name}：还没有人物时期")
            continue
        for epoch in epochs:
            ref_doc = _reference_doc(epoch)
            view_doc = ref_doc["views"]
            epoch.reference_set_json = ref_doc

            # 正面是这一期身体/服装的权威；任何派生视角都必须从它出发。
            front_item = view_doc.get("front") if isinstance(
                view_doc.get("front"), dict) else {}
            front_id = str(front_item.get("asset_id") or "")
            needs_front = "front" in requested and (regenerate or not front_id)
            if needs_front:
                anchor_url = _asset_url(db, epoch.identity_ref_asset_id)
                prompt = compose_character_reference_prompt(epoch, profile, "front")
                if not anchor_url:
                    result.blocked.append(
                        f"{ent.display_name}／{epoch.display_name}：先生成身份锚，再扩成正面全身参考")
                elif not prompt:
                    result.blocked.append(
                        f"{ent.display_name}／{epoch.display_name}：缺英文时期外观，不能交给图像模型猜")
                else:
                    pending.append((ent, epoch, "front", anchor_url, prompt))
                # 这一轮即使有旧 front，重出时也不能让侧面继续从旧版派生。
                for view in requested:
                    if view != "front":
                        result.blocked.append(
                            f"{ent.display_name}／{epoch.display_name}／{REFERENCE_VIEW_CN[view]}："
                            "等待本轮正面参考落地后再派生")
                continue

            if "front" in requested and front_id:
                result.skipped += 1
            front_url = _asset_url(db, front_id)
            for view in requested:
                if view == "front":
                    continue
                current = view_doc.get(view) if isinstance(view_doc.get(view), dict) else {}
                if current.get("asset_id") and not regenerate:
                    result.skipped += 1
                    continue
                if not front_url:
                    result.blocked.append(
                        f"{ent.display_name}／{epoch.display_name}／{REFERENCE_VIEW_CN[view]}："
                        "正面全身参考还没落地")
                    continue
                pending.append((
                    ent, epoch, view, front_url,
                    compose_character_reference_prompt(epoch, profile, view),
                ))

    if not pending:
        db.flush()
        return result
    est = estimate_cost(
        db, Capability.image_i2i, "character_reference", len(pending))
    result.estimated_cost = est
    if est is not None and est > cost_threshold and not confirm_cost:
        result.requires_confirm = True
        return result

    for ent, epoch, view, source_url, prompt in pending:
        task = submit_task(
            db, Capability.image_i2i,
            {
                "image": {"url": source_url},
                "prompt": prompt,
                "negative_prompt": CHARACTER_REFERENCE_NEGATIVE,
                "strength": 0.68 if view == "front" else 0.42,
                "width": 1024, "height": 1536,
                "params": {"seed": None},
            },
            purpose="character_reference",
            ref_kind=REFERENCE_REF_KINDS[view], ref_id=epoch.id,
            novel_id=novel_id, force=regenerate, max_cost=0.0,
        )
        # 同步方言会在 submit_task 内立刻把 asset_id 回挂；从更新后的对象再取，
        # 不能用调用前的旧字典覆盖掉回挂结果。
        ref_doc = _reference_doc(epoch)
        current = dict(ref_doc["views"].get(view) or {})
        current.update({
            "prompt_en": prompt,
            "source_asset_id": (epoch.identity_ref_asset_id if view == "front"
                                else ref_doc["views"].get("front", {}).get("asset_id")),
            "gen_task_id": task.id,
            "status": task.status.value,
        })
        ref_doc["views"][view] = current
        epoch.reference_set_json = ref_doc
        result.submitted += 1
        result.tasks.append({
            "entity": ent.display_name, "entity_id": ent.id,
            "epoch": epoch.epoch_key, "epoch_id": epoch.id,
            "view": view, "gen_task_id": task.id, "status": task.status.value,
        })
        checkpoint(db)
    db.flush()
    return result


def character_reference_status(
    db: Session, novel_id: str, profile_id: str,
) -> dict[str, Any]:
    entities = {
        e.id: e for e in db.execute(
            select(WorldEntity).where(
                WorldEntity.novel_id == novel_id,
                WorldEntity.kind == EntityKind.character,
            )
        ).scalars()
    }
    items: list[dict[str, Any]] = []
    complete = 0
    epoch_total = 0
    for eid, ent in entities.items():
        epoch_items = []
        for epoch in epochs_of(db, eid, profile_id):
            epoch_total += 1
            doc = _reference_doc(epoch)
            views_out: dict[str, Any] = {}
            ready = 0
            for view in CHARACTER_REFERENCE_VIEWS:
                v = dict(doc["views"].get(view) or {})
                aid = str(v.get("asset_id") or "") or None
                url = _asset_url(db, aid)
                if url:
                    ready += 1
                views_out[view] = {
                    **v, "label": REFERENCE_VIEW_CN[view],
                    "asset_id": aid, "url": url,
                }
            is_complete = ready == len(CHARACTER_REFERENCE_VIEWS)
            complete += int(is_complete)
            epoch_items.append({
                "epoch_id": epoch.id, "epoch_key": epoch.epoch_key,
                "display_name": epoch.display_name,
                "elements": doc["elements"], "views": views_out,
                "ready_views": ready, "complete": is_complete,
            })
        if epoch_items:
            items.append({
                "entity_id": eid, "name": ent.display_name,
                "epochs": epoch_items,
                "complete": all(e["complete"] for e in epoch_items),
            })
    items.sort(key=lambda x: x["name"])
    return {
        "views_required": list(CHARACTER_REFERENCE_VIEWS),
        "epoch_sets": epoch_total, "complete_sets": complete,
        "items": items,
        "not_checked": ([] if epoch_total else ["还没有人物时期，无法建立三要素与三视角参考集"]),
    }
