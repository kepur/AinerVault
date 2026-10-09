"""关键帧方案（借鉴纳逗）：本章定妆照 → 画进场景的关键帧 → 视频模型从关键帧动起来。

纳逗的做法是：人物照 → 定妆照（三视图＋表情）→ 换装定妆照 → 「参考定妆照，生成她在滑雪场的图片」→
「参考换装定妆照＋多角度定妆照＋那张图，按这段动作出视频」。画面好不好、人像不像，全在那张关键帧上；
视频模型只管让它动起来。这里照这个顺序走，前两步就是角色库（时期造型 = 本章服装的定妆照），后两步是这个模块：

  1. 关键帧：图像编辑模型拿「场景图（资产库）当底图 ＋ 这一镜出场人物本章的定妆照当身份参考 ＋ 构图和动作」
     直接画出成片的第一帧 → 挂到这一镜的首帧（FrameSpec，分镜画布上看得到、可以先审）。
  2. 视频：本机 LTX 2.5 钉住这张关键帧当第 0 帧（ltx25_shots identity="frame"）；台词按角色音色配好的
     就用台词轨驱动口型（a2v），否则现场生成声音。运镜写在提示词里。云端走万相图生视频。

和 3D 导演方案（白模控制，from_shot）的分工：白模适合站位、机位、动作必须严格照预演走的镜头（打斗、复杂调度），
它不进成片画面，只当控制视频和身份首帧的构图底；网关的 a2v 不吃白模控制，所以白模镜头的台词音色保证不了。
关键帧方案更快（不搭景、不渲 Blender），人像、服装、场景都由关键帧钉死，作为默认。

引擎：
  local  关键帧 FLUX.2-klein 图像编辑（本机，一张约 30 秒，底图＋最多 3 张身份参考）
         → LTX 2.5（768×448 Q8 流式，带声音）
  cloud  关键帧 通义图像编辑 Max（吃多张参考图，跨期保脸）→ 万相 2.7 图生视频（付费：路由要标好计费并批准用途）
"""
from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.capability.schemas import Capability
from app.models import FrameRole, FrameSpec, Shot, ShotMotion, ShotPlan, SpecStatus

log = logging.getLogger(__name__)

ENGINES = ("local", "cloud")
#: 每个引擎用哪个模型（网关 / 厂商自报的模型 id）
IMAGE_MODEL = {"local": "flux2-klein-4b-edit", "cloud": "qwen-image-edit-max"}
VIDEO_MODEL = {"local": "ltx-2.5-22b-distilled", "cloud": "wan2.7-i2v"}
#: 关键帧尺寸：FLUX.2-klein 编辑档只有 800×480；LTX 出 768×448 时网关把首帧缩过去（宽高比差 3%，裁一点边）
IMAGE_SIZE = {"local": (800, 480), "cloud": (1280, 720)}
PURPOSE_IMAGE = {"local": "shot_keyframe", "cloud": "shot_keyframe_cloud"}
PURPOSE_VIDEO_CLOUD = "shot_video_cloud"
#: FLUX.2-klein 编辑档：底图 ＋ 最多 3 张身份参考（多一张注意力就长一截）
MAX_PEOPLE = 3
#: 身份参考取哪个视角：本章服装的正面全身优先（服装是跨镜认人的关键），其次四分之三侧、半身
IDENTITY_VIEWS = ("front", "three_quarter_left", "bust")
_SIZE_EN = {"ecu": "Extreme close-up", "cu": "Close-up", "ms": "Medium shot", "fs": "Full shot",
            "ws": "Wide shot", "els": "Extreme wide shot"}
_CJK = re.compile(r"[㐀-䶿一-鿿]")


#: 写机位、取景的句子（关键帧要的是「人在干什么」，机位交给视频模型）。镜 6 实跑过：「Starts at frontal eye-level…」
#: 被当成了动作，关键帧画成两人并排正脸
_CAMERA = re.compile(r"\b(camera|lens|dolly|pan|pans|tilt|zoom|tracking|handheld|locked[- ]off|static shot|starts at|ends at|"
                     r"eye[- ]level|angle|frontal|framing|framed|orbit\w*|arc|crane|whip|push[- ]in|pull[- ]out|"
                     r"close[- ]up|wide shot|medium shot|rack focus|focus pull|composition|"
                     r"speed|pace|slow[- ]motion|simulat\w*|jitter\w*|focal length|shutter|frame rate)\b", re.I)
#: 关键帧框景描述里的「运镜分句」：静态图用不上，留着还会把动作挤出提示词（镜 7：「slow pan right, starting from left cheek…」）
_MOVE = re.compile(r"\b(pan|pans|panning|tilt\w*|dolly\w*|track(s|ing)?|truck\w*|zoom\w*|push(es|ing)?[- ]in|pull(s|ing)?[- ]out|"
                   r"orbit\w*|arc(s|ing)?|crane\w*|whip\w*|handheld|locked[- ]off|static camera|steadicam|"
                   r"starting|start(s)? from|ending|ends? (on|at)|moving|moves?|transition\w*|then|speed|pace|"
                   r"slow[- ]motion|simulat\w*|jitter\w*)\b", re.I)
#: 特写、大特写只画焦点人物（9-29 定的：特写把三个人都塞进画面就成了合照）
CLOSE_SIZES = {"ecu", "cu"}
#: 运镜限幅：这些运镜在钉首帧的短镜头里最容易把人甩出画面或把画面拧翻（镜 6 的 orbit 实跑塌成倒置人脸）
_WILD = re.compile(r"[^.!?]*\b(orbit\w*|360|spin\w*|whip[- ]?pan\w*|rotat\w*|swirl\w*|flip\w*|crane\w*|barrel roll)\b[^.!?]*[.!?]?",
                   re.I)


def tame_camera(text: str, size: str | None) -> str:
    """钉住关键帧出片时给运镜限幅：去掉环绕、旋转、甩镜这类句子，再写明「人始终在画面里」。

    「空画面、空运镜、跟静态差不多」两头的毛病都在这：运镜太猛人出画、太弱等于定格。
    特写只许锁定或极慢推近；其余景别只许慢、稳的运镜。
    """
    out = _WILD.sub("", text or "")
    out = re.sub(r"[ \t]{2,}", " ", out).strip()
    if (size or "").lower() in CLOSE_SIZES:
        rule = ("Camera: locked-off or a very slow push-in; the face stays centered and fully in frame for the whole shot; "
                "natural small movements of the face and eyes, no frozen frame.")
    else:
        rule = ("Camera: slow, smooth movement only; the characters stay in frame for the whole shot; "
                "visible body movement and acting, no frozen frame, no flips, no sudden cuts.")
    return f"{out}\n\n{rule}" if out else rule


def still_framing(text: str) -> str:
    """框景描述去掉运镜分句（按逗号、分号切），只留景别、角度、镜头、构图这些静态图用得上的。"""
    keep = [c.strip() for c in re.split(r"[,;]", text or "") if c.strip() and not _MOVE.search(c)]
    return ", ".join(keep)


def first_action(motion_en: str) -> str:
    """运动单里第一句写人的（关键帧是这一镜开头那一刻）；写机位的句子跳过 —— 运镜交给视频模型。"""
    for sentence in re.split(r"(?<=[.!?])\s+", (motion_en or "").strip()):
        if sentence and not _CAMERA.search(sentence):
            return _clip(sentence, 300)
    return ""


class KeyframeError(RuntimeError):
    """出不了关键帧（没人物定妆照、没有英文描述）。消息直接给人看。"""


def _clip(text: str, n: int) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0].rstrip(" ,;")


def _english(text: str | None) -> str:
    """模型不认中文：混着中文的描述整句不要（宁可少写，不把乱码喂进去）。"""
    return "" if not text or _CJK.search(text) else text


def keyframe_prompt(*, people: list[str], size: str | None, framing: str, action: str, location: str,
                    background: str, has_plate: bool) -> str:
    """关键帧提示词（英文、祈使句：FLUX.2-klein 编辑档按指令改图，不按画面描述）。

    顺序按要紧程度排（模型最听前面的话，见 identity_frame 的实测）：人 → 构图和这一刻的动作 → 场景 → 画风 → 质感。
    各段限长：三个人的外貌加场景描述就能把 1900 字占满，构图和动作被截掉的话画出来就是三个人在走廊里站桩。
    人的长相、衣服主要靠参考图，文字只给前面几个从句（脸型、身材）。
    """
    parts = []
    if people:
        who = "; ".join(f"({i + 1}) {_clip(p, 200)}" for i, p in enumerate(people))
        parts.append(f"Place {len(people)} {'person' if len(people) == 1 else 'people'} in the scene, "
                     f"each the same person as reference image {', '.join(str(i + 1) for i in range(len(people)))} "
                     f"in order, keeping their face, hairstyle and outfit exactly: {who}.")
        # 多参考图时 klein 爱把某个人画两遍（实测镜 1：三个人画成四个，被霸凌者出现两次）
        if len(people) > 1:
            parts.append(f"Exactly {len(people)} people in the frame, each of them appears only once, "
                         "every person is different; no duplicates, no extra people.")
    shot = " ".join(x for x in (f"{_SIZE_EN[(size or '').lower()]}." if (size or "").lower() in _SIZE_EN else "",
                                framing) if x)
    if shot:
        parts.append(shot)
    if action:
        parts.append(f"The moment at the start of the shot: {action}")
    if has_plate:
        parts.append("Use this location image as the set and keep it recognisable"
                     + (f": {_clip(location, 160).rstrip('.')}." if location else "."))
    elif location:
        parts.append(f"Change the background to this location: {_clip(location, 200).rstrip('.')}.")
    if background:
        parts.append(_clip(background, 260).rstrip(".") + ".")
    parts.append("Photorealistic cinematic film still, natural light, real skin texture, one single image, "
                 "no text, no captions, no split screen, no collage, no character sheet.")
    return _clip(" ".join(p for p in parts if p), 1900)


def _first_frame(db: Session, shot: Shot) -> FrameSpec:
    """这一镜的首帧规格（关键帧挂在这里）；分镜没建过就补一条空的。"""
    fs = db.execute(select(FrameSpec).where(FrameSpec.shot_id == shot.id, FrameSpec.role == FrameRole.first)
                    ).scalars().first()
    if fs is None:
        from app.ids import new_id
        fs = FrameSpec(id=new_id("fs"), shot_id=shot.id, role=FrameRole.first, status=SpecStatus.pending,
                       derive_from_first=False, params_json={})
        db.add(fs)
        db.flush()
    return fs


def keyframe_request(db: Session, shot: Shot, plan: ShotPlan, engine: str = "local") -> tuple[FrameSpec, dict[str, Any]]:
    """这一镜关键帧的请求体（image.image_to_image）。人物、场景图、构图都取导演要求（from_shot.director_brief），
    和 3D 导演方案用的是同一份「这一镜拍谁、在哪、怎么拍」。"""
    from app.director.from_shot import director_brief
    from app.director.identity_frame import _face_ref

    if engine not in ENGINES:
        raise KeyframeError(f"引擎只有 {', '.join(ENGINES)}")
    from app.pipelines import ltx25_shots as L
    from app.pipelines.director_review import review_of

    b = director_brief(db, shot, plan)
    first = _first_frame(db, shot)
    rv = review_of(shot)
    look_of = dict(zip(b.get("cast") or [], b.get("looks") or []))
    if rv:
        # 导演审过：画面里看得见谁、焦点是谁以审片为准（分镜原文常把「领头少年」分给错的人）
        cast = pick_cast(list(rv.get("cast") or []), rv.get("focus"), b.get("shot_size"))
        for eid in cast:
            look_of.setdefault(eid, L.appearance(db, eid, b.get("chapter_order"), b.get("profile_id")))
    else:
        cast = pick_cast(list(b.get("cast") or []), b.get("focus"), b.get("shot_size"))
    close = (b.get("shot_size") or "").lower() in CLOSE_SIZES
    refs, people, missing = [], [], []
    for eid in cast:
        # 特写要脸：半身像优先；其余要服装：本章服装的正面全身优先
        url = _face_ref(db, eid, b.get("chapter_order"), b.get("profile_id"),
                        ("bust", "front") if close else IDENTITY_VIEWS)
        if not url:
            missing.append(eid)
            continue
        refs.append({"ref": {"url": url}, "role": "character", "identity": True, "tag": f"person {len(refs) + 1}"})
        people.append(_english(look_of.get(eid)) or "the same person as the reference")
    if missing:
        from app.models import WorldEntity
        names = "、".join(getattr(db.get(WorldEntity, e), "display_name", None) or e for e in missing)
        raise KeyframeError(f"{names} 在角色库里还没有本章的定妆照（正面全身 / 半身），先去角色库出图")
    loc = b.get("location") or {}
    plate = loc.get("url") or ""
    # 没有场景图就拿第一个人的定妆照当底图（纳逗第三步就是这么做的：参考定妆照，生成她在滑雪场的图）
    base = plate or (refs[0]["ref"]["url"] if refs else "")
    if not base:
        raise KeyframeError("这一镜既没有场景图也没有出场人物，画不出关键帧（先在资产库给这场戏绑一张场景图）")
    if rv:
        # 审片的首帧描述本身就是静态快照（位置、朝向、部位细节都写了），不再拼运动单的动作句
        framing = _clip(still_framing(_english(rv["first_frame"])), 600).rstrip(" ,;.")
        action = ""
    else:
        framing = _clip(still_framing(_english(first.prompt)), 420).rstrip(" ,;.")
        motion = db.execute(select(ShotMotion).where(ShotMotion.shot_id == shot.id)).scalars().first()
        action = first_action(_english(getattr(motion, "motion_prompt_en", None)))
    framing = f"{framing}." if framing else ""
    prompt = keyframe_prompt(people=people, size=b.get("shot_size"), framing=framing, action=action,
                             location=_english(loc.get("prompt")), background=_english(b.get("background")),
                             has_plate=bool(plate))
    w, h = IMAGE_SIZE[engine]
    payload: dict[str, Any] = {
        "image": {"url": base}, "prompt": prompt, "width": w, "height": h, "style": "photoreal",
        # 改动幅度：要把人画进场景、换姿势，几乎是重画（厂商语义相反的由中间层翻）
        "strength": 0.9, "reference_images": refs, "params": {},
        "_cast": [{"entity_id": e} for e in cast if e not in missing],   # 只给 submit_keyframe 用，提交前拿掉
    }
    return first, payload


def pick_cast(cast: list[str], focus: str | None, size: str | None) -> list[str]:
    """画进关键帧的人：特写只要焦点人物；其余最多 3 个，焦点人物排第一（模型最听前面的话）。"""
    if not cast:
        return []
    if focus in cast and (size or "").lower() in CLOSE_SIZES:
        return [focus]
    ordered = ([focus] if focus in cast else []) + [e for e in cast if e != focus]
    return ordered[:MAX_PEOPLE]


#: 关键帧覆盖首帧时要清掉的旧记录：导演链的预演站位、分区身份，留着会被下一次 brief 当成「导演手摆的站位」
_STALE_FRAME_KEYS = ("previs", "regional", "needs_regeneration", "missing_character_references")


def _route(db: Session, capability: str, model: str, *, refreshed: bool = False):
    """点名模型的路由（付费闸要看路由上的计费标注）。返回 (route, 本机?, 被拦的原因)。

    模型目录读的是 core 缓存的那份网关能力目录（capability_endpoints.caps_cache_json）。网关
    （ml-stable-diffusion/ai-studio，7999）重启或新装了模型以后，缓存会落后：2026-10-08 快速成片出视频时
    缓存里还没有 ltx-2.5，报「没有找到模型」，其实网关早就有了。所以找不到时先向本机网关刷新一次目录再找。
    """
    from app.capability.generic import (
        _enabled_routes, blocked_reason, catalog_models, is_local_endpoint, route_for,
    )
    from app.models import CapabilityEndpoint

    eps = list(db.execute(select(CapabilityEndpoint).where(CapabilityEndpoint.enabled.is_(True))
                          .order_by(CapabilityEndpoint.name)).scalars())
    for ep in eps:
        for info in catalog_models(ep, [capability]):
            if info.model == model:
                route, routed = route_for(info, ep, _enabled_routes(db))
                local = is_local_endpoint(getattr(ep, "base_url", None))
                return route, local, None if local else blocked_reason(db, route, routed)
    if not refreshed and _refresh_local_catalogs(db, eps):
        return _route(db, capability, model, refreshed=True)
    return None, False, f"没有找到模型 {model}（网关没开、或后台没接这个厂商）"


def _refresh_local_catalogs(db: Session, eps: list) -> bool:
    """向本机网关重新拉一次能力目录写回缓存（同后台「刷新能力」）。只刷本机端点：云端厂商的目录不会突然多出模型。"""
    from app.capability.client import CapabilityClient
    from app.capability.generic import is_local_endpoint
    from app.models.base import utcnow

    done = False
    for ep in eps:
        if not is_local_endpoint(getattr(ep, "base_url", None)):
            continue
        try:
            with CapabilityClient(ep.base_url, auth=ep.auth_json or {}, timeout_sec=20,
                                  dialect=ep.dialect or "capability") as c:
                cat = c.capabilities()
        except Exception as exc:                      # noqa: BLE001 —— 网关没开：照旧报找不到
            log.warning("刷新 %s 的能力目录失败：%s", ep.name, exc)
            continue
        ep.caps_cache_json = cat.model_dump(mode="json")
        ep.caps_fetched_at = utcnow()
        ep.contract_version = cat.capability_version
        done = True
    if done:
        db.flush()
    return done


def _scope(db: Session, plan: ShotPlan) -> tuple[str | None, str | None]:
    from app.models import Chapter, ScriptDoc
    doc = db.get(ScriptDoc, plan.script_doc_id)
    chapter = db.get(Chapter, doc.chapter_id) if doc else None
    return (chapter.novel_id if chapter else None), (chapter.id if chapter else None)


def submit_keyframe(db: Session, plan: ShotPlan, shot: Shot, engine: str = "local"):
    """交一张关键帧；出完由 capability.service 按 frame_spec 挂到这一镜的首帧。返回 GenTask。"""
    return submit_candidates(db, plan, shot, engine, 1)[0]


#: 候选图不自动挂到首帧（挑完再挂）：ref_kind 用一个 service 不认识的值
CANDIDATE_REF_KIND = "keyframe_candidate"


def submit_candidates(db: Session, plan: ShotPlan, shot: Shot, engine: str = "local", n: int = 1) -> list:
    """交 n 张关键帧。n=1 直接挂首帧；n>1 各用不同种子出候选，挑完由 attach_candidate 挂（返回 GenTask 列表）。"""
    from app.capability.service import submit_task

    first, payload = keyframe_request(db, shot, plan, engine)
    route, _local, blocked = _route(db, Capability.image_i2i.value, IMAGE_MODEL[engine])
    if route is None or blocked:
        raise KeyframeError(f"关键帧模型不能用：{blocked}")
    novel_id, chapter_id = _scope(db, plan)
    kept = {k: v for k, v in (first.params_json or {}).items() if k not in _STALE_FRAME_KEYS}
    first.params_json = {**kept, "keyframe": {"engine": engine, "model": IMAGE_MODEL[engine], "prompt": payload["prompt"]}}
    # 画面里有谁就记谁：LTX 出片时「Characters in this shot」按它写，和关键帧对得上
    first.entity_ids_json = [r["entity_id"] for r in payload.pop("_cast", [])] or first.entity_ids_json
    n = max(1, min(4, int(n)))
    tasks = []
    for i in range(n):
        body = payload if n == 1 else {**payload, "params": {**payload.get("params", {}), "seed": 1000 + 7919 * i + (shot.order_no or 0)}}
        task = submit_task(db, Capability.image_i2i, body, purpose=PURPOSE_IMAGE[engine],
                           ref_kind="frame_spec" if n == 1 else CANDIDATE_REF_KIND,
                           ref_id=first.id, novel_id=novel_id, chapter_id=chapter_id, route=route, force=True)
        tasks.append(task)
    if n == 1:
        first.gen_task_id = tasks[0].id
    db.commit()
    return tasks


def candidate_url(db: Session, task_id: str) -> tuple[str, str] | None:
    """候选任务的产物 (asset_id, url)。"""
    from app.models import Asset, AssetKind

    a = db.execute(select(Asset).where(Asset.gen_task_id == task_id, Asset.kind == AssetKind.image)
                   ).scalars().first()
    return (a.id, a.url) if a is not None else None


def attach_candidate(db: Session, shot: Shot, task_id: str, asset_id: str, pick: dict[str, Any] | None = None) -> None:
    """把挑中的候选挂成这一镜的首帧（和 service 自动回挂 frame_spec 做的一样，外加记下挑图理由）。"""
    first = _first_frame(db, shot)
    first.asset_id = asset_id
    first.gen_task_id = task_id
    first.status = SpecStatus.ready
    params = {**(first.params_json or {}), "needs_regeneration": False}
    if pick:
        params["keyframe"] = {**(params.get("keyframe") or {}), "pick": pick}
    first.params_json = params


def pick_refs(db: Session, plan: ShotPlan, shot: Shot) -> list[tuple[str, str]]:
    """挑图用的参考：这一镜关键帧用到的定妆照（说明 + 地址），和出图时同一套。"""
    try:
        _first, payload = keyframe_request(db, shot, plan, "local")
    except KeyframeError:
        return []
    from app.models import WorldEntity

    names = [getattr(db.get(WorldEntity, c["entity_id"]), "display_name", "") for c in payload.get("_cast", [])]
    return [(f"{names[i] if i < len(names) else 'character'} — reference portrait", r["ref"]["url"])
            for i, r in enumerate(payload.get("reference_images") or [])]


def submit_video(db: Session, plan: ShotPlan, shot: Shot, engine: str = "local",
                 size: tuple[int, int] = (768, 448)) -> dict[str, Any]:
    """从关键帧出这一镜的视频。返回 {"task": id} 或 {"skipped": 原因}。出完按 ref_kind=shot 挂回 Shot.video_asset_id。"""
    if engine == "local":
        from app.pipelines import ltx25_shots
        res = ltx25_shots.generate(db, plan, shot_ids=[shot.id], regenerate=True, quality="final",
                                   width=size[0], height=size[1], identity="frame")
        items = res.get("items") or []                 # submitted 是条数，明细在 items
        if items:
            return {"task": items[0]["task"], "audio": items[0].get("audio")}
        why = (res.get("skipped") or [{}])[0].get("why") or "LTX 2.5 没接这一镜"
        return {"skipped": why}

    from app.capability.service import submit_task
    from app.director.from_shot import director_brief
    from app.models import Asset

    first = _first_frame(db, shot)
    asset = db.get(Asset, first.asset_id) if first.asset_id else None
    if asset is None:
        return {"skipped": "这一镜还没有关键帧"}
    route, _local, blocked = _route(db, Capability.video_i2v.value, VIDEO_MODEL["cloud"])
    if route is None or blocked:
        return {"skipped": f"云端视频模型不能用：{blocked}"}
    b = director_brief(db, shot, plan)
    novel_id, chapter_id = _scope(db, plan)
    payload = {"first_frame": {"url": asset.url}, "prompt": _clip(b.get("prompt") or "", 1500),
               "duration_ms": int(round(float(b.get("duration") or 5) * 1000)), "fps": 24}
    task = submit_task(db, Capability.video_i2v, payload, purpose=PURPOSE_VIDEO_CLOUD, ref_kind="shot",
                       ref_id=shot.id, novel_id=novel_id, chapter_id=chapter_id, route=route, force=True)
    db.commit()
    return {"task": task.id, "audio": "generate"}
