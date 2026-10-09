"""素材卡：从翻译系统的世界素材组出有限、标准化的卡片（planA.md 4.1）。

人：世界实体 + 本章那一期的造型（参考集各视角）+ 译名（entity_world_names）+ 物理尺寸。
地点：场次的地点文字 + 资产库里定好的场景图（shot_location，和关键帧、白模用的是同一张）。
道具：分镜调度表里还没有结构化的道具，P6 再补。

物理尺寸的来源按优先级：人改过的（存在这一期参考集的 reference_set_json["physical"]，不用加列）
> 从外貌描写里推断（「瘦高」「矮胖」「teenage girl」）> 按性别和年龄给默认值。
身高决定舞台里人偶的大小：两个人同框时的高矮差由舞台算出来，不靠提示词描述。
"""
from __future__ import annotations

import re
from typing import Any, Iterable

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.stage.schema import AssetCard, Physical

# ── 物理尺寸推断（纯函数） ────────────────────────────────────────────────────

_FEMALE = re.compile(r"\b(woman|women|girl|female|lady|her|she|mother|mom)\b|她|女|姑娘|母亲|妈妈", re.I)
_CHILD = re.compile(r"\b(child|kid|little boy|little girl|toddler)\b|孩子|小孩|儿童|幼", re.I)
_TEEN = re.compile(r"\b(teen\w*|adolescent|mid[- ]teens|late teens|high school|schoolboy|schoolgirl)\b|少年|少女|中学|高中|初中", re.I)
_OLD = re.compile(r"\b(elderly|old man|old woman|grandfather|grandmother|aged)\b|老人|老头|老太|爷爷|奶奶", re.I)
_TALL = re.compile(r"\b(tall|lanky|towering|long[- ]legged)\b|高个|高大|瘦高|个子高|大高个", re.I)
# 「short chin」「short hair」「thin eyebrows」说的是五官和发型，不是身材
_FEATURE = r"(?![- ]?\s*(?:chin|hair|haired|sleeve\w*|neck|nose|skirt|pants|jacket|eyebrows?|brows?|lips?|mustache|beard|fingers?))"
_SHORT = re.compile(r"\b(short stature|short" + _FEATURE + r"|petite|small[- ]framed|tiny)\b|矮|个子小|娇小", re.I)
_STOUT = re.compile(r"\b(stout|chubby|plump|fat|heavyset|protruding belly|pot[- ]bellied|overweight)\b|胖|壮实|肥", re.I)
_SLIM = re.compile(r"\b(skinny|thin" + _FEATURE + r"|slender|slim|frail|bony|visible ribs)\b|瘦弱|瘦小|纤细|单薄|瘦", re.I)
_ATHLETIC = re.compile(r"\b(muscular|athletic|broad[- ]shouldered|well[- ]built|brawny)\b|健壮|魁梧|结实|肌肉", re.I)

#: 默认身高（米）：(性别, 年龄段)
_BASE = {("m", "adult"): 1.75, ("f", "adult"): 1.63, ("m", "teen"): 1.70, ("f", "teen"): 1.60,
         ("m", "child"): 1.30, ("f", "child"): 1.28, ("m", "old"): 1.70, ("f", "old"): 1.58}


def infer_physical(*texts: str | None) -> Physical:
    """从外貌词估算尺寸，来源为 inferred；无命中为 default，均非实测值。"""
    t = " ".join(x for x in texts if x)
    sex = "f" if _FEMALE.search(t) else "m"
    age = "child" if _CHILD.search(t) else "teen" if _TEEN.search(t) else "old" if _OLD.search(t) else "adult"
    h = _BASE[(sex, age)]
    build = None
    hit = False
    if _TALL.search(t):
        h, hit = h + 0.10, True
        build = "lanky" if _SLIM.search(t) or re.search(r"lanky|瘦高", t, re.I) else None
    elif _SHORT.search(t):
        h, hit = h - 0.08, True
    if _STOUT.search(t):
        build, hit = "stout", True
    elif _ATHLETIC.search(t):
        build, hit = "athletic", True
    elif build is None and _SLIM.search(t):
        build, hit = "slim", True
    return Physical(height_m=round(h, 2), build=build or "average", source="inferred" if hit else "default")


# ── 从库里组卡片 ─────────────────────────────────────────────────────────────

def _screen_names(db: Session, transform_id: str | None, ids: list[str]) -> dict[str, str]:
    if not transform_id or not ids:
        return {}
    rows = db.execute(text("select entity_id, target_name from core.entity_world_names "
                           "where transform_id = :t and entity_id = any(:ids)"), {"t": transform_id, "ids": ids}).all()
    return {e: n for e, n in rows if n}


def _urls(db: Session, asset_ids: Iterable[str]) -> dict[str, str]:
    from app.models import Asset

    ids = [a for a in asset_ids if a]
    if not ids:
        return {}
    return {a.id: a.url for a in db.execute(select(Asset).where(Asset.id.in_(ids))).scalars()}


def scene_people(db: Session, shots: list[Any]) -> list[str]:
    """这几镜里出场的人（调度表 + 首帧登记 + 说台词的），按第一次出场排。"""
    from app.models import AudioKind, AudioSpec, FrameRole, FrameSpec, ShotPerformance

    out: list[str] = []
    for s in sorted(shots, key=lambda x: x.order_no):
        out += [p.entity_id for p in db.execute(select(ShotPerformance).where(ShotPerformance.shot_id == s.id)).scalars()]
        fs = db.execute(select(FrameSpec).where(FrameSpec.shot_id == s.id, FrameSpec.role == FrameRole.first)).scalars().first()
        out += list((fs.entity_ids_json or []) if fs else [])
        out += [a.entity_id for a in db.execute(select(AudioSpec).where(AudioSpec.shot_id == s.id,
                                                                        AudioSpec.kind == AudioKind.dialogue)).scalars()]
    return [e for e in dict.fromkeys(out) if e]


def character_card(db: Session, entity_id: str, *, profile_id: str | None, chapter_order: int | None,
                   screen_name: str | None = None) -> AssetCard | None:
    from app.models import WorldEntity
    from app.pipelines.epochs import resolve_epoch
    from app.pipelines.identity import reference_elements
    from app.pipelines.ltx25_shots import appearance

    ent = db.get(WorldEntity, entity_id)
    if ent is None:
        return None
    epoch = resolve_epoch(db, entity_id, profile_id, chapter_order) if profile_id else None
    ref = (epoch.reference_set_json or {}) if epoch else {}
    vids = {k: v.get("asset_id") for k, v in (ref.get("views") or {}).items() if isinstance(v, dict) and v.get("asset_id")}
    urls = _urls(db, vids.values())
    views = {k: urls[a] for k, a in vids.items() if a in urls}
    # 标准定妆照的 16 格（char_sheet）挂在参考集的 sheet_panels 下时一并带上（下游按朝向和景别挑格子）
    from app.production.canonical import canonical_views

    panels = canonical_views(ref)
    panel_urls = _urls(db, [p["asset_id"] for p in panels.values()])
    for key, p in panels.items():
        if p["asset_id"] in panel_urls:
            views[key] = panel_urls[p["asset_id"]]
    # Historical URL-only panels remain readable; asset-backed panels never use stale URLs.
    from app.pipelines.base import as_items
    for p in as_items(ref, "sheet_panels"):
        if not p.get("asset_id") and p.get("key") and p.get("url"):
            views.setdefault(str(p["key"]), str(p["url"]))
    user = ref.get("physical")
    if isinstance(user, dict) and user.get("source") == "user":
        physical = Physical(**{k: v for k, v in user.items() if k in Physical.model_fields})
    else:
        look_text = (epoch.visual_prompt if epoch else None) or ent.visual_prompt
        physical = infer_physical(ent.appearance, ent.summary, look_text)
    wardrobe = ((reference_elements(epoch) if epoch else {}).get("wardrobe") or {}).get("en") or ""
    look = wardrobe or appearance(db, entity_id, chapter_order, profile_id)
    return AssetCard(id=f"e:{entity_id}", kind="character", entity_id=entity_id, name=ent.display_name,
                     screen_name=screen_name, aliases=[str(a) for a in (ent.aliases_json or []) if a][:8],
                     epoch=getattr(epoch, "epoch_key", None), physical=physical, views=views, look_en=look[:400])


def location_card(db: Session, scene: Any, shot: Any, plan: Any) -> AssetCard | None:
    """地点卡：场次地点 + 资产库里定好的场景图（关键帧、白模用的同一张）。"""
    from app.director.from_shot import director_brief

    if scene is None:
        return None
    loc = (director_brief(db, shot, plan).get("location") or {}) if shot is not None else {}
    views = {"plate": loc["url"]} if loc.get("url") else {}
    return AssetCard(id=f"l:scene:{scene.id}", kind="location", name=scene.location_text or scene.title or "场景",
                     views=views, look_en=str(loc.get("prompt") or "")[:400])


def cards_for_shots(db: Session, plan: Any, shots: list[Any]) -> list[AssetCard]:
    """一组镜头（一镜、几镜、一场、一章）要用到的素材卡：先人，后地点（每个场次一张）。"""
    from app.models import Chapter, Scene, ScriptDoc, WorldTransform

    doc = db.get(ScriptDoc, plan.script_doc_id) if getattr(plan, "script_doc_id", None) else None
    chapter = db.get(Chapter, doc.chapter_id) if doc else None
    transform = db.get(WorldTransform, plan.transform_id) if getattr(plan, "transform_id", None) else None
    profile_id = transform.target_profile_id if transform else None
    people = scene_people(db, shots)
    names = _screen_names(db, getattr(plan, "transform_id", None), people)
    cards = [c for c in (character_card(db, e, profile_id=profile_id, chapter_order=getattr(chapter, "order_no", None),
                                        screen_name=names.get(e)) for e in people) if c is not None]
    seen: set[str] = set()
    for s in sorted(shots, key=lambda x: x.order_no):
        if s.scene_id and s.scene_id not in seen:
            seen.add(s.scene_id)
            c = location_card(db, db.get(Scene, s.scene_id), s, plan)
            if c is not None:
                cards.append(c)
    return cards


def set_physical(db: Session, card_id: str, physical: Physical, *, profile_id: str | None,
                 chapter_order: int | None) -> Physical:
    """人改物理尺寸：写进这一章那一期参考集的 physical（source=user，以后不再被推断覆盖）。"""
    from app.pipelines.epochs import resolve_epoch

    if not card_id.startswith("e:"):
        raise ValueError("现在只有人物卡能改物理尺寸")
    epoch = resolve_epoch(db, card_id[2:], profile_id, chapter_order) if profile_id else None
    if epoch is None:
        raise ValueError("这个人在本章没有造型时期，先在后台「人物时期」里推导")
    p = physical.model_copy(update={"source": "user"})
    epoch.reference_set_json = {**(epoch.reference_set_json or {}), "physical": p.model_dump()}
    db.flush()
    return p
