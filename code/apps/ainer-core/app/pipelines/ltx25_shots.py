"""分镜走 LTX-2.5：不要首尾帧，一镜一次出片，片子自带声音。

用户定的（2026-09-28）：FLUX 出的首尾帧整批作废（画面、人物都有问题），成片不再走
「首帧＋尾帧 → 2B 插值」。LTX-2.5 自己出运动和音轨，首尾帧只剩可选锚点。

每一镜一条 video.image_to_video 请求（用途 shot_video_ltx25，路由到网关的 ltx-2.5-22b-distilled）：

  提示词  场景头（同一场景每镜一字不差：地点、时间、光线、氛围）＋ 这一镜的人物外貌 ＋ 构图（首帧提示词的开头）
          ＋ 运动单英文（怎么动、机位怎么走）＋ 音效说明
          —— 为什么要场景头：实跑坏蛋 1–4 镜同属「走廊抢劫」，第 2 镜的首帧提示词却写着「正午阳光、城市室外」，
          出来就是室外；第 3 镜是青色隧道。旧路有场景图当连贯锚把地点拉回来，只剩文字时，每镜各写各的光和地点就全露了
  时长    有对白 = 对白总长 ＋ 前后留白（和 cut.build_timeline 同一个算法，成片里台词对得上位置）；
          没对白 = 画面拍子（cut._beat_ms：动作导演判的 action_ms 优先）
  音频    有对白 → audio.mode=drive：把这一镜的台词按「前留白＋逐句顺排＋后留白」拼成一条驱动轨，
          画面口型跟着它走，成片音轨就是原配音（角色音色不变）；
          没对白 → audio.mode=generate：模型按 Audio: 出环境声、动作声，并写明没人说话

产物落地后由 capability.service 按 ref_kind="shot" 挂到 Shot.video_asset_id（异步回绑，和老路一样）。
"""
from __future__ import annotations

import logging
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Asset, AudioKind, AudioSpec, FrameRole, FrameSpec, GenTask, Shot, ShotMotion, ShotPlan,
)

log = logging.getLogger(__name__)

PURPOSE = "shot_video_ltx25"
MODEL_ID = "ltx-2.5-22b-distilled"
MIN_MS = 1_600
#: 没对白的镜头最长 10 秒；有对白按台词来，最长 20 秒（LTX-2.5 单段上限）
MAX_SILENT_MS = 10_000
MAX_VOICED_MS = 20_000
#: 网关 limits.max_prompt_chars 是 4000；给「Audio:」和分段留余量
PROMPT_BUDGET = 3_600
#: 构图只取首帧提示词开头这么多字（主体、景别、机位），后面逐镜各写的光线描述互相矛盾
FRAMING_CHARS = 420
#: 外貌按从句截：脸在前、衣服在后，衣服是跨镜认人的关键，别截掉
APPEARANCE_CHARS = 380
_SPACES = re.compile(r"\s+")
_CJK = re.compile(r"[㐀-䶿一-鿿]")


def _clean(text: str | None) -> str:
    return _SPACES.sub(" ", (text or "").strip())


def _cue(text: str) -> str:
    """音效说明取第一句：「at 0.5s, slight wind brushing …（后面是给拟音师的长注释）」只留前面那句。"""
    t = _clean(text)
    t = re.split(r"(?<=[.;。；])\s", t, maxsplit=1)[0]
    return t[:140].rstrip(" ,;.")


#: 画风锚，放在提示词最前面（LTX 看开头最重）。实跑没有它时：人物外貌里「肉乎乎的圆脸、厚嘴唇」这类描述
#: 直接被画成皮克斯式卡通，配音驱动那两镜尤其明显；首帧提示词末尾原本那串写实摄影词在截断时被丢了
STYLE_LINES = {
    "photoreal": ("Live-action film footage, photorealistic, real actors, natural skin texture, cinematic lighting. "
                  "Not animation, not cartoon, not 3D render, not anime."),
    "cinematic": ("Cinematic live-action film footage, photorealistic, anamorphic look, natural skin texture. "
                  "Not animation, not cartoon, not 3D render."),
    "anime": "Japanese anime style animation, clean line art, cel shading.",
}


def style_line(plan: Any) -> str:
    """按分镜计划的画风预设取画风锚；没设就写实（改编成片默认真人）。"""
    preset = ((getattr(plan, "config_json", None) or {}).get("style_preset") or {})
    render = str(preset.get("render") or "photoreal").lower()
    return STYLE_LINES.get(render, STYLE_LINES["photoreal"])


def shot_prompt(first: FrameSpec | None, motion: ShotMotion | None, sfx: Sequence[AudioSpec],
                speakers: Sequence[str], fallback: str = "", *, scene: str = "",
                characters: Sequence[str] = (), style: str = "") -> str:
    """LTX-2.5 的一镜提示词。顺序：场景头 → 人物 → 构图 → 动作 → 声音。

    场景头和人物每镜都写同一套字，镜头之间才接得上；构图只取首帧提示词的开头（主体、景别），
    后面那串光线描述是逐镜各写的，互相矛盾（同一场戏一镜室内灯、一镜正午室外），不要。
    """
    action = _clean(motion.motion_prompt_en if motion else "")
    framing = _clean(first.prompt if first else "")
    framing = framing[:FRAMING_CHARS].rsplit(",", 1)[0] if len(framing) > FRAMING_CHARS else framing
    head = [style] if style else []
    if scene:
        head.append(f"Setting (the same location and lighting for every shot of this scene): {scene}.")
    if characters:
        head.append("Characters in this shot: " + "; ".join(f"({i + 1}) {c}" for i, c in enumerate(characters)) + ".")
    header = " ".join(head)
    # 音效单里混着中文说明（存量数据），视频模型的提示词只收英文那几条
    cues = [c for c in (_cue(s.text or "") for s in sfx if s.text) if c and not _CJK.search(c)][:5]
    if speakers:
        audio = ("Audio: " + "; ".join(cues) + ". " if cues else "Audio: ") + \
            f"{', '.join(speakers)} speaks; lips move in sync with the dialogue."
    else:
        audio = ("Audio: " + "; ".join(cues) + ". " if cues else "Audio: natural ambient sound of the scene. ") + \
            "No one speaks: no dialogue, no voices."
    room = PROMPT_BUDGET - len(header) - len(framing) - len(audio) - 12
    if len(action) > room:                 # 运动单写得太长：保动作的前半段（节拍、主动作都在前面）
        action = action[: max(400, room)]
    parts = [p for p in (header, framing, action, audio) if p]
    if not action and not framing:
        parts.insert(1 if header else 0, _clean(fallback))
    return "\n\n".join(parts)[:PROMPT_BUDGET]


def appearance(db: Session, entity_id: str, chapter_order: int | None, profile_id: str | None = None) -> str:
    """一个人在这一章的样子（英文）：取这一章的形象期（按改编圈层），去掉手里拿的东西。"""
    from app.models import WorldEntity
    from app.pipelines.entity_epochs import without_handheld

    pick = _epoch_for(db, entity_id, chapter_order, profile_id)
    ent = db.get(WorldEntity, entity_id)
    text = (pick.visual_prompt if pick else None) or (ent.visual_prompt if ent else None) or ""
    text = _clean(without_handheld(text))
    if len(text) > APPEARANCE_CHARS:                 # 在从句边界截，别把「wearing an o…」截成半个词
        text = text[:APPEARANCE_CHARS].rsplit(",", 1)[0]
    return text.rstrip(" ,")


#: 参考设定图（Ingredients IC-LoRA）：每个角色一行 = 脸部特写 ＋ 正／¾／侧／背全身，黑底无字。
#: 实测（坏蛋谢文东、李爽，走廊中近景 vs 教室特写两镜）：挂设定图两镜是同一张脸、对得上设定图；
#: 纯文字两镜的瘦男孩不是同一个人。模型卡：768×448、121 帧训练，参考图循环成静态视频喂
SHEET_VIEWS = ("bust", "front", "three_quarter_left", "profile_left", "back")
SHEET_MAX_ROWS = 3
SHEET_SIZE = (768, 448)


def _ready_views(ep) -> int:
    views = (ep.reference_set_json or {}).get("views") or {} if ep is not None else {}
    return sum(1 for v in SHEET_VIEWS if (views.get(v) or {}).get("status") in ("ready", "succeeded"))


def _epoch_for(db: Session, entity_id: str, chapter_order: int | None, profile_id: str | None = None, *,
               need_views: bool = False):
    """这一章该用的形象期。

    **先按改编的目标圈层取**（和出首帧的 frame_compose 同一套 resolve_epoch）：同一个人在原著圈层和
    改编圈层各有一期、名字序号都一样 —— 坏蛋的谢文东，原著圈层那期是早年画坏的动漫半身像（四个视角同一张图），
    改编圈层那期才是写实五视角。不分圈层按序号拿，拼出来的设定图第三行就是那张动漫脸。
    取不到再兜底：覆盖这一章的期里挑视角最齐、最近更新的。
    """
    from app.models import AssetEpoch
    from app.pipelines.epochs import resolve_epoch

    def usable(e):
        return e is not None and (_ready_views(e) >= 2 if need_views else bool(e.visual_prompt))

    if profile_id:
        ep = resolve_epoch(db, entity_id, profile_id, chapter_order)
        if usable(ep):
            return ep
    order = chapter_order or 1
    eps = [e for e in db.execute(select(AssetEpoch).where(AssetEpoch.entity_id == entity_id)).scalars() if usable(e)]
    covering = [e for e in eps if (e.from_chapter_order or 0) <= order <= (e.to_chapter_order or 10 ** 9)] or eps
    covering.sort(key=lambda e: (_ready_views(e), e.updated_at or e.created_at), reverse=True)
    return covering[0] if covering else None


def reference_sheet(db: Session, entity_ids: Sequence[str], chapter_order: int | None,
                    profile_id: str | None = None) -> tuple[str | None, str]:
    """拼这一镜的参考设定图，存进媒体库。返回 (url, 设定图说明)；没有可用视图就 (None, "")。"""
    import io

    from PIL import Image

    from app.capability.mediastore import store_bytes
    from app.models import Asset as _Asset

    rows, desc = [], []
    for eid in entity_ids:
        if len(rows) >= SHEET_MAX_ROWS:
            break
        ep = _epoch_for(db, eid, chapter_order, profile_id, need_views=True)
        views = ((ep.reference_set_json or {}).get("views") or {}) if ep else {}
        paths = []
        for v in SHEET_VIEWS:
            aid = (views.get(v) or {}).get("asset_id")
            a = db.get(_Asset, aid) if aid and (views.get(v) or {}).get("status") in ("ready", "succeeded") else None
            p = _media_path(a.url) if a else None
            if p is not None:
                paths.append(p)
        if len(paths) >= 2:
            rows.append(paths)
            desc.append(f"Row {len(rows)}: {appearance(db, eid, chapter_order, profile_id)}")
    if not rows:
        return None, ""
    W, H, pad = SHEET_SIZE[0] * 2, SHEET_SIZE[1] * 2, 12
    row_h = (H - pad * (len(rows) + 1)) // len(rows)
    sheet = Image.new("RGB", (W, H), (0, 0, 0))
    for r, paths in enumerate(rows):
        ims = [Image.open(p).convert("RGB") for p in paths]
        ims = [im.resize((max(1, im.width * row_h // im.height), row_h), Image.LANCZOS) for im in ims]
        total = sum(im.width for im in ims) + pad * (len(ims) - 1)
        if total > W - 2 * pad:
            k = (W - 2 * pad - pad * (len(ims) - 1)) / sum(im.width for im in ims)
            ims = [im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.LANCZOS) for im in ims]
            total = sum(im.width for im in ims) + pad * (len(ims) - 1)
        x, y0 = (W - total) // 2, pad + r * (row_h + pad)
        for im in ims:
            sheet.paste(im, (x, y0 + (row_h - im.height) // 2))
            x += im.width + pad
    buf = io.BytesIO()
    sheet.save(buf, format="PNG")
    stored = store_bytes(buf.getvalue(), mime="image/png")
    return str(stored["url"]), "Reference sheet: " + " ".join(desc)


_SCENE_EN: dict[str, str] = {}


def scene_header(db: Session, scene: Any, chapter: Any = None) -> str:
    """场景头（英文）：地点、时间、光线、氛围。存量字段是中文，走 text.translate 翻一次，按场景缓存。"""
    if scene is None:
        return ""
    fields = [("loc", scene.location_text), ("time", scene.time_of_day), ("light", scene.weather), ("mood", scene.mood)]
    fields = [(k, _clean(v)) for k, v in fields if _clean(v)]
    if not fields:
        return ""
    key = scene.id + "|" + "|".join(v for _, v in fields)
    if key in _SCENE_EN:
        return _SCENE_EN[key]
    texts = dict(fields)
    if any(_CJK.search(v) for v in texts.values()):
        try:
            from app.capability.schemas import Capability
            from app.capability.service import submit_task
            from app.models import TaskStatus

            task = submit_task(db, Capability.text_translate, {
                "source_language": "zh-CN", "target_language": "en-US",
                "segments": [{"id": k, "text": v} for k, v in fields],
                "style_prompt": "Short, literal English for a film scene header (location / time of day / lighting / mood).",
                "glossary": []}, purpose="translate", sync=True,
                novel_id=getattr(chapter, "novel_id", None), chapter_id=getattr(chapter, "id", None),
                ref_kind="scene", ref_id=scene.id)
            if task.status == TaskStatus.succeeded:
                for seg in (task.result_json or {}).get("segments") or []:
                    if seg.get("id") in texts and seg.get("text"):
                        texts[str(seg["id"])] = _clean(seg["text"])
        except Exception as exc:  # noqa: BLE001 —— 翻不了就退回原文，不挡出片
            log.warning("场景头翻译失败，用原文：%s", exc)
    bits = [texts.get("loc", ""), texts.get("time", ""), texts.get("light", ""),
            ("mood: " + texts["mood"]) if texts.get("mood") else ""]
    out = ", ".join(b for b in bits if b)
    _SCENE_EN[key] = out
    return out


def _media_path(url: str | None) -> Path | None:
    from app.pipelines.cut import _local
    return _local(url)


def drive_track(shot: Shot, voiced: Sequence[AudioSpec], assets: dict[str, Asset]) -> tuple[str, int]:
    """这一镜的对白驱动轨：前留白＋逐句顺排＋后留白，48k 单声道 wav，存进媒体库，返回 (url, 时长 ms)。

    排法与 cut.build_timeline 一致（dialogue_padding 的前留白、台词首尾相接），
    所以片子里的口型和成片时间线上的台词是同一个位置。
    """
    from app.capability.mediastore import store_bytes
    from app.pipelines.cut import dialogue_padding

    lead, tail = dialogue_padding(shot)
    files = []
    for spec in voiced:
        p = _media_path((assets.get(spec.asset_id or "") or Asset()).url)
        if p is None:
            raise ValueError(f"镜 {shot.order_no} 的台词音频不在本地媒体库：{spec.asset_id}")
        files.append(p)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "drive.wav"
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
        for f in files:
            cmd += ["-i", str(f)]
        chains = [f"anullsrc=r=48000:cl=mono:d={lead / 1000:.3f}[lead]"]
        chains += [f"[{i}:a]aresample=48000,aformat=channel_layouts=mono[a{i}]" for i in range(len(files))]
        chains.append(f"anullsrc=r=48000:cl=mono:d={tail / 1000:.3f}[tail]")
        seq = "[lead]" + "".join(f"[a{i}]" for i in range(len(files))) + "[tail]"
        chains.append(f"{seq}concat=n={len(files) + 2}:v=0:a=1[out]")
        cmd += ["-filter_complex", ";".join(chains), "-map", "[out]", "-c:a", "pcm_s16le", str(out)]
        subprocess.run(cmd, check=True, capture_output=True, timeout=120, stdin=subprocess.DEVNULL)
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                    str(out)], capture_output=True, text=True, timeout=60).stdout.strip() or 0)
        stored = store_bytes(out.read_bytes(), mime="audio/wav")
    return str(stored["url"]), int(round(dur * 1000))


def _is_ltx25_video(asset: Asset | None) -> bool:
    return bool(asset is not None and (asset.meta_json or {}).get("model") == MODEL_ID)


def _latest_preview_token(db: Session, shot_id: str) -> str | None:
    """这一镜最近一次预览的 resume_token（预览潜变量在网关只留 24 小时）。"""
    tasks = db.execute(
        select(GenTask).where(GenTask.capability == "video.image_to_video", GenTask.ref_kind == "shot",
                              GenTask.ref_id == shot_id).order_by(GenTask.created_at.desc()).limit(5)
    ).scalars()
    for t in tasks:
        tok = (t.result_json or {}).get("resume_token")
        if tok:
            return str(tok)
    return None


def generate(db: Session, plan: ShotPlan, *, limit: int = 0, regenerate: bool = False,
             shot_ids: Sequence[str] | None = None, quality: str = "final",
             width: int = 832, height: int = 448, seed: int | None = None,
             identity: str = "sheet") -> dict[str, Any]:
    """给分镜出 LTX-2.5 视频（带声音）。

    - 已经是 LTX-2.5 出的片子跳过（regenerate=True 重出）；2B 首尾帧时代的旧片子视为待重出
    - quality=preview：只跑第一阶段出半分辨率预览（约一半时间）；再调 quality=final 从同一潜变量续跑，
      预览满意才花第二阶段的时间。final 找不到预览就整段跑
    - limit 必填意义同老路：一支两三分钟，别一把梭整章
    - identity="sheet"（默认）：用这一镜出场角色的五视角拼参考设定图挂 Ingredients，跨镜同一张脸；
      有对白的镜头由网关先挂设定图出一小段拿身份锚、再配音驱动。"text" 只靠文字描述（快，脸会漂）
    """
    from app.capability.schemas import Capability
    from app.capability.service import submit_task
    from app.models import Chapter, Scene, ScriptDoc
    from app.pipelines.base import checkpoint
    from app.pipelines.cut import _assets, _beat_ms

    quality = "preview" if quality == "preview" else "final"
    shots = list(db.execute(
        select(Shot).where(Shot.shot_plan_id == plan.id).order_by(Shot.order_no)).scalars())
    if shot_ids:
        wanted = set(shot_ids)
        shots = [s for s in shots if s.id in wanted]
    sids = [s.id for s in shots]
    firsts = {f.shot_id: f for f in db.execute(select(FrameSpec).where(
        FrameSpec.shot_id.in_(sids), FrameSpec.role == FrameRole.first)).scalars()}
    motions = {m.shot_id: m for m in db.execute(
        select(ShotMotion).where(ShotMotion.shot_id.in_(sids))).scalars()}
    specs: dict[str, list[AudioSpec]] = {}
    for a in db.execute(select(AudioSpec).where(AudioSpec.shot_id.in_(sids))).scalars():
        specs.setdefault(a.shot_id, []).append(a)
    assets = _assets(db, [a.asset_id for lst in specs.values() for a in lst] + [s.video_asset_id for s in shots])
    doc = db.get(ScriptDoc, plan.script_doc_id)
    chapter = db.get(Chapter, doc.chapter_id) if doc else None
    chapter_order = getattr(chapter, "order_no", None)
    from app.models import WorldTransform
    transform = db.get(WorldTransform, plan.transform_id) if plan.transform_id else None
    profile_id = transform.target_profile_id if transform else None
    scene_ids = {s.scene_id for s in shots if s.scene_id}
    scenes = {sc.id: sc for sc in db.execute(select(Scene).where(Scene.id.in_(scene_ids))).scalars()} \
        if scene_ids else {}

    submitted, skipped = [], []
    for shot in shots:
        if limit and len(submitted) >= limit:
            break
        if not regenerate and _is_ltx25_video(assets.get(shot.video_asset_id or "")):
            continue
        motion = motions.get(shot.id)
        own = sorted(specs.get(shot.id, []), key=lambda a: a.id)
        voiced = [a for a in own if a.kind == AudioKind.dialogue]
        missing = [a for a in voiced if not a.asset_id]
        if missing:
            skipped.append({"shot": shot.order_no, "why": "台词还没配音；先出对白再出片（口型要跟着配音走）"})
            continue
        if motion is not None and _CJK.search(motion.motion_prompt_en or ""):
            # 视频模型不认中文：节奏和物理约束等于没写，出来就是乱动（老路同一道门禁）
            skipped.append({"shot": shot.order_no, "why": "英文运动提示词里混着中文；请重出这一镜的运动单"})
            continue
        sfx = [a for a in own if a.kind == AudioKind.sfx]
        first = firsts.get(shot.id)
        # 这一镜里的人：首帧登记的实体 ＋ 说话的人；外貌取这一章的形象时期（去掉手里拿的东西）
        who = list(dict.fromkeys([*(first.entity_ids_json or [] if first else []),
                                  *[a.entity_id for a in voiced if a.entity_id]]))
        looks = {eid: appearance(db, eid, chapter_order, profile_id) for eid in who}
        # 说话的人用人物段里的编号指代，不再把外貌抄一遍
        cast = [eid for eid in who if looks.get(eid)]
        speakers = list(dict.fromkeys(f"character ({cast.index(a.entity_id) + 1})" if a.entity_id in cast
                                      else "the character" for a in voiced))
        scene = scenes.get(shot.scene_id or "")
        prompt = shot_prompt(first, motion, sfx, speakers, shot.description or "",
                             scene=scene_header(db, scene, chapter) if scene else "",
                             characters=[looks[eid] for eid in cast], style=style_line(plan))

        payload: dict[str, Any] = {"prompt": prompt, "width": width, "height": height, "fps": 24,
                                   "quality": quality, "params": {"seed": seed} if seed is not None else {}}
        sheet_url = None
        if identity == "sheet" and cast:
            sheet_url, sheet_desc = reference_sheet(db, cast, chapter_order, profile_id)
            if sheet_url:
                # Ingredients 按 768×448 训练；参考图走 IC-LoRA，不能分阶段预览续跑
                payload.update(reference_sheet={"url": sheet_url}, reference_sheet_desc=sheet_desc,
                               width=SHEET_SIZE[0], height=SHEET_SIZE[1], quality="final")
        if voiced:
            url, track_ms = drive_track(shot, voiced, assets)
            payload["duration_ms"] = max(MIN_MS, min(MAX_VOICED_MS, track_ms))
            payload["audio"] = {"mode": "drive", "track": {"url": url}}
            payload["quality"] = "final"          # a2v 没有分阶段续跑
        else:
            payload["duration_ms"] = max(MIN_MS, min(MAX_SILENT_MS, _beat_ms(shot, motion)))
            payload["audio"] = {"mode": "generate"}
            if quality == "final" and not sheet_url:
                tok = _latest_preview_token(db, shot.id)
                if tok:
                    payload = {"quality": "final", "resume_token": tok}
        task = submit_task(db, Capability.video_i2v, payload, purpose=PURPOSE, ref_kind="shot", ref_id=shot.id,
                           novel_id=chapter.novel_id if chapter else None,
                           chapter_id=chapter.id if chapter else None, force=True)
        submitted.append({"shot": shot.order_no, "task": task.id, "status": task.status.value,
                          "duration_ms": payload.get("duration_ms"), "audio": (payload.get("audio") or {}).get("mode"),
                          "quality": payload.get("quality"), "resumed": "resume_token" in payload,
                          "identity": "sheet" if sheet_url else "text"})
        checkpoint(db)
    remaining = sum(1 for s in shots if not _is_ltx25_video(assets.get(s.video_asset_id or "")))
    return {"submitted": len(submitted), "items": submitted, "skipped": skipped, "remaining": remaining,
            "purpose": PURPOSE}
