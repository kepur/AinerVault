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
from pathlib import Path
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.capability.schemas import Capability
from app.ids import new_id
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


#: 源文化的族裔词。**本地化时它们出现在不变项里，就是这一步没做映射。**
#:
#: 人物外貌和名物、货币、场所一样属于目标世界观：五元钱要变成
#: five-dollar bill，人也要变成目标世界的人。抽取时读的是中文原文，
#: 模型很自然地写出 East Asian、monolid eyes —— 提示词里其实写了
#: 「族裔按目标圈层写」，但只是请求，没有任何一处检查。
#: 坏蛋实跑：整本七个人的脸都是中国脸，而故事发生在美国，名字叫 Thomas。
_SOURCE_ETHNICITY = (
    "east asian", "asian", "chinese", "japanese", "korean",
    "monolid", "oriental", "han chinese",
    # 肤色词比族裔词更隐蔽：「yellowish skin」不写族裔，
    # 出来的仍是一张东亚面孔，而检查只找族裔词的话一个都抓不到
    "yellowish skin", "yellow skin", "sallow yellow",
    # **骨相比肤色更隐蔽。**
    #
    # 抽取提示词从前明说「脸型骨相可以沿用原文的描写」，于是
    # 不变项里一个族裔词、一个肤色词都没有，检查全绿，
    # 出来的仍是一屋子东亚面孔 —— 因为 small eyes、flat features
    # 描述的本来就是东亚骨相。
    #
    # 坏蛋实跑：谢文东写 small eyes、prominent cheekbones，
    # 李爽写 flat features、small snub nose，而故事发生在美国、
    # 名字叫 Thomas Ashford。
    #
    # 骨相和货币场所一样要做映射：留下的是**戏剧功能**
    #（瘦弱、高瘦、矮胖），换掉的是族裔判据。
    "small eyes", "narrow eyes", "slanted eyes", "epicanthic",
    "flat features", "flat face", "flat nose", "snub nose",
    "flat cheekbones", "high flat cheekbones", "broad flat",
)


def foreign_appearance_terms(text: str, profile: WorldProfile) -> list[str]:
    """不变项里还留着的、与目标圈层不符的族裔词。

    只在目标圈层**不是**东亚时才报 —— 译到日本或中国的作品里
    写 East Asian 完全正确，那不是漏做映射。
    """
    region = str((profile.axes_json or {}).get("region") or "").upper()
    if region in {"CN", "JP", "KR", "TW", "HK", "SG", "VN"}:
        return []
    low = (text or "").lower()
    return [t for t in _SOURCE_ETHNICITY if t in low]


def recast_appearance(text: str, profile: WorldProfile) -> tuple[str, list[str]]:
    """摘掉与目标圈层不符的族裔判据，返回（重铸后的描述, 摘掉的短语）。

    **查出来还要拦得住。** 从前 foreign_appearance_terms 只被一处
    调用，而那一处是出报告的：issues 里如实写着「不变项里还写着
    monolid eyes」，而同一段文字照原样流进锚提示词，脸照出不误。
    查了没拦，和存了没注入是同一类。

    按逗号切开逐段判断，只摘掉出问题的那一段 —— 整段清空会把
    「extremely frail build with visible ribs」这种戏剧信息一起丢掉，
    而那正是这个人物之所以是这个人物的地方。
    """
    if not text:
        return "", []
    kept, dropped = [], []
    for phrase in (p.strip() for p in text.split(",")):
        if not phrase:
            continue
        if foreign_appearance_terms(phrase, profile):
            dropped.append(phrase)
        else:
            kept.append(phrase)
    return ", ".join(kept), dropped


def demonym(profile: WorldProfile) -> str:
    """目标圈层的人**长什么样**，一个词。

    与 era_phrase 分开：那一句说「故事发生在哪」，这一个说「这里的人
    是哪儿的人」。合成一句写过 "early 21st century American man"，
    结果地域被当成人种、年代被当成形容词，两头都不准；
    但完全不写也不行 —— 本地化作品的人物就该是目标世界的人，
    不写的话模型照着原文的中文描述画，出来一屋子中国脸配着 Thomas 这种名字。
    """
    return _DEMONYM.get(str((profile.axes_json or {}).get("region") or "").upper(), "")


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
    # **国籍不是人种。**
    #
    # 原来拼出来是 "early 21st century American man"，而人物不变项里
    # 明明写着 monolid eyes、East Asian。模型把 American 读成了白人，
    # 于是坏蛋的主角出成一个白人少年，而他的译名是 Thomas Chen ——
    # 脸与名字对不上，且这一步是**所有**下游画面的底图。
    #
    # 改成写「所在地」而不是「哪国人」：年代与地域仍然影响发型、
    # 穿着、气质，而长相由不变项自己说了算。
    if not who:
        return era
    article = "an" if who[0] in "AEIOU" else "a"
    return f"set in {article} {who} city{f', {era}' if era else ''}"


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
    who = demonym(profile) if profile is not None else ""
    specifics = ", ".join(dict.fromkeys(x for x in (age, who, era, wardrobe) if x))
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
    # Contact sheets are for human review; model inputs use one viewpoint.
    order = (preferred, *tail)
    for key in order:
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
    #: 出完立刻挂回各期的结果。为空表示这一轮没提交任何锚
    synced: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "submitted": self.submitted,
            "skipped_has_anchor": self.skipped_has_anchor,
            "skipped_no_epoch": self.skipped_no_epoch,
            "blocked": self.blocked,
            "estimated_cost": self.estimated_cost,
            "requires_confirm": self.requires_confirm,
            "tasks": self.tasks,
            "synced": self.synced,
        }


@dataclass
class CharacterReferenceResult:
    submitted: int = 0
    skipped: int = 0
    blocked: list[str] = field(default_factory=list)
    estimated_cost: float | None = None
    requires_confirm: bool = False
    tasks: list[dict[str, Any]] = field(default_factory=list)
    #: 上游换过、这一轮要重出的。非空说明有参考图曾经与锚脱节
    stale: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "submitted": self.submitted, "skipped": self.skipped,
            "blocked": self.blocked, "stale": self.stale,
            "estimated_cost": self.estimated_cost,
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
    if profile is not None:
        en = recast_appearance(en, profile)[0]
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
    # 年代地域**排在人之后**。它说的是故事发生在哪，不是这个人是哪国人 ——
    # 贴在性别词前面就成了「late 19th century Russian man」，
    # 模型把地域读成人种，于是不变项里写着 monolid eyes 的少年
    # 出成了一个白人。人先说完，再说他站在什么年代的什么城市。
    # 族裔贴在性别词上：American man / American woman。
    # 这是**本地化的一部分**，跟货币场所一样 —— 不写的话模型照着
    # 原文的中文外貌描述画，出来一屋子中国脸配着 Thomas 这种名字。
    who = demonym(profile) if profile is not None else ""
    person = " ".join(x for x in (who, noun) if x)
    parts = [p for p in (age, person, en, era) if p]
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
    # **出完就挂上。**
    #
    # 「generate 提交、sync 挂回」这套两段式是为异步供应商准备的，
    # 而同步方言（百炼出图是同步的）在 submit_task 返回时图就已经在库里。
    # 于是漏跑一次 sync 的代价是：七张锚图全都有，
    # 每一期的 identity_ref_asset_id 仍然是空 —— 下一步「扩成正面全身参考」
    # 七个人全部报「先生成身份锚」，而锚明明就在那儿。
    # sync 幂等，同步路径上多跑一次不花钱。
    if result.submitted:
        result.synced = sync_anchors(db, novel_id, profile)
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
            # **锚换了，从旧锚派生的参考图就作废。**
            #
            # 每张视角图都记着 source_asset_id（它是从哪张图派生的），
            # 但从来没有人读过它 —— 又一处「存了没用」。
            # 后果实测过：坏蛋的正面参考 12:06 从旧锚派生，
            # 12:14 锚被重出（旧锚把亚裔主角画成了白人），
            # 于是每一期的 identity_ref_asset_id 指向新脸，
            # 而 views.front 里还是那张白人全身像。
            # 再往下所有引用这个人的镜头都会拿到两张脸，
            # 而这一步只会报「skipped: 7」，看着像一切正常。
            stale_front = bool(
                front_id and epoch.identity_ref_asset_id
                and front_item.get("source_asset_id") != epoch.identity_ref_asset_id
            )
            if stale_front:
                result.stale.append(
                    f"{ent.display_name}／{epoch.display_name}／正面全身："
                    "身份锚换过了，这张是从旧锚派生的，重出")
            needs_front = "front" in requested and (
                regenerate or not front_id or stale_front)
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
                # 派生视角的上游是正面图，同一条判据：正面换了就得重出
                stale_view = bool(
                    current.get("asset_id") and front_id
                    and current.get("source_asset_id") != front_id
                )
                if stale_view:
                    result.stale.append(
                        f"{ent.display_name}／{epoch.display_name}／"
                        f"{REFERENCE_VIEW_CN[view]}：正面参考换过了，重出")
                if current.get("asset_id") and not regenerate and not stale_view:
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



#: 三要素合成图在参考集里的键。**不在 CHARACTER_REFERENCE_VIEWS 里** ——
#: 那张表驱动「要向模型要几张图」，而这一张是本地拼的，一次调用都不花。
SHEET_VIEW = "sheet"

#: 拼图上每一格的标注。写英文 —— 这张图会作为参考图送给出图模型，
#: 中文标注在它眼里是汉字纹样
SHEET_LABELS = {
    "front": "FRONT / OUTFIT",
    "three_quarter_left": "3/4 LEFT",
    "profile_left": "PROFILE",
    "bust": "FACE",
}
#: 拼图顺序。正面在最左 —— 它带着全身与服饰，是这一期的权威
SHEET_ORDER = ("front", "three_quarter_left", "profile_left", "bust")
_SHEET_H = 1152          # 每格统一高度
_SHEET_PAD = 16
_SHEET_BG = (200, 200, 202)   # 与各视角的中灰底一致，拼缝不显眼


def compose_reference_sheet(db: Session, epoch: AssetEpoch) -> str | None:
    """把已有的几张视角图拼成**一张**人物设定图，返回新 asset 的 id。

    ## 为什么要有这一张

    分镜取参考图时，一个人物只占一个参考位 —— 四张分开存，就只有一张
    会被选中，模型看不到另外三张。正面那张里的服饰、侧脸那张里的轮廓，
    到了实际出图时都不在场，于是同一个人在不同镜头之间**漂**：
    这一镜的外套长一点，下一镜的下巴尖一点，每一张单看都合理。

    拼成一张之后，模型在同一个参考位上同时看到正面、服饰、侧脸与面部特写，
    约束是完整的。这也是设定集本来的样子 —— 人物三视图从来都画在一张纸上。

    ## 为什么不用模型拼

    **本地拼，一次调用都不花。** 图都已经在库里了，让模型「再画一张
    包含四个角度的图」不但要花额度，画出来的还是四个新的人 ——
    它不会去抄，它会去创作。

    没有任何一张视角图时返回 None；缺几张就拼几张（缺正面也照拼，
    有总比没有强），但会把实际拼进去的记进 meta，方便回查。
    """
    from io import BytesIO

    from PIL import Image, ImageDraw

    from app.capability import mediastore
    from app.models import Asset, AssetKind, AssetSource

    views = dict((epoch.reference_set_json or {}).get("views") or {})
    tiles: list[tuple[str, "Image.Image"]] = []
    for key in SHEET_ORDER:
        item = views.get(key)
        if not isinstance(item, dict) or not item.get("asset_id"):
            continue
        asset = db.get(Asset, str(item["asset_id"]))
        path = _local_path(asset)
        if path is None:
            continue
        try:
            img = Image.open(path).convert("RGB")
        except Exception as exc:            # 坏图不该让整张拼图失败
            log.warning("参考图打不开 %s：%s", path, exc)
            continue
        w = max(1, round(img.width * _SHEET_H / img.height))
        tiles.append((key, img.resize((w, _SHEET_H), Image.LANCZOS)))
    if not tiles:
        return None

    total_w = sum(t.width for _, t in tiles) + _SHEET_PAD * (len(tiles) + 1)
    sheet = Image.new("RGB", (total_w, _SHEET_H + _SHEET_PAD * 2), _SHEET_BG)
    draw = ImageDraw.Draw(sheet)
    x = _SHEET_PAD
    for key, tile in tiles:
        sheet.paste(tile, (x, _SHEET_PAD))
        draw.text((x + 8, _SHEET_PAD + 6), SHEET_LABELS.get(key, key),
                  fill=(90, 90, 92))
        x += tile.width + _SHEET_PAD

    buf = BytesIO()
    sheet.save(buf, format="JPEG", quality=92)
    item = mediastore.store_bytes(buf.getvalue(), mime="image/jpeg")

    existing = db.execute(
        select(Asset).where(Asset.sha256 == item.get("sha256"))
    ).scalars().first()
    if existing is None:
        existing = Asset(
            id=new_id("as"), kind=AssetKind.image, url=item["url"],
            sha256=item.get("sha256"), mime=item.get("mime"),
            bytes=item.get("bytes"), source=AssetSource.generated,
            novel_id=None,
            meta_json={"composed": "character_reference_sheet",
                       "views": [k for k, _ in tiles]},
        )
        db.add(existing)
        db.flush()

    doc = _reference_doc(epoch)
    doc["views"][SHEET_VIEW] = {
        "asset_id": existing.id,
        "views": [k for k, _ in tiles],
        # 上游是这几张视角图；其中任何一张换了，这张拼图就该重拼
        "source_asset_id": ",".join(
            str(views[k].get("asset_id")) for k, _ in tiles),
        "status": "ready",
    }
    epoch.reference_set_json = doc
    flag_modified(epoch, "reference_set_json")
    return existing.id


def _local_path(asset: "Asset | None") -> "Path | None":
    """asset 的本地文件路径。拼图要读像素，读不到 URL 只能读盘。"""
    from app.capability import mediastore

    if asset is None or not asset.url:
        return None
    name = str(asset.url).rsplit("/", 1)[-1]
    path = mediastore.media_root() / name
    return path if path.exists() else None

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
    profile = db.get(WorldProfile, profile_id)
    items: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    complete = 0
    epoch_total = 0
    for eid, ent in entities.items():
        epoch_items = []
        for epoch in epochs_of(db, eid, profile_id):
            epoch_total += 1
            # 人物外貌和名物、货币、场所一样属于目标世界观 ——
            # 五元钱要变成 five-dollar bill，人也要变成目标世界的人。
            # 抽取读的是中文原文，模型很自然写出 East Asian、monolid；
            # 提示词里写了「族裔按目标圈层写」，但只是请求，没人检查。
            # 不报的话结果是一屋子中国脸配着 Thomas 这种名字，
            # 而每一步都显示成功。
            stray = (foreign_appearance_terms(
                str((epoch.invariant_json or {}).get(EN_KEY) or ""), profile)
                if profile is not None else [])
            if stray:
                issues.append({
                    "type": "unmapped_appearance",
                    "entity": ent.display_name, "epoch": epoch.epoch_key,
                    "found": stray,
                    "detail": f"不变项里还写着「{'、'.join(stray)}」，"
                              f"而目标圈层是{profile.display_name} —— "
                              f"外貌这一层没做世界观映射，"
                              f"出来的脸会与译名和场景对不上",
                })
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
        "items": items, "issues": issues,
        "not_checked": ([] if epoch_total else ["还没有人物时期，无法建立三要素与三视角参考集"]),
    }
