"""手动模式 —— 把一章编译成人能照着手搓的时间轴。

交付清单（delivery.py）是给**下游程序**看的：一份 JSON，字段齐全、结构规整，
前提是那些程序真的能调通。可 API 会用不了 —— 额度用尽、模型下架、
新供应商还没接、或者某一集就是想换个站点出图。那时整条链路并没有失效：
分镜、提示词、制作单、配音、声景全都算好了，只是没人去调接口。

本模块把同一批产出换一种投影：**按轨道排在时间轴上，每一格配一块可直接
粘贴的文本**。人拿着它去任何一个网页版模型里出图、出声、出片，
再自己拉进剪辑软件对齐。

三条设计约束：

**轨道而不是镜头。** 交付清单按镜头分组，因为下游是逐镜合成的；
人手搓时是逐轨道干的 —— 先把画面全出完，再统一配音，最后铺音效。
按镜头组织会逼人在八个面板之间来回跳。

**每格自带绝对时间码。** 手搓的产物散落在各个网站，最后要在剪辑台上拼起来。
没有时间码就只能靠听靠看对齐，一集下来对不完。时长权威依旧是
TTS 的真实时长 —— 没有生成音频的对白只能给估算，且必须标出来是估的。

**缺口要说出口。** 「这一镜没有提示词」和「这一镜提示词是空字符串」
在界面上长得一样，但前者该补，后者是 bug。gaps 把两者分开列。
"""
from __future__ import annotations

import csv
import io
import logging
from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Asset, AudioKind, AudioSpec, Chapter, CrewSheet, FrameRole, FrameSpec,
    Scene, ScriptDoc, Shot, ShotMotion, ShotPerformance, ShotPlan, WorldEntity,
)
from app.pipelines.base import as_items

log = logging.getLogger(__name__)


# ── 轨道 ──────────────────────────────────────────────────────────────────────
#
# 顺序即工作顺序：先出画面，画面定了才谈得上运动；
# 声音挂在画面之后，因为音效点位要看着画面才对得准。

TRACKS: tuple[tuple[str, str, str], ...] = (
    ("frame_first", "首帧", "每镜的第一张图。人物一致性靠身份锚，别重新描述长相"),
    ("frame_last", "尾帧", "从首帧派生，只写「变了什么」，不要重写整句"),
    ("video", "运动", "把首尾帧交给图生视频；静止也要明写，否则模型会自己加运动"),
    ("dialogue", "对白", "文本 + 音色 + 表演指示。时长以生成结果为准，不要按字数估"),
    ("narration", "旁白", "同对白，但音色固定用旁白音"),
    ("sfx", "音效", "挂在镜头内的相对位置，不是整场"),
    ("bgm", "配乐", "挂整场，不挂单镜"),
    ("ambience", "环境声", "整场铺底，需要能无缝循环"),
)
TRACK_NAMES = {t[0]: t[1] for t in TRACKS}

#: 工种 → 中文。手搓面板里要能一眼找到「光影」「美术」那几栏
CREW_CN = {
    "cinematography": "摄影", "lighting": "灯光", "production_design": "美术",
    "costume_makeup": "服化", "vfx": "视效", "color_grading": "调色",
    "editing": "剪辑", "sound": "声音",
}

#: 出图目标平台。**只影响图像与视频轨的成型方式**，声音轨不受影响 ——
#: 各家 TTS 的入参差别在「音色怎么选」，那是网页上点的，不是文本里写的。
TARGETS: tuple[tuple[str, str], ...] = (
    ("generic", "通用（提示词 + 负面词分行）"),
    ("midjourney", "Midjourney（--ar / --no 参数式）"),
    ("sd", "Stable Diffusion / ComfyUI（正负分段）"),
)

#: 估算语速。**只在没有真实音频时使用，且结果一律打上 estimated 标记。**
#: 中文按字、西文按词，两者速率差得远，混用会让一整章的时间码整体漂移。
_CJK_CPS = 4.8       # 字/秒
_LATIN_WPS = 2.6     # 词/秒
_MIN_LINE_MS = 700


def _is_cjk(ch: str) -> bool:
    return "㐀" <= ch <= "鿿" or "豈" <= ch <= "﫿"


def estimate_speech_ms(text: str) -> int:
    """没有音频时的时长估算。宁可粗，也要标明是估的。"""
    clean = (text or "").strip()
    if not clean:
        return 0
    cjk = sum(1 for c in clean if _is_cjk(c))
    if cjk >= len(clean) * 0.3:
        secs = cjk / _CJK_CPS
    else:
        secs = max(1, len(clean.split())) / _LATIN_WPS
    return max(_MIN_LINE_MS, int(secs * 1000))


def timecode(ms: int, *, sep: str = ",") -> str:
    """毫秒 → HH:MM:SS,mmm。sep 用 ',' 出 SRT，用 '.' 出给剪辑软件看的。"""
    ms = max(0, int(ms))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, milli = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{milli:03d}"


# ── 提示词成型 ────────────────────────────────────────────────────────────────

def _mj_negative(neg: str) -> str:
    """Midjourney 的 --no 只吃逗号分隔的名词，吃不了整句。

    直接把一长串否定句塞进 --no 会被当成一堆无意义的词，
    且 MJ 不认 "no"/"without" 这类否定词 —— 反而会把它们当主体画进去。
    """
    words = [w.strip() for w in (neg or "").replace("，", ",").split(",")]
    return ", ".join(w for w in words if w and len(w.split()) <= 4)


def format_image(prompt: str, negative: str, *, target: str,
                 aspect: str | None) -> str:
    prompt = (prompt or "").strip()
    negative = (negative or "").strip()
    if not prompt:
        return ""
    if target == "midjourney":
        bits = [prompt]
        if aspect:
            bits.append(f"--ar {aspect.replace(':', ':')}")
        bits.append("--style raw")
        no = _mj_negative(negative)
        if no:
            bits.append(f"--no {no}")
        return " ".join(bits)
    if target == "sd":
        out = f"Positive:\n{prompt}"
        if negative:
            out += f"\n\nNegative:\n{negative}"
        return out
    out = prompt
    if negative:
        out += f"\n\n【负面词】{negative}"
    if aspect:
        out += f"\n【画幅】{aspect}"
    return out


def format_video(motion: str, *, first_url: str | None, last_url: str | None,
                 duration_ms: int) -> str:
    """图生视频的一格。**首尾帧的地址要跟着走** —— 手搓时那是要上传的文件。"""
    lines = [motion.strip() or "static locked-off shot"]
    lines.append(f"【时长】{duration_ms / 1000:.1f}s")
    lines.append(f"【首帧】{first_url or '未生成 —— 需先出首帧'}")
    lines.append(f"【尾帧】{last_url or '未生成 —— 可只用首帧'}")
    return "\n".join(lines)


def format_speech(text: str, *, speaker: str | None, voice: str | None,
                  instruct: str | None, language: str | None) -> str:
    lines = [text.strip()]
    meta = []
    if speaker:
        meta.append(f"说话人 {speaker}")
    if voice:
        meta.append(f"音色 {voice}")
    if language:
        meta.append(f"语种 {language}")
    if meta:
        lines.append("【" + " · ".join(meta) + "】")
    if instruct:
        lines.append(f"【表演指示】{instruct}")
    return "\n".join(lines)


def format_audio_cue(prompt: str, *, duration_ms: int | None,
                     loop: bool = False) -> str:
    lines = [prompt.strip()]
    if duration_ms:
        lines.append(f"【时长】{duration_ms / 1000:.1f}s")
    if loop:
        lines.append("【要求】需能无缝循环")
    return "\n".join(lines)


# ── 主编译 ────────────────────────────────────────────────────────────────────

def build_handoff(
    db: Session, plan: ShotPlan, *, target: str = "generic",
) -> dict[str, Any]:
    """把一章编译成轨道化时间轴。"""
    if target not in {t[0] for t in TARGETS}:
        target = "generic"

    doc = db.get(ScriptDoc, plan.script_doc_id)
    chapter = db.get(Chapter, doc.chapter_id) if doc else None
    cfg = plan.config_json or {}
    aspect = cfg.get("aspect_ratio") or "16:9"

    shots = list(db.execute(
        select(Shot).where(Shot.shot_plan_id == plan.id).order_by(Shot.order_no)
    ).scalars())
    shot_ids = [s.id for s in shots]
    if not shot_ids:
        return _empty(chapter, plan, target, aspect)

    frames: dict[str, dict[str, FrameSpec]] = {}
    for f in db.execute(select(FrameSpec).where(FrameSpec.shot_id.in_(shot_ids))).scalars():
        frames.setdefault(f.shot_id, {})[f.role.value] = f

    motions = {m.shot_id: m for m in db.execute(
        select(ShotMotion).where(ShotMotion.shot_id.in_(shot_ids))).scalars()}

    crew: dict[str, dict[str, CrewSheet]] = {}
    for c in db.execute(select(CrewSheet).where(CrewSheet.shot_id.in_(shot_ids))).scalars():
        crew.setdefault(c.shot_id, {})[c.role] = c

    perfs: dict[str, list[ShotPerformance]] = {}
    for p in db.execute(
        select(ShotPerformance).where(ShotPerformance.shot_id.in_(shot_ids))
    ).scalars():
        perfs.setdefault(p.shot_id, []).append(p)

    scene_ids = [s.scene_id for s in shots if s.scene_id]
    scenes = {s.id: s for s in db.execute(
        select(Scene).where(Scene.id.in_(scene_ids))).scalars()} if scene_ids else {}

    audio_shot: dict[str, list[AudioSpec]] = {}
    audio_scene: dict[str, list[AudioSpec]] = {}
    for a in db.execute(select(AudioSpec).where(
        (AudioSpec.shot_id.in_(shot_ids))
        | ((AudioSpec.shot_id.is_(None)) & (AudioSpec.scene_id.in_(scene_ids or [""])))
    )).scalars():
        (audio_shot if a.shot_id else audio_scene).setdefault(
            a.shot_id or a.scene_id or "", []).append(a)

    entities = {}
    if chapter:
        entities = {e.id: e for e in db.execute(
            select(WorldEntity).where(WorldEntity.novel_id == chapter.novel_id)).scalars()}

    assets = _assets(db, [
        *(f.asset_id for d in frames.values() for f in d.values()),
        *(a.asset_id for lst in audio_shot.values() for a in lst),
        *(a.asset_id for lst in audio_scene.values() for a in lst),
        *(s.video_asset_id for s in shots),
    ])

    clips: dict[str, list[dict[str, Any]]] = {t[0]: [] for t in TRACKS}
    gaps: list[dict[str, Any]] = []
    if not scenes:
        # **没有分场时，「位置」这一栏是空的。**
        # 手搓时找不到地点、时间、天气、氛围，人只能自己编，
        # 编出来的东西每一镜都不一样。缺得静悄悄比缺本身更糟：
        # 面板上那一栏干脆不出现，看的人以为这一镜本来就不需要。
        gaps.append({"track": "frame_first", "shot": 0,
                     "why": "这一章没有分场，所有镜头都读不到地点/时间/天气/氛围",
                     "fix": "到「剧本转换」重跑一次，让它分出场次"})
    cursor = 0
    estimated_any = False

    for shot in shots:
        pair = frames.get(shot.id, {})
        first = pair.get(FrameRole.first.value)
        last = pair.get(FrameRole.last.value)
        first_url = _url(assets, first)
        last_url = _url(assets, last)
        scene = scenes.get(shot.scene_id or "")
        detail = _detail(shot, scene, perfs.get(shot.id, []), motions.get(shot.id),
                         crew.get(shot.id, {}), entities)
        label = (shot.description or "").strip() or f"镜 {shot.order_no}"

        for role, frame, url, track in (
            ("first", first, first_url, "frame_first"),
            ("last", last, last_url, "frame_last"),
        ):
            prompt = (frame.prompt if frame else "") or ""
            if not prompt:
                gaps.append({"track": track, "shot": shot.order_no,
                             "why": "没有提示词" if frame is None else "提示词为空",
                             "fix": "在「剧本转换」重新拼帧，或到「分镜调度」补表演"})
            clips[track].append(_clip(
                track, shot, cursor, shot.duration_ms, label, url,
                copy=format_image(prompt, (frame.negative_prompt if frame else "") or "",
                                  target=target, aspect=aspect),
                detail=detail,
                refs=_refs(frame, entities, assets, db),
            ))

        motion = motions.get(shot.id)
        motion_text = (motion.motion_prompt_en if motion else "") or _camera_text(shot)
        clips["video"].append(_clip(
            "video", shot, cursor, shot.duration_ms, label,
            _url_by_id(assets, shot.video_asset_id),
            copy=format_video(motion_text, first_url=first_url, last_url=last_url,
                              duration_ms=shot.duration_ms),
            detail=detail, refs=[],
        ))

        local = 0
        for spec in sorted(audio_shot.get(shot.id, []),
                           key=lambda a: (a.kind != AudioKind.dialogue, a.id)):
            track = spec.kind.value
            if track not in clips:
                continue
            asset = assets.get(spec.asset_id or "")
            dur = spec.duration_ms or (
                int((asset.meta_json or {}).get("duration_ms") or 0) if asset else 0)
            est = False
            if not dur and spec.kind in (AudioKind.dialogue, AudioKind.narration):
                dur = estimate_speech_ms(spec.text or "")
                est = estimated_any = bool(dur)
            params = spec.params_json or {}
            speaker = entities.get(spec.entity_id or "")
            if spec.kind in (AudioKind.dialogue, AudioKind.narration):
                copy = format_speech(
                    spec.text or "", speaker=speaker.display_name if speaker else None,
                    voice=params.get("voice_asset_key") or params.get("voice_id"),
                    instruct=params.get("style_prompt") or params.get("instruct"),
                    language=spec.language_code)
                if not (params.get("voice_asset_key") or params.get("voice_id")):
                    gaps.append({"track": track, "shot": shot.order_no,
                                 "why": "这句没有绑定音色",
                                 "fix": "到「配音表」为该角色配音色"})
            else:
                copy = format_audio_cue(
                    params.get("prompt") or spec.text or "", duration_ms=dur or None)
            clip = _clip(track, shot, cursor + local, dur or 0,
                         (spec.text or params.get("prompt_cn") or "")[:60] or label,
                         asset.url if asset else None,
                         copy=copy, detail=detail, refs=[])
            clip["estimated_duration"] = est
            if speaker:
                clip["speaker"] = speaker.display_name
            clips[track].append(clip)
            local += dur or 0

        cursor += shot.duration_ms

    # 整场轨：配乐与环境声挂场景，跨若干镜连续铺底
    for sid, specs in audio_scene.items():
        rng = [s for s in shots if s.scene_id == sid]
        if not rng:
            continue
        start = sum(s.duration_ms for s in shots if s.order_no < rng[0].order_no)
        total = sum(s.duration_ms for s in rng)
        scene = scenes.get(sid)
        for spec in specs:
            track = spec.kind.value
            if track not in clips:
                continue
            asset = assets.get(spec.asset_id or "")
            params = spec.params_json or {}
            clips[track].append(_clip(
                track, rng[0], start, total,
                (scene.title if scene else None) or f"场 {sid[-4:]}",
                asset.url if asset else None,
                copy=format_audio_cue(params.get("prompt") or spec.text or "",
                                      duration_ms=total,
                                      loop=spec.kind == AudioKind.ambience),
                detail={"场景": _scene_detail(scene)} if scene else {}, refs=[]))
            clips[track][-1]["shot_range"] = [rng[0].order_no, rng[-1].order_no]

    out_tracks = []
    for tid, name, hint in TRACKS:
        items = sorted(clips[tid], key=lambda c: (c["start_ms"], c["shot"]))
        out_tracks.append({
            "id": tid, "name": name, "hint": hint, "clips": items,
            "ready": sum(1 for c in items if c["status"] == "ready"),
            "manual": sum(1 for c in items if c["status"] == "manual"),
        })

    return {
        "chapter": {"id": chapter.id if chapter else None,
                    "title": chapter.title if chapter else None,
                    "novel_id": chapter.novel_id if chapter else None,
                    "order_no": chapter.order_no if chapter else None},
        "shot_plan_id": plan.id,
        "target": target,
        "targets": [{"id": t, "name": n} for t, n in TARGETS],
        "aspect_ratio": aspect,
        "fps": 24,
        "language": plan.target_language_code,
        "total_duration_ms": cursor,
        "shots": len(shots),
        "tracks": out_tracks,
        "resources": _resources(db, shots, frames, entities, assets),
        "gaps": gaps,
        "estimated_durations": estimated_any,
        "notes": (
            "本页是「API 用不了时照着手搓」的那一份。每格的文本可直接粘进任意"
            "网页版模型；出完的文件按时间码拉进剪辑软件即可。"
            + ("　⚠ 部分对白没有生成音频，时长是按字数估的，"
               "实际配音后须回来重新对齐。" if estimated_any else "")
        ),
    }


# ── 细部 ──────────────────────────────────────────────────────────────────────

def _empty(chapter, plan, target, aspect) -> dict[str, Any]:
    return {
        "chapter": {"id": chapter.id if chapter else None,
                    "title": chapter.title if chapter else None,
                    "novel_id": chapter.novel_id if chapter else None,
                    "order_no": chapter.order_no if chapter else None},
        "shot_plan_id": plan.id, "target": target,
        "targets": [{"id": t, "name": n} for t, n in TARGETS],
        "aspect_ratio": aspect, "fps": 24, "total_duration_ms": 0, "shots": 0,
        "tracks": [{"id": t, "name": n, "hint": hint, "clips": [],
                    "ready": 0, "manual": 0} for t, n, hint in TRACKS],
        "resources": {"anchors": [], "audio": [], "images": []},
        "gaps": [{"track": "frame_first", "shot": 0, "why": "这一章还没有分镜",
                  "fix": "先到「剧本转换」编译分镜"}],
        "estimated_durations": False,
        "notes": "这一章还没有分镜，手动模式没有可排的内容。",
    }


def _clip(track: str, shot: Shot, start: int, dur: int, label: str,
          url: str | None, *, copy: str, detail: dict[str, Any],
          refs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "key": f"{track}:{shot.order_no}:{start}",
        "track": track, "shot": shot.order_no,
        "start_ms": start, "duration_ms": dur,
        "tc": timecode(start, sep="."),
        "label": label,
        "asset_url": url,
        # ready = 已经有产物，手搓时可跳过；manual = 这一格要人去出
        "status": "ready" if url else "manual",
        "copy": copy,
        "detail": detail,
        "refs": refs,
    }


def _detail(shot: Shot, scene: Scene | None, perfs: Sequence[ShotPerformance],
            motion: ShotMotion | None, sheets: dict[str, CrewSheet],
            entities: dict[str, WorldEntity]) -> dict[str, Any]:
    """一格展开后能看到的全部上下文。

    用户手搓时的实际动作是「找这一镜对应的人物、位置、光影、美术……」——
    这些数据本来就都算好了，只是散在六张表里。不聚合的话，
    人得在六个页面之间来回翻，翻到第三个就放弃了，然后自己编一个。
    """
    out: dict[str, Any] = {}
    if scene:
        out["场景"] = _scene_detail(scene)
    people = []
    for p in perfs:
        ent = entities.get(p.entity_id)
        en = p.en_json or {}
        people.append({
            "角色": ent.display_name if ent else p.entity_id,
            "站位": getattr(p.position, "value", p.position),
            "朝向": getattr(p.facing, "value", p.facing),
            "视线": p.gaze_target,
            "表情": p.expression, "表情(尾)": p.expression_end,
            "动作": p.action, "动作(尾)": p.action_end,
            "手持": p.props_json or [],
            "英文": {k: v for k, v in (en or {}).items() if v},
        })
    if people:
        out["人物"] = people
    if motion:
        out["运动"] = {k: v for k, v in {
            "起幅": motion.start_frame, "落幅": motion.end_frame,
            "相机": motion.camera_move, "主体": motion.subject_move,
            "节奏": motion.pacing,
        }.items() if v}
    cam = shot.camera_json or {}
    out["镜头"] = {k: v for k, v in {
        "景别": shot.shot_size, "运镜": cam.get("move"),
        "速度": cam.get("speed"), "时长": f"{shot.duration_ms / 1000:.1f}s",
    }.items() if v}
    for role, sheet in sheets.items():
        block = {}
        if sheet.prompt:
            block["中文"] = sheet.prompt
        if sheet.prompt_en:
            block["英文"] = sheet.prompt_en
        if sheet.missing_json:
            block["缺项"] = sheet.missing_json
        if block:
            out[CREW_CN.get(role, role)] = block
    return out


def _scene_detail(scene: Scene | None) -> dict[str, Any]:
    if scene is None:
        return {}
    return {k: v for k, v in {
        "标题": scene.title, "地点": scene.location_text,
        "时间": scene.time_of_day, "天气": scene.weather,
        "氛围": scene.mood, "梗概": scene.summary,
    }.items() if v}


def _camera_text(shot: Shot) -> str:
    cam = shot.camera_json or {}
    bits = [str(cam.get("move") or "static").replace("_", " ")]
    if cam.get("speed") is not None:
        bits.append(f"speed {cam['speed']}")
    return ", ".join(bits)


def _refs(frame: FrameSpec | None, entities: dict[str, WorldEntity],
          assets: dict[str, Asset], db: Session) -> list[dict[str, Any]]:
    """这一格手搓时要上传哪些参考图。

    只列真拿得到地址的 —— 列一个取不到的文件名，人会去找、找不到、
    然后以为是自己的问题。
    """
    if frame is None:
        return []
    out: list[dict[str, Any]] = []
    for item in as_items(frame.params_json or {}, "reference_images"):
        url = ((item.get("ref") or {}) if isinstance(item.get("ref"), dict) else {}).get("url")
        if not url:
            continue
        out.append({"role": item.get("role"), "tag": item.get("tag"), "url": url})
    for aid in frame.ref_asset_ids or []:
        asset = assets.get(aid) or db.get(Asset, aid)
        if asset and asset.url:
            out.append({"role": "asset", "tag": None, "url": asset.url})
    return out


def _resources(db: Session, shots: Sequence[Shot],
               frames: dict[str, dict[str, FrameSpec]],
               entities: dict[str, WorldEntity],
               assets: dict[str, Asset]) -> dict[str, Any]:
    """整章要用到的素材清单，按「上传一次、多镜复用」的方式去重。"""
    seen: dict[str, dict[str, Any]] = {}
    for shot in shots:
        for frame in frames.get(shot.id, {}).values():
            for ref in as_items(frame.params_json or {}, "reference_images"):
                url = ((ref.get("ref") or {}) if isinstance(ref.get("ref"), dict)
                       else {}).get("url")
                if not url:
                    continue
                row = seen.setdefault(url, {"url": url, "role": ref.get("role"),
                                            "tag": ref.get("tag"), "shots": []})
                row["shots"].append(shot.order_no)
    for row in seen.values():
        row["shots"] = sorted(set(row["shots"]))
    return {
        "anchors": sorted(seen.values(), key=lambda r: (r["role"] or "", r["url"])),
        "images": sorted({a.url for a in assets.values()
                          if a.url and (a.mime or "").startswith("image/")}),
        "audio": sorted({a.url for a in assets.values()
                         if a.url and (a.mime or "").startswith("audio/")}),
    }


def _assets(db: Session, ids: Iterable[str | None]) -> dict[str, Asset]:
    clean = [i for i in ids if i]
    if not clean:
        return {}
    return {a.id: a for a in db.execute(
        select(Asset).where(Asset.id.in_(clean))).scalars()}


def _url(assets: dict[str, Asset], frame: FrameSpec | None) -> str | None:
    if frame is None or not frame.asset_id:
        return None
    asset = assets.get(frame.asset_id)
    return asset.url if asset else None


def _url_by_id(assets: dict[str, Asset], asset_id: str | None) -> str | None:
    asset = assets.get(asset_id or "")
    return asset.url if asset else None


# ── 导出 ──────────────────────────────────────────────────────────────────────

def to_srt(handoff: dict[str, Any]) -> str:
    """字幕。对白与旁白按绝对时间码排。

    估算时长的行照出不误 —— 但整份文件开头不加任何说明性文字：
    SRT 里多一行非字幕内容，播放器会把它当第一句台词显示出来。
    """
    lines: list[dict[str, Any]] = []
    for track in as_items(handoff, "tracks"):
        if track["id"] not in ("dialogue", "narration"):
            continue
        for clip in track["clips"]:
            text = (clip.get("copy") or "").split("\n")[0].strip()
            if text:
                lines.append({"start": clip["start_ms"],
                              "end": clip["start_ms"] + max(clip["duration_ms"], 500),
                              "speaker": clip.get("speaker"), "text": text})
    lines.sort(key=lambda x: x["start"])
    out = io.StringIO()
    for i, ln in enumerate(lines, 1):
        who = f"{ln['speaker']}：" if ln.get("speaker") else ""
        out.write(f"{i}\n{timecode(ln['start'])} --> {timecode(ln['end'])}\n"
                  f"{who}{ln['text']}\n\n")
    return out.getvalue()


def to_csv(handoff: dict[str, Any]) -> str:
    """剪辑用的标记表：每格一行，带时间码、时长、状态、素材地址。

    列顺序照「拉进时间线时要看什么」排：先定位（轨道/时间码），
    再决定要不要做（状态），最后才是内容。
    """
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["轨道", "镜号", "开始时间码", "开始毫秒", "时长毫秒",
                "状态", "说话人", "标题", "素材地址", "时长是否估算", "提示词"])
    for track in as_items(handoff, "tracks"):
        for clip in track["clips"]:
            w.writerow([
                track["name"], clip["shot"], clip["tc"], clip["start_ms"],
                clip["duration_ms"],
                "已生成" if clip["status"] == "ready" else "待手搓",
                clip.get("speaker") or "", clip.get("label") or "",
                clip.get("asset_url") or "",
                "是" if clip.get("estimated_duration") else "",
                (clip.get("copy") or "").replace("\n", " ⏎ "),
            ])
    return buf.getvalue()


def to_markdown(handoff: dict[str, Any]) -> str:
    """整章手搓手册。一个文件带走，离线也能干活。"""
    ch = handoff.get("chapter") or {}
    out: list[str] = [
        f"# 手搓手册 · {ch.get('title') or '未命名章节'}",
        "",
        f"- 画幅 {handoff.get('aspect_ratio')}　"
        f"总时长 {handoff.get('total_duration_ms', 0) / 1000:.1f}s　"
        f"{handoff.get('shots')} 镜",
        f"- 出图目标 {handoff.get('target')}",
        "",
        str(handoff.get("notes") or ""),
        "",
    ]
    gaps = handoff.get("gaps") or []
    if gaps:
        out += ["## ⚠ 开工前要补的缺口", ""]
        for g in gaps:
            out.append(f"- **{TRACK_NAMES.get(g['track'], g['track'])}** "
                       f"镜 {g['shot']}：{g['why']} —— {g['fix']}")
        out.append("")
    res = handoff.get("resources") or {}
    if res.get("anchors"):
        out += ["## 要先备好的参考图", ""]
        for a in res["anchors"]:
            shots = "、".join(str(s) for s in a.get("shots") or [])
            out.append(f"- `{a['url']}`（{a.get('role')}，用于镜 {shots}）")
        out.append("")
    for track in as_items(handoff, "tracks"):
        if not track["clips"]:
            continue
        out += [f"## {track['name']}　"
                f"（{track['manual']} 格待手搓 / 共 {len(track['clips'])}）",
                "", f"> {track['hint']}", ""]
        for clip in track["clips"]:
            flag = "✅ 已生成" if clip["status"] == "ready" else "✏️ 待手搓"
            out.append(f"### 镜 {clip['shot']} · {clip['tc']} · {flag}")
            if clip.get("label"):
                out.append(f"*{clip['label']}*")
            out += ["", "```", (clip.get("copy") or "").strip(), "```", ""]
            for ref in as_items(clip, "refs"):
                out.append(f"- 参考图（{ref.get('role')}）：`{ref['url']}`")
            if clip.get("asset_url"):
                out.append(f"- 已有产物：`{clip['asset_url']}`")
            out.append("")
    return "\n".join(out)
