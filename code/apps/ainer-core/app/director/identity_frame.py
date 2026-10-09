"""3D 导演出片的身份首帧：Blender 预演首帧打底，每个人只在自己的区域里画自己的脸（FLUX 分区身份）。

为什么要这一步：LTX 2.5 按控制素材出片时，人长什么样只能靠文字 —— 实跑出来是大头卡通、脸也不是角色库里的人；
而同一套分区身份在阶段 1 的 spike 里三人全对（空景＋灰人偶底图、每人一块区域、只带自己的脸）。
预演首帧本身就是「场景＋灰人偶」，每个人的区域由 Blender 人物色块直接给（能算遮挡，比 2D 槽位准）。
画好的首帧钉在 LTX 成片的第 0 帧：站位、动作、机位跟预演走，长相和画风跟角色库走。
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.capability.schemas import Capability
from app.director import config
from app.director.renderers.base import run_task
from app.models import DirectorJob

log = logging.getLogger(__name__)


class IdentityFrameError(RuntimeError):
    """出不了身份首帧、而且不该退回「不钉首帧」的情况（有人要出场，却没有预演色块或正脸参考）。"""


#: 区域比人物轮廓外扩的比例（头发、手、衣摆会超出人偶）
PAD_X, PAD_Y = 0.18, 0.08
MAX_REGIONS = 3
#: 特写：预演里人物已经占满取景，首帧要保持这个构图——不写这句，模型按「一个人物」画成全身小人，
#: 预演选的特写机位就白选了（实跑：镜 2 预演是头肩特写，首帧出成 15% 宽的全身像）
CLOSEUP = {"ecu": "extreme close-up, only the face fills the whole region, forehead and chin cropped by the frame, no body visible",
           "cu": "close-up, head and upper chest only, the person fills the whole region and is cropped at the chest by the frame, legs and feet not visible"}
CLOSEUP_SHOT = {"ecu": "Extreme close-up shot of a face.", "cu": "Close-up shot, head and shoulders, shallow depth of field."}

#: 第 0 帧正在做的动作 → 首帧里这个人的姿势（动作库见 ainer-studio/src/scene/rig.ts）。
#: 首帧要画成动作的起势：成片的骨架/深度控制从这一刻开始动，首帧姿势对不上，开头几帧会被硬拽过去
#: （实跑：协议是「两人挥拳」，首帧按外貌描述画成了插兜，成片前 0.4 秒整个人形在变）
ACTION_START = {
    "idle": "standing relaxed",
    "walk_forward": "walking forward mid-stride",
    "run_forward": "running forward mid-stride",
    "turn_left": "turning to the left",
    "turn_right": "turning to the right",
    "turn_to": "turning to face {target}",
    "look_back": "looking back over the shoulder",
    "right_punch": "leaning toward {target} in a fighting stance, right fist drawn back ready to punch",
    "left_punch": "leaning toward {target} in a fighting stance, left fist drawn back ready to punch",
    "front_kick": "in a fighting stance facing {target}, weight shifting to kick",
    "dodge_left": "ducking to the left",
    "dodge_right": "ducking to the right",
    "block_high": "raising both forearms in front of the face to block",
    "hit_react_back": "recoiling backward as if just hit",
    "hit_react_left": "reeling sideways as if just hit",
    "hit_react_right": "reeling sideways as if just hit",
    "fall_backward": "falling backward off balance",
    "stand_up": "getting up from the ground",
}
POSE_TEXT = {
    "stand": "standing", "walk": "walking", "run": "running", "sit": "sitting", "drive": "sitting at the wheel",
    "crouch": "crouching", "kneel": "kneeling", "point": "pointing", "wave": "waving",
    "fight": "in a fighting stance with fists raised", "lie": "lying on the ground",
    "phone": "holding a phone to the ear", "arms_crossed": "standing with arms crossed",
    "hands_up": "holding both hands up", "aim": "aiming", "bow": "bowing",
}
#: 外貌描述里写死的习惯姿势（插兜、驼背、站姿…）会压过这一镜的动作，画首帧时去掉
_HABIT = re.compile(r"\b(posture|stance|slouch\w*|hunch\w*|hands? in (his |her |the )?pockets?|arms? crossed|"
                    r"gesturing)\b", re.I)


def _boxes(masks: dict[str, Path], w: int, h: int) -> dict[str, tuple[int, int, int, int]]:
    """人物轮廓 → 外扩的矩形区域；相邻两人的区域从两人中心的中线切开，不互相压。"""
    from PIL import Image

    boxes: dict[str, list[int]] = {}
    for aid, p in masks.items():
        im = Image.open(p).convert("L")
        bb = im.point(lambda v: 255 if v > 127 else 0).getbbox()
        if not bb:
            continue
        x0, y0, x1, y1 = bb
        px, py = int((x1 - x0) * PAD_X), int((y1 - y0) * PAD_Y)
        boxes[aid] = [max(0, x0 - px), max(0, y0 - py), min(w, x1 + px), min(h, y1 + py)]
    ordered = sorted(boxes, key=lambda a: (boxes[a][0] + boxes[a][2]) / 2)
    for left, right in zip(ordered, ordered[1:]):
        a, b = boxes[left], boxes[right]
        if a[2] > b[0]:                               # 横向重叠：中线切
            mid = int(((a[0] + a[2]) / 2 + (b[0] + b[2]) / 2) / 2)
            a[2], b[0] = mid, mid
    return {k: tuple(v) for k, v in boxes.items() if v[2] - v[0] > 8 and v[3] - v[1] > 8}


_LOWER = re.compile(r"\b(pants|trousers|jeans|shorts|skirt|leggings|shoes?|sneakers?|boots?|socks?|loafers?|heels?|"
                   r"belt|knees?|legs?|feet|footwear|cargo)\b", re.I)


def upper_body_only(look: str) -> str:
    """特写只留脸和上半身的描述：外貌里写着裤子、鞋，模型就会在区域里把腿和脚画出来，头反而被挤出画面。"""
    parts = [p for p in re.split(r"[,;]", look) if p.strip() and not _LOWER.search(p)]
    return ", ".join(x.strip() for x in parts)


def without_habits(look: str) -> str:
    """去掉外貌里的习惯姿势子句（「hands in pockets or gesturing aggressively」「hunched posture」）。"""
    return ", ".join(c.strip() for c in look.split(",") if c.strip() and not _HABIT.search(c))


def _where(boxes: dict[str, tuple[int, int, int, int]]) -> dict[str, str]:
    """画面里的左中右：给「冲着谁」找个画得出来的说法。"""
    order = sorted(boxes, key=lambda a: boxes[a][0] + boxes[a][2])
    names = {1: [""], 2: ["on the left", "on the right"],
             3: ["on the left", "in the middle", "on the right"]}.get(len(order))
    if names is None:
        return {a: "" for a in order}
    return dict(zip(order, names))


def staging(protocol: dict[str, Any], boxes: dict[str, tuple[int, int, int, int]], t0: float = 0.1) -> dict[str, str]:
    """协议里第 0 帧每个人在干什么 → 英文姿势。只看开场那一刻（t ≤ t0）的动作或姿势。"""
    where = _where(boxes)
    out: dict[str, str] = {}
    actors = {a.get("id"): a for a in protocol.get("actors") or []}
    ops = sorted(protocol.get("timeline") or [], key=lambda o: float(o.get("time") or 0))
    for aid in boxes:
        text = POSE_TEXT.get(str((actors.get(aid) or {}).get("pose") or ""), "")
        for op in ops:
            if op.get("actor") != aid or float(op.get("time") or 0) > t0:
                continue
            if op.get("op") == "actor.play_action" and op.get("action") in ACTION_START:
                text = ACTION_START[op["action"]]
                tgt = op.get("target_actor")
                target = f"the person {where[tgt]}" if tgt in where and where[tgt] else "the other person"
                text = text.format(target=target)
                break
            if op.get("op") == "actor.set_pose" and op.get("pose") in POSE_TEXT:
                text = POSE_TEXT[op["pose"]]
        if text:
            out[aid] = text
    return out


#: 朝向 → 这个人该用参考集里哪一张（按人对镜头的角度挑，不再一律正脸）
_VIEW_BY_FACING = {"to_camera": ("bust", "front"), "three_quarter": ("three_quarter_left", "bust", "front"),
                   "profile": ("profile_left", "three_quarter_left", "front"), "away": ("back", "three_quarter_left")}


def facing(resolved: dict[str, Any], protocol: dict[str, Any], t_frame: int = 0) -> dict[str, tuple[str, str]]:
    """第 0 帧每个人相对镜头的朝向 → {演员: (类别, 英文描述)}。

    为什么要算：身份参考是正脸半身像，区域提示词里又不说人朝哪 —— 模型一律画成对着镜头的证件照。
    预演里两人面对面（镜 5 扇耳光），出来的分镜图却是两人并排看镜头。

    约定（与 Blender worker 一致）：协议 Y 朝上，yaw=0 时人面朝 +Z，yaw=θ 时面朝 (sin θ, 0, cos θ)。
    相机帧 [px, py, pz, lx, ly, lz, lens, roll]。
    """
    import math

    f = (resolved.get("camera") or {}).get("frames") or []
    if len(f) < 6:
        return {}
    i = max(0, min(t_frame, len(f) // 8 - 1)) * 8
    cam, look = (f[i], f[i + 2]), (f[i + 3], f[i + 5])
    dx, dz = look[0] - cam[0], look[1] - cam[1]
    right = (-dz, dx)
    out: dict[str, tuple[str, str]] = {}
    from app.pipelines.base import as_items

    for a in as_items(protocol, "actors"):
        if a.get("type", "human") != "human":
            continue
        sp = a.get("spawn") or {}
        pos = sp.get("position") or [0, 0, 0]
        yaw = math.radians(float((sp.get("rotation") or [0, 0, 0])[1] or 0))
        fwd = (math.sin(yaw), math.cos(yaw))
        tc = (cam[0] - pos[0], cam[1] - pos[2])
        n = math.hypot(*tc) or 1.0
        ang = math.degrees(math.acos(max(-1.0, min(1.0, (fwd[0] * tc[0] + fwd[1] * tc[1]) / n))))
        side = "right" if fwd[0] * right[0] + fwd[1] * right[1] > 0 else "left"
        if ang < 35:
            out[a["id"]] = ("to_camera", "facing the camera")
        elif ang < 70:
            out[a["id"]] = ("three_quarter", f"body and face turned three-quarters toward screen-{side}, "
                                             f"looking toward screen-{side}, not at the camera")
        elif ang < 125:
            out[a["id"]] = ("profile", f"seen in side profile facing screen-{side}, looking toward screen-{side}, "
                                       f"not at the camera")
        else:
            out[a["id"]] = ("away", "back turned to the camera, face not visible, we see the back of the head")
    return out



def _mirrored(url: str) -> str | None:
    """参考图左右翻转（侧面、四分之三参考都朝画面左；人朝画面右时给翻过来的那张）。"""
    import io
    import urllib.request

    from PIL import Image, ImageOps

    from app.capability.mediastore import store_bytes

    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            im = Image.open(io.BytesIO(r.read())).convert("RGB")
    except Exception:          # noqa: BLE001
        return None
    buf = io.BytesIO()
    ImageOps.mirror(im).save(buf, format="PNG")
    return store_bytes(buf.getvalue(), mime="image/png")["url"]



def _face_ref(db: Session, entity_id: str, chapter_order: int | None, profile_id: str | None,
              views_order: tuple[str, ...] = ("bust", "front")) -> str | None:
    """这个人在这一章的参考图：按 views_order 取第一张有的（默认正脸半身像，其次正面全身）。"""
    from app.models import Asset
    from app.pipelines.ltx25_shots import _epoch_for

    ep = _epoch_for(db, entity_id, chapter_order, profile_id, need_views=True)
    views = ((ep.reference_set_json or {}).get("views") or {}) if ep else {}
    for v in (*views_order, "bust", "front"):
        aid = (views.get(v) or {}).get("asset_id")
        if aid and (views.get(v) or {}).get("status") in ("ready", "succeeded"):
            a = db.get(Asset, aid)
            if a is not None and a.url:
                return a.url
    return None


def render(db: Session, blender_job: DirectorJob, ident: dict[str, Any]) -> str | None:
    """出身份首帧，返回图片地址。

    这一镜没人、或者出场的人第一帧都不在画面里（后面才入画）→ None（没有要钉的脸）。
    有人在画面里却做不出来（预演缺人物色块、角色没有正脸参考、出图失败）→ 抛错，不悄悄退回纯文字出人。

    ident：{"cast": [实体 id…（按搭景时的人物顺序）], "looks": [外貌英文…], "actors": [演员 id…（同顺序）],
            "prompt": 背景＋画风, "chapter_order", "profile_id", "seed"}
    """
    from app.capability.mediastore import store_bytes

    out = config.job_dir(blender_job.id)
    vis_path = out / "visibility.json"
    first = out / "first_frame.png"
    loc = ident.get("location") or {}
    w, h = (blender_job.input_json or {}).get("render_plan", {}).get("output_resolution") or [1024, 576]
    if not list(ident.get("cast") or []):
        # 没人的镜头（空镜）也要按场景图出，不然成片的背景就是灰模
        plate = location_plate(db, first, loc, int(w), int(h), ident) if first.exists() else None
        if plate and ident.get("shot_id"):
            attach_first_frame(db, ident["shot_id"], plate[1], blender_job, [], [])
        return plate[0] if plate else None
    if not vis_path.exists() or not first.exists():
        raise IdentityFrameError("预演缺人物色块（visibility.json / first_frame.png），重渲一次预演")
    vis = json.loads(vis_path.read_text(encoding="utf-8"))
    actors = vis.get("actors") or {}
    order = list(ident.get("actors") or [])
    cast = list(ident.get("cast") or [])
    looks = list(ident.get("looks") or [])
    # 演员 ↔ 角色库角色按协议里的 character_ref（e:<实体 id>）一一对应，不靠 p1/p2 的顺序碰运气；
    # 3D-BOX 里改名、换位置、删演员之后绑定仍然成立
    bound = bound_actors(out / "scene_protocol.json", cast)
    if bound:
        order = [a for a, _ in bound]
        cast = [e for _, e in bound]
        by_ent = dict(zip(ident.get("cast") or [], ident.get("looks") or []))
        looks = [by_ent.get(e, "") for e in cast]
    masks = {aid: out / a["mask"] for aid, a in actors.items() if a.get("mask") and (out / a["mask"]).exists()}
    boxes = _boxes(masks, int(w), int(h))
    proto_path = out / "scene_protocol.json"
    proto = json.loads(proto_path.read_text(encoding="utf-8")) if proto_path.exists() else {}
    poses = staging(proto, boxes) if proto else {}
    res_path = out / "scene_resolved.json"
    faces = facing(json.loads(res_path.read_text(encoding="utf-8")), proto) if proto and res_path.exists() else {}
    regions, no_face, kept = [], [], []
    # 露得多的人优先（最多 3 个区域）
    ranked = sorted(boxes, key=lambda a: -max(actors.get(a, {}).get("coverage") or [0]))
    for aid in ranked[:MAX_REGIONS]:
        i = order.index(aid) if aid in order else None
        if i is None or i >= len(cast):
            continue
        if ident.get("shot_size") in CLOSEUP and ident.get("focus") and cast[i] != ident["focus"]:
            # 特写只画焦点人物；别人的人偶不贴回底图、不给区域（从前被画成巨脸、额头条）
            continue
        kind, turn = faces.get(aid, ("to_camera", ""))
        order_v = ("bust", "front") if (ident.get("shot_size") in CLOSEUP and kind == "to_camera") else _VIEW_BY_FACING[kind]
        face = _face_ref(db, cast[i], ident.get("chapter_order"), ident.get("profile_id"), order_v)
        if not face:
            no_face.append(cast[i])
            continue
        if "screen-right" in turn and kind in ("profile", "three_quarter"):
            face = _mirrored(face) or face     # 侧面、四分之三参考图都是朝画面左的
        kept.append(aid)
        look = without_habits(looks[i]) if i < len(looks) else "the same person as the reference"
        if ident.get("shot_size") in CLOSEUP:
            look = upper_body_only(look) or "the same person as the reference"
        if poses.get(aid):
            look = f"{look}; {poses[aid]}"
        if turn:
            look = f"{turn}; {look}"          # 朝向放最前：模型最听前面的话
        cut = CLOSEUP.get(str(ident.get("shot_size") or ""))
        regions.append({"actor": aid, "face": face, "look": f"{cut + '; ' if cut else ''}{look}"})
    if no_face:
        from app.models import WorldEntity
        names = "、".join((getattr(db.get(WorldEntity, e), "display_name", None) or e) for e in no_face)
        raise IdentityFrameError(f"{names} 在角色库里没有可用的正脸参考（半身像或正面全身），先补出来")
    if not regions:
        return None                      # 出场的人第一帧都不在画面里
    # 先把灰模环境换成资产库里的场景图、人偶按预演原位贴回，再整图一次把人偶换成角色。
    # 不走网关的分区身份：它按每人的外框裁出来单独画（连背景一起）再贴回，
    # 成图每个人身上带一块自己的背景，像贴上去的（实跑镜 1、3、4、8）
    plate = location_plate(db, first, loc, int(w), int(h), ident, keep=kept)
    base = {"url": plate[0]} if plate else store_bytes(first.read_bytes(), mime="image/png")
    payload = {"image": {"url": base["url"]}, "width": int(w), "height": int(h), "style": "photoreal",
               "prompt": replace_prompt(regions, boxes, CLOSEUP_SHOT.get(str(ident.get("shot_size") or ""))),
               "reference_images": [{"ref": {"url": r["face"]}, "role": "character", "identity": True}
                                    for r in sorted(regions, key=lambda r: sum(boxes[r["actor"]][::2]))],
               "params": {"seed": ident.get("seed")} if ident.get("seed") is not None else {}}
    # 时限含网关排队：前面可能压着几条 LTX 出片（每条十几分钟）
    t = run_task(db, Capability.image_i2i, payload, purpose="director_first_frame", timeout_s=3600, label="身份首帧")
    imgs = (t.result_json or {}).get("images") or []
    url = str(imgs[0]["url"]) if imgs and imgs[0].get("url") else None
    if not url:
        raise IdentityFrameError("身份首帧出图成功却没有返回图片")
    figures = []
    for a in ranked[:MAX_REGIONS]:
        i = order.index(a) if a in order else None
        if i is None or i >= len(cast) or a not in boxes:
            continue
        x0, y0, x1, y1 = boxes[a]
        figures.append({"actor": a, "entity_id": cast[i], "box": list(boxes[a]),
                        "x": round((x0 + x1) / 2 / int(w), 4), "bottom": round(y1 / int(h), 4)})
    (out / "identity_first_frame.json").write_text(json.dumps(
        {"url": url, "regions": [{"box": boxes.get(a), "actor": a} for a in ranked[:MAX_REGIONS]],
         "figures": figures},
        ensure_ascii=False, indent=1), encoding="utf-8")
    if ident.get("shot_id"):
        attach_first_frame(db, ident["shot_id"], t, blender_job, figures, cast)
    return url


def replace_prompt(regions: list[dict[str, Any]], boxes: dict[str, tuple[int, int, int, int]],
                   shot: str | None = None) -> str:
    """整图编辑的提示词：按人偶从左到右，第 n 个人偶换成第 n+1 张参考图里的人（第 1 张是底图）。"""
    order = sorted(regions, key=lambda r: sum(boxes[r["actor"]][::2]))
    where = {1: ["in the frame"], 2: ["on the left", "on the right"],
             3: ["on the left", "in the middle", "on the right"]}[len(order)]
    lines = [f"The grey mannequin {where[n]} becomes the person from image {n + 2} ({r['look'][:420]})."
             for n, r in enumerate(order)]
    return " ".join(x for x in (
        shot,
        "Image 1 is a real location with grey mannequins in it. Replace every grey mannequin with a real person, "
        "keeping each one exactly where the mannequin is: same position, same size, same pose, same body orientation.",
        *lines,
        f"Exactly {len(order)} {'person' if len(order) == 1 else 'people'}, nobody else, no leftover mannequin, "
        "no transparent or ghost figures. Keep the location, lighting and camera exactly as in image 1; the people "
        "stand on the same floor under the same light with natural shadows. Photorealistic film still.",
    ) if x)


def location_plate(db: Session, first: Path, loc: dict[str, Any], w: int, h: int,
                   ident: dict[str, Any], keep: list[str] | None = None) -> tuple[str, Any] | None:
    """预演首帧（灰模＋人偶）→ 同一机位、同一站位的真实场景（按资产库场景图），返回 (图片地址, 任务)。没有场景图返回 None。

    为什么要这一步：分区身份只认「底图＋每人的脸」，不读场景参考；从前底图就是 Blender 的灰墙，
    场景全靠一句地点文字重新长 —— 镜 1 出来的走廊和资产库里定好的走廊不是同一个地方，
    成片里背景还塌成一面平墙。编辑模型的第二张参考就是场景图：把它的材质、陈设、光搬进预演的几何里。
    """
    from app.capability.mediastore import store_bytes

    if not loc.get("url"):
        return None
    base = store_bytes(first.read_bytes(), mime="image/png")
    # 底图出空场景：人偶和人一律不要，站好位的人偶之后按 Blender 色块原样贴回（只贴要画的人）。
    # 从前让模型「保留人偶」，它会挪人偶、还顺手添路人（实跑镜 1、5 冒出穿黑西装的陌生人）
    prompt = (f"Turn this grey 3D previs render into the real location shown in the second reference image: "
              f"same camera angle, same perspective, same room layout and depth, but with the reference's "
              f"architecture, materials, fixtures, colors and lighting. "
              f"Remove the grey mannequins: the location is completely empty, nobody in it. "
              f"Keep the exact colors of the reference (walls, lockers, floor) — do not recolor anything. "
              f"No other people, no bystanders in the background. "
              f"Photorealistic, no text, no signs with letters. {(loc.get('prompt') or '')[:600]}")
    payload = {"image": {"url": base["url"]}, "prompt": prompt, "width": w, "height": h, "style": "photoreal",
               # identity=true 是网关挑「第二张参考」的标记（flux2_edit2），这里放的是场景图
               "reference_images": [{"ref": {"url": loc["url"]}, "role": "scene", "identity": True}],
               "params": {"seed": ident.get("seed")} if ident.get("seed") is not None else {}}
    t = run_task(db, Capability.image_i2i, payload, purpose="director_location_plate", timeout_s=3600,
                 label="场景底图")
    imgs = (t.result_json or {}).get("images") or []
    if not imgs or not imgs[0].get("url"):
        raise IdentityFrameError("场景底图出图成功却没有返回图片")
    url = str(imgs[0]["url"])
    if keep:
        url = restore_mannequins(url, first, first.parent / "masks", w, h, only=keep) or url
    return url, t


def restore_mannequins(plate_url: str, first: Path, mask_dir: Path, w: int, h: int,
                       only: list[str] | None = None) -> str | None:
    """把预演首帧里的人偶按色块轮廓原样贴回场景底图。

    编辑模型换场景时会顺手重新构图：人偶被挪位、缩小、转成正面，甚至整个没了（实跑镜 3、4、5、8 全变成
    画面正中、对着镜头站）。而后面分区身份的区域是按 Blender 色块算的 —— 人偶不在那个位置，
    人就画到了别处、朝向也丢了。站位和朝向以预演为准，场景只换背景。
    """
    import io
    import urllib.request

    from PIL import Image

    from app.capability.mediastore import store_bytes

    masks = sorted(mask_dir.glob("*.png")) if mask_dir.exists() else []
    if only is not None:
        masks = [m for m in masks if m.stem in only]
    if not masks:
        return None
    try:
        with urllib.request.urlopen(plate_url, timeout=120) as r:
            plate = Image.open(io.BytesIO(r.read())).convert("RGB").resize((w, h))
    except Exception:          # noqa: BLE001
        log.warning("场景底图取不回来，人偶没贴回：%s", plate_url)
        return None
    src = Image.open(first).convert("RGB").resize((w, h))
    for m in masks:
        mk = Image.open(m).convert("L").resize((w, h)).point(lambda v: 255 if v > 127 else 0)
        plate.paste(src, (0, 0), mk)
    buf = io.BytesIO()
    plate.save(buf, format="PNG")
    return store_bytes(buf.getvalue(), mime="image/png")["url"]


def bound_actors(proto_path: Path, cast: list[str]) -> list[tuple[str, str]]:
    """[(演员 id, 实体 id)]：协议里 character_ref=e:<实体 id> 的演员，只保留这一镜出场的人。没有绑定返回 []。"""
    if not proto_path.exists():
        return []
    try:
        actors = json.loads(proto_path.read_text(encoding="utf-8")).get("actors") or []
    except ValueError:
        return []
    out, seen = [], set()
    for a in actors:
        ref = str(a.get("character_ref") or "")
        eid = ref[2:] if ref.startswith("e:") else ""
        if eid and eid in cast and eid not in seen:
            out.append((a["id"], eid))
            seen.add(eid)
    return out if len(out) == len(set(cast)) else []


def attach_first_frame(db: Session, shot_id: str, task: Any, blender_job: DirectorJob,
                       figures: list[dict[str, Any]], cast: list[str]) -> None:
    """把身份首帧写回这一镜的首帧（FrameSpec.first）：分镜图片、3D-BOX 预演、成片是同一条线上的三样东西。

    - 图：分镜首帧就是这张按预演站位、按角色库人脸画出来的图（asset_id / gen_task_id）
    - 谁：entity_ids_json 是这一镜按角色库 id 出场的人（与协议里 character_ref 一致）
    - 站位：params.regional 记预演里每个人的位置，source=director，导演台看得到、也能据此重出
    - 出处：params.previs 记这张图来自哪个预演任务、哪个场景
    """
    from sqlalchemy import select

    from app.models import Asset, FrameRole, FrameSpec, SpecStatus

    frame = db.execute(select(FrameSpec).where(FrameSpec.shot_id == shot_id,
                                               FrameSpec.role == FrameRole.first)).scalars().first()
    asset_id = db.execute(select(Asset.id).where(Asset.gen_task_id == task.id).limit(1)).scalars().first()
    if frame is None or not asset_id:
        log.warning("身份首帧没能写回分镜首帧：shot=%s frame=%s asset=%s", shot_id, bool(frame), asset_id)
        return
    frame.asset_id = asset_id
    frame.gen_task_id = task.id
    frame.status = SpecStatus.ready
    frame.entity_ids_json = list(dict.fromkeys(cast))
    frame.params_json = {**(frame.params_json or {}), "needs_regeneration": False,
                         "regional": {"source": "director", "figures": figures},
                         "previs": {"blender_job_id": blender_job.id, "scene_id": blender_job.scene_id}}
    db.commit()
