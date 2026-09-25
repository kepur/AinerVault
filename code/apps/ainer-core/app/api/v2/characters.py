"""角色库与造型室。

我的角色库 = 小说里的角色（世界实体＋它的参考集）＋我存下的造型副本；官方角色库 = 预设。
造型室的每一次「确认生成」是一次本机图像编辑（在当前立绘上改发型、服装、肤质、身材），
排进出图队列、人在等所以优先；满意了「保存」存成副本（不动小说里的原角色 ——
原角色的参考集牵着已经出好的镜头，悄悄换掉会让前后镜对不上），勾选「保存时生成角色资产」
就接着出半身、三视图、表情九宫格。
"""
from __future__ import annotations

import io
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.capability.mediastore import media_root, store_bytes
from app.capability.schemas import Capability
from app.db import get_db
from app.ids import new_id
from app.models import Asset, AssetEpoch, EntityKind, Novel, Preset, WorldEntity
from app.presets import jobs
from app.presets import service as ps
from app.presets.seeds import EXPRESSIONS

router = APIRouter(prefix="/api/v2/characters", tags=["characters"])

WHITE = "plain pure white background, soft even studio lighting, photorealistic, high detail"
KEEP = "Keep exactly the same person: same face, identity, age, hairstyle and clothing unless told otherwise."


# ── 卡片 ────────────────────────────────────────────────

def _infer_tags(text: str) -> dict[str, str]:
    """从外观描述（英文分项＋中文外观、简介）推性别、年龄段、文化区域，给筛选用。推不出就写「未知」。"""
    t = (text or "").lower()
    female = re.search(r"\b(woman|girl|female|lady|mother|grandmother|aunt|she)\b|[她女娘妈姐妹母婆姨妻嫂姑]", t)
    male = re.search(r"\b(man|boy|male|father|grandfather|uncle|he)\b|[他男爷爸哥弟父叔伯夫]", t)
    gender = "女" if female and not (male and male.start() < female.start()) else "男" if male else "未知"
    # 中年先判：middle-aged 里的 aged 会被当成「老」
    age = ("儿童" if re.search(r"\b(child|kid|toddler)\b|儿童|小孩|孩童", t)
           else "少年" if re.search(r"\b(teen|teenage|teenager|adolescent)\b|少年|少女|中学|高中", t)
           else "中年" if re.search(r"middle-aged|\b(in (his|her) (forties|fifties))\b|中年|[四五]十多?岁", t)
           else "老年" if re.search(r"\b(elderly|old man|old woman|grandmother|grandfather)\b|老人|老年|奶奶|爷爷|老太|[六七八九]十多?岁", t)
           else "青年")
    culture = ("东亚" if re.search(r"east asian|chinese|japanese|korean|中国|东亚", t)
               else "欧美" if re.search(r"european|caucasian|american|欧美|西方", t) else "未知")
    return {"gender": gender, "age": age, "culture": culture}


def _urls(db: Session, ids: list[str]) -> dict[str, str]:
    ids = [i for i in ids if i]
    if not ids:
        return {}
    return {a.id: a.url for a in db.execute(select(Asset).where(Asset.id.in_(ids))).scalars()}


def _entity_cards(db: Session, only: str | None = None) -> list[dict[str, Any]]:
    from app.pipelines.identity import reference_elements

    q = select(WorldEntity).where(WorldEntity.kind == EntityKind.character)
    if only:
        q = q.where(WorldEntity.id == only)
    ents = {e.id: e for e in db.execute(q).scalars()}
    if not ents:
        return []
    epochs: dict[str, AssetEpoch] = {}
    for ep in db.execute(select(AssetEpoch).where(AssetEpoch.subject_key.in_(list(ents)))
                         .order_by(AssetEpoch.from_chapter_order, AssetEpoch.order_no)).scalars():
        views = (ep.reference_set_json or {}).get("views") or {}
        if ep.subject_key not in epochs and any(isinstance(v, dict) and v.get("asset_id") for v in views.values()):
            epochs[ep.subject_key] = ep
    novels = {n.id: n.title for n in db.execute(select(Novel).where(Novel.id.in_({e.novel_id for e in ents.values()}))).scalars()}
    extras = {p.key[7:]: p for p in db.execute(select(Preset).where(Preset.kind == "character", Preset.key.like("entity:%"))).scalars()}
    out = []
    for eid, ep in epochs.items():
        e = ents[eid]
        vids = {k: v.get("asset_id") for k, v in ((ep.reference_set_json or {}).get("views") or {}).items() if isinstance(v, dict)}
        urls = _urls(db, list(vids.values()))
        views = {k: urls.get(a) for k, a in vids.items() if urls.get(a)}
        el = reference_elements(ep)
        ex = extras.get(eid)
        exv = ((ex.payload_json or {}).get("views") or {}) if ex else {}
        identity = (el.get("identity") or {}).get("en") or ""
        described = " ".join(str((el.get(k) or {}).get("en") or "") for k in ("silhouette", "identity", "wardrobe"))
        out.append({
            "id": f"e:{eid}", "source": "novel", "entity_id": eid, "name": e.display_name,
            "novel": novels.get(e.novel_id), "tags": _infer_tags(f"{described} {e.appearance or ''} {e.summary or ''}"),
            "cover": views.get("front") or views.get("bust"), "views": {**views, **{k: v for k, v in exv.items() if k.startswith("expression")}},
            "look": (el.get("wardrobe") or {}).get("en"), "identity": identity,
            "voice": ((ex.payload_json or {}).get("voice") if ex else None), "epoch": ep.epoch_key,
            "pending": jobs.pending(f"char:{ex.id}") if ex else 0,
        })
    return out


def _preset_card(p: Preset) -> dict[str, Any]:
    pl = p.payload_json or {}
    views = pl.get("views") or {}
    return {
        "id": p.id, "source": "official" if p.official else "mine", "name": p.name,
        "tags": pl.get("tags") or {}, "cover": views.get("front") or p.cover_url, "views": views,
        "look": pl.get("look"), "voice": pl.get("voice"), "category": p.category,
        "pending": jobs.pending(f"char:{p.id}"),
    }


def _card(db: Session, cid: str) -> tuple[dict[str, Any], Preset | None]:
    if cid.startswith("e:"):
        cards = _entity_cards(db, only=cid[2:])
        if not cards:
            raise HTTPException(404, "这个角色还没有参考图")
        return cards[0], _entity_extra(db, cid[2:])
    p = db.get(Preset, cid)
    if p is None or p.kind != "character":
        raise HTTPException(404, "角色不存在")
    return _preset_card(p), p


def _entity_extra(db: Session, eid: str) -> Preset:
    """小说角色在角色库里的附加卡（表情九宫格、音色）。不存在就建。"""
    key = f"entity:{eid}"
    p = db.execute(select(Preset).where(Preset.kind == "character", Preset.key == key)).scalars().first()
    if p is None:
        e = db.get(WorldEntity, eid)
        p = Preset(id=new_id("ps"), kind="character", key=key, name=e.display_name if e else eid, category="小说角色",
                   payload_json={"views": {}, "entity_id": eid}, official=False, commercial=True, uses=0, sort=0, author="小说")
        db.add(p)
        db.flush()
    return p


@router.get("")
def list_characters(scope: str = "official", gender: str | None = None, age: str | None = None,
                    culture: str | None = None, q: str | None = None, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    ps.ensure_seeded(db, "character")
    if scope == "official":
        rows = [_preset_card(p) for p in db.execute(select(Preset).where(Preset.kind == "character", Preset.official.is_(True))
                                                      .order_by(Preset.sort)).scalars()]
    else:
        mine = [_preset_card(p) for p in db.execute(select(Preset).where(
            Preset.kind == "character", Preset.official.is_(False), ~Preset.key.like("entity:%"))
            .order_by(Preset.updated_at.desc())).scalars()]
        rows = mine + _entity_cards(db)
    db.commit()

    def keep(c: dict[str, Any]) -> bool:
        t = c.get("tags") or {}
        return ((not gender or t.get("gender") == gender) and (not age or t.get("age") == age)
                and (not culture or t.get("culture") == culture) and (not q or q in c["name"]))
    return [c for c in rows if keep(c)]


@router.get("/voices")
def voices(language: str | None = None, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """TTS 端点上的音色清单（本机 Qwen3-TTS／Edge TTS 等）。"""
    from app.capability.client import CapabilityClient
    from app.capability.errors import CapabilityError
    from app.capability.router import resolve_one

    try:
        ep = resolve_one(db, Capability.audio_tts, "dialogue").endpoint
        with CapabilityClient(ep.base_url, auth=ep.auth_json or {}, dialect=ep.dialect or "capability") as c:
            vs = c.voices(language=language) or c.voices()
    except CapabilityError as exc:
        raise HTTPException(502, f"取音色失败：{exc}") from exc
    return [{"voice_id": v.voice_id, "name": v.display_name, "gender": v.gender, "age": v.age,
             "languages": v.languages, "tags": v.tags, "preview_url": v.preview_url} for v in vs]


@router.get("/jobs/{job_id}")
def job(job_id: str) -> dict[str, Any]:
    j = jobs.get(job_id)
    if j is None:
        raise HTTPException(404, "任务不在队列里了（服务重启过）")
    return {"id": j.id, "status": j.status, "url": j.result_url, "error": j.error, "title": j.title}


@router.get("/{cid}")
def detail(cid: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    card, _ = _card(db, cid)
    db.commit()
    return card


# ── 出图：立绘、半身、三视图、表情九宫格 ─────────────────────

_DERIVED = ("bust", "turnaround", "expressions", "expression_items")


def _set_view(pid: str, view: str, then=None, *, reset_derived: bool = False):
    def done(db: Session, asset: Asset) -> None:
        p = db.get(Preset, pid)
        if p is None:
            return
        pl = dict(p.payload_json or {})
        views = dict(pl.get("views") or {})
        if reset_derived:
            # 立绘重出了：半身、三视图、九宫格都是从旧立绘派生的，留着就和新立绘对不上
            for k in _DERIVED:
                views.pop(k, None)
        if view.startswith("expression:"):
            items = dict(views.get("expression_items") or {})
            items[view.split(":", 1)[1]] = asset.url
            views["expression_items"] = items
            if len(items) >= len(EXPRESSIONS):
                views["expressions"] = _grid([items[k] for k, _, _ in EXPRESSIONS if k in items])
        else:
            views[view] = asset.url
        pl["views"] = views
        p.payload_json = pl
        if view == "front":
            p.cover_url = asset.url          # 封面跟着最新的立绘走
        if then:
            then(db, p)
    return done


def _grid(urls: list[str]) -> str | None:
    """九张表情拼成 3×3。"""
    from PIL import Image

    imgs = []
    for u in urls:
        path = media_root() / u.rsplit("/", 1)[-1]
        if path.exists():
            imgs.append(Image.open(path).convert("RGB"))
    if not imgs:
        return None
    w, h = 256, 256
    grid = Image.new("RGB", (w * 3, h * ((len(imgs) + 2) // 3)), "white")
    for i, im in enumerate(imgs):
        s = min(im.width, im.height)
        crop = im.crop(((im.width - s) // 2, 0, (im.width - s) // 2 + s, s)).resize((w, h))
        grid.paste(crop, ((i % 3) * w, (i // 3) * h))
    buf = io.BytesIO()
    grid.save(buf, "PNG")
    return str(store_bytes(buf.getvalue(), mime="image/png")["url"])


def _i2i(base_url: str, prompt: str, w: int, h: int, style: str = "photoreal") -> dict[str, Any]:
    # 画风放顶层：工作台只读 input.style
    return {"image": {"url": base_url}, "prompt": prompt, "width": w, "height": h, "style": style, "params": {"seed": 11}}


def _enqueue_assets(p: Preset, *, front_url: str | None, bust_url: str | None, expressions: bool = True,
                    turnaround: bool = True) -> int:
    """立绘有了之后的下游：半身、三视图、表情九宫格（表情从半身出）。"""
    n = 0
    group = f"char:{p.id}"
    if front_url and not bust_url:
        def after_bust(db: Session, pp: Preset) -> None:
            if expressions:
                _enqueue_expressions(pp, (pp.payload_json or {}).get("views", {}).get("bust"))
        jobs.enqueue(jobs.Job(title=f"{p.name}·半身", capability=Capability.image_i2i, group=group,
                              payload=_i2i(front_url, f"{KEEP} Tight head-and-shoulders portrait of this person facing the camera, {WHITE}.", 576, 768),
                              on_done=_set_view(p.id, "bust", after_bust)))
        n += 1
    elif bust_url and expressions:
        n += _enqueue_expressions(p, bust_url)
    if front_url and turnaround:
        jobs.enqueue(jobs.Job(title=f"{p.name}·三视图", capability=Capability.image_i2i, group=group,
                              payload=_i2i(front_url, f"{KEEP} Character turnaround reference sheet of this same person: full-body front view, "
                                           f"side view and back view standing side by side, plus three head close-ups (front, three-quarter, profile), {WHITE}.", 1024, 576),
                              on_done=_set_view(p.id, "turnaround")))
        n += 1
    return n


def _enqueue_expressions(p: Preset, bust_url: str | None) -> int:
    if not bust_url:
        return 0
    for key, zh, prompt in EXPRESSIONS:
        jobs.enqueue(jobs.Job(title=f"{p.name}·表情·{zh}", capability=Capability.image_i2i, group=f"char:{p.id}",
                              payload=_i2i(bust_url, f"{KEEP} Head-and-shoulders portrait with a {prompt}, {WHITE}.", 512, 512),
                              on_done=_set_view(p.id, f"expression:{key}")))
    return len(EXPRESSIONS)


class GenerateIn(BaseModel):
    #: all = 立绘→半身→三视图→表情九宫格（一个角色约 12 张）；front = 只出立绘；views = 半身＋三视图；expressions = 九宫格
    what: str = "all"
    #: 已有立绘也重出（what=front 时）；从旧立绘派生的半身、三视图、九宫格一并作废
    redo: bool = False


_AGE_EN = {"儿童": "little", "少年": "teenage", "青年": "young", "中年": "middle-aged", "老年": "elderly"}
_CULTURE_EN = {"东亚": "East Asian", "欧美": "European", "混合": "mixed-race"}


def _who(tags: dict[str, Any]) -> str:
    """标签 → 英文主体，写在立绘提示词开头。

    外观描述里常常不写性别、年龄，模型就自己猜：「赛博猎手」标签是女，描述只写了
    silver buzz cut、techwear jacket，出来是个光头男人（实测）。
    """
    age, g = tags.get("age"), tags.get("gender")
    kid = age in ("儿童", "少年")
    noun = {"女": "girl" if kid else "woman", "男": "boy" if kid else "man"}.get(str(g), "person")
    who = " ".join(x for x in (_AGE_EN.get(str(age), ""), _CULTURE_EN.get(str(tags.get("culture")), ""), noun) if x)
    return f"{'an' if who[:1].lower() in 'aeio' and not who.startswith('European') else 'a'} {who}"


@router.post("/{cid}:generate")
def generate(cid: str, body: GenerateIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    """出角色资产。官方角色从零出（立绘→半身→三视图→表情）；小说角色已有参考集，只补表情九宫格。"""
    card, p = _card(db, cid)
    if p is None:
        raise HTTPException(422, "这个角色不能生成资产")
    if jobs.pending(f"char:{p.id}"):
        return {"queued": 0, "pending": jobs.pending(f"char:{p.id}")}
    views = card.get("views") or {}
    n = 0
    if card["source"] == "novel":
        n = _enqueue_expressions(p, views.get("bust") or views.get("front"))
    elif not views.get("front") or (body.redo and body.what == "front"):
        look = f"{_who(card.get('tags') or {})}: {card.get('look') or card['name']}"
        # 官方角色一律写实：造型室的编辑、三视图、表情都在写实立绘上最稳
        style = "photoreal"
        jobs.enqueue(jobs.Job(
            title=f"{card['name']}·立绘", capability=Capability.image_t2i, group=f"char:{p.id}", purpose="preset_character",
            payload={"prompt": f"Full-body character design reference photo of {look}. Standing naturally facing the camera, "
                               f"arms relaxed, whole body from head to shoes visible, {WHITE}",
                     "negative_prompt": "cropped feet, cut off head, multiple people, text, watermark",
                     "width": 576, "height": 1024, "style": style, "params": {"seed": 5}},
            on_done=_set_view(p.id, "front", None if body.what == "front" else (
                lambda db2, pp: _enqueue_assets(pp, front_url=(pp.payload_json or {})["views"]["front"], bust_url=None)),
                reset_derived=bool(views.get("front")))))
        n = 1
    else:
        n = _enqueue_assets(p, front_url=views.get("front"), bust_url=views.get("bust"),
                            expressions=body.what in ("all", "expressions"), turnaround=body.what in ("all", "views") and not views.get("turnaround"))
    db.commit()
    return {"queued": n, "pending": jobs.pending(f"char:{p.id}")}


# ── 造型室 ────────────────────────────────────────────────

class RestyleIn(BaseModel):
    base_url: str | None = None
    view: str = "front"
    hairstyle: str | None = None      # 发型预设 key
    outfit: str | None = None         # 服装预设 key
    skin: dict[str, float] = Field(default_factory=dict)       # smooth/beauty/texture/glow/rosy/whiten 0–100
    blemish: bool = False
    features: dict[str, str] = Field(default_factory=dict)     # 自由选项：脸型、眼睛……（英文或中文短语）
    body: dict[str, float] = Field(default_factory=dict)       # height/build/shoulder/waist -50–50
    extra: str = ""


_SKIN = {"smooth": "smoother, more even skin", "beauty": "subtly refined, more attractive facial features",
         "texture": "natural visible skin texture", "glow": "luminous, translucent-looking skin",
         "rosy": "rosier cheeks", "whiten": "a fairer skin tone"}


def restyle_instruction(db: Session, body: RestyleIn) -> str:
    parts = [KEEP]
    if body.hairstyle:
        h = db.execute(select(Preset).where(Preset.kind == "hairstyle", Preset.key == body.hairstyle)).scalars().first()
        if h:
            parts.append(f"Change only the hairstyle to {(h.payload_json or {}).get('prompt')}.")
    if body.outfit:
        o = db.execute(select(Preset).where(Preset.kind == "outfit", Preset.key == body.outfit)).scalars().first()
        if o:
            parts.append(f"Change only the clothing to {(o.payload_json or {}).get('prompt')}.")
    skin = [f"{'slightly ' if v < 50 else ''}{_SKIN[k]}" for k, v in body.skin.items() if k in _SKIN and v >= 15]
    if body.blemish:
        skin.append("remove blemishes and acne")
    if skin:
        parts.append("Skin: " + ", ".join(skin) + ".")
    b = body.body
    shape = []
    if abs(b.get("height", 0)) >= 15:
        shape.append("taller, longer-legged proportions" if b["height"] > 0 else "shorter proportions")
    if abs(b.get("build", 0)) >= 15:
        shape.append("a broader, more muscular build" if b["build"] > 0 else "a slimmer, slender build")
    if abs(b.get("shoulder", 0)) >= 15:
        shape.append("broader shoulders" if b["shoulder"] > 0 else "narrower shoulders")
    if abs(b.get("waist", 0)) >= 15:
        shape.append("a slimmer waist" if b["waist"] < 0 else "a thicker waist")
    if shape:
        parts.append("Body: " + ", ".join(shape) + ".")
    feats = [f"{k}: {v}" for k, v in body.features.items() if v]
    if feats:
        parts.append("Facial features: " + "; ".join(feats) + ".")
    if body.extra.strip():
        parts.append(body.extra.strip()[:300])
    parts.append(f"Full body visible, same pose, {WHITE}.")
    return " ".join(parts)


@router.post("/{cid}/restyle")
def restyle(cid: str, body: RestyleIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    card, _ = _card(db, cid)
    base = body.base_url or (card.get("views") or {}).get(body.view) or card.get("cover")
    if not base:
        raise HTTPException(422, "这个角色还没有立绘：先生成角色资产")
    prompt = restyle_instruction(db, body)
    j = jobs.enqueue(jobs.Job(title=f"{card['name']}·造型试穿", capability=Capability.image_i2i, priority=1,
                              group=f"restyle:{cid}", payload=_i2i(base, prompt, 576, 1024), on_done=lambda db2, a: None))
    return {"job_id": j.id, "prompt": prompt}


class SaveLookIn(BaseModel):
    url: str
    name: str | None = None
    generate_assets: bool = True


@router.post("/{cid}/save-look")
def save_look(cid: str, body: SaveLookIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    """存成「我的角色库」里的副本；不动小说里的原角色。"""
    card, src = _card(db, cid)
    name = (body.name or f"{card['name']} - 副本").strip()[:120]
    p = Preset(id=new_id("ps"), kind="character", key=f"user:{new_id()}", name=name, category=(card.get("tags") or {}).get("era") or "我的",
               payload_json={"tags": card.get("tags") or {}, "look": card.get("look"), "views": {"front": body.url},
                             "voice": card.get("voice"), "from": cid},
               official=False, commercial=True, uses=0, sort=0, author="我", cover_url=body.url)
    db.add(p)
    db.flush()
    n = _enqueue_assets(p, front_url=body.url, bust_url=None) if body.generate_assets else 0
    db.commit()
    return {**_preset_card(p), "queued": n}


class VoiceIn(BaseModel):
    voice_id: str
    name: str = ""


@router.post("/{cid}/voice")
def set_voice(cid: str, body: VoiceIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    _, p = _card(db, cid)
    if p is None:
        raise HTTPException(422, "不能设置音色")
    pl = dict(p.payload_json or {})
    pl["voice"] = {"voice_id": body.voice_id, "name": body.name}
    p.payload_json = pl
    db.commit()
    return {"voice": pl["voice"]}


class PreviewIn(BaseModel):
    voice_id: str
    text: str = "你好，很高兴认识你。今天的风，有点像故事开始的那天。"
    language: str = "zh-CN"


@router.post("/voices:preview")
def preview_voice(body: PreviewIn) -> dict[str, Any]:
    j = jobs.enqueue(jobs.Job(title=f"试听·{body.voice_id}", capability=Capability.audio_tts, priority=1, group="voice",
                              purpose="voice_preview",
                              payload={"text": body.text[:200], "language": body.language, "voice_id": body.voice_id},
                              on_done=lambda db, a: None))
    return {"job_id": j.id}
