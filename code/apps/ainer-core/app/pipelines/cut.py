"""剪辑台 —— 把一章拼成能直接播放的时间线，以及能导出的成片。

前两种投影是 `delivery`（给下游程序的 JSON）与 `handoff`（给人照着手搓的
提示词）。这是第三种：**给眼睛和耳朵**。轨道排开、按时间码对齐、点一下能播。

它回答的是前两种回答不了的那个问题：**「拼起来到底是什么样」**。
分镜看着合理、每张图单看都不错、每句配音单听都对，
连起来却可能这一镜停三秒没事发生、下一镜台词还没说完就切了。
那只有播一遍才知道。

## 电影没有旁白

完整朗读只属于有声书。电影里的小说叙述必须在上游转成动作、反应、环境变化
与视觉转场；剪辑层没有旁白开关，防止同一条产线又退回“图片配朗读”。

## 时长权威仍然是音频

有对白的镜头，长度由对白决定，不由分镜时的估算决定 ——
这条在前两种投影里就是这样，这里不能例外，否则同一章在
剪辑台和交付清单里长度不一样，而两边都说自己是对的。
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Asset, AssetKind, AssetSource, AudioKind, AudioSpec, Chapter, CrewSheet,
    FrameRole, FrameSpec, Scene, ScriptDoc, Shot, ShotMotion, ShotPerformance,
    ShotPlan, WorldEntity,
)
from app.ids import new_id

from app.pipelines import screenplay as sp

log = logging.getLogger(__name__)


#: 轨道。顺序即**叠放顺序**：先画面后声音，声音里对白在最上层 ——
#: 剪辑软件里也是这么排的，换个顺序人会找不到。
TRACKS: tuple[tuple[str, str, str], ...] = (
    ("video", "画面", "visual"),
    ("dialogue", "对白", "audio"),
    ("sfx", "音效", "audio"),
    ("ambience", "环境声", "audio"),
    ("bgm", "配乐", "audio"),
)

#: 没有对白的镜头给多长。**不是随便定的**：
#: 一个只有画面的镜头低于两秒观众来不及看清，高于五秒开始觉得卡住。
#: 初始时长仍来自锁定译本的信息量，这里只负责夹进可信的单镜范围。
_BEAT_MS = 2600
_BEAT_MIN = 1600
_BEAT_MAX = 5200

#: 对白前后各留一点，否则切点压在字上
_PAD_MS = 200


def runtime_window(text: str) -> dict[str, int]:
    """按原著信息量给电影章节一个节奏窗。

    约 1000 个中文字／西文词对应 3–10 分钟。下限防止把剧情压成预告片，
    上限防止靠静默与慢镜头灌水；超长章节到十分钟仍装不下时应拆集。
    """
    raw = text or ""
    cjk = len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", raw))
    latin_words = len(re.findall(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*", raw))
    units = cjk + latin_words
    minimum = max(30_000, min(600_000, units * 180))
    maximum = max(minimum, min(600_000, units * 600))
    return {"source_units": units, "min_ms": minimum, "max_ms": maximum}


def _assets(db: Session, ids: Iterable[str | None]) -> dict[str, Asset]:
    clean = [i for i in ids if i]
    if not clean:
        return {}
    return {a.id: a for a in db.execute(
        select(Asset).where(Asset.id.in_(clean))).scalars()}


def _beat_ms(shot: Shot, motion: ShotMotion | None) -> int:
    """无对白镜头的画面拍子。

    有运动的镜头需要多一点时间把运动走完；静止镜头短一点。
    """
    # 分镜时已经按锁定译本的信息量估过时长，不能把每个视觉叙事镜头
    # 一律砍成 2.6 秒，否则 1000 字章节会被压成一分钟预告片。
    base = int(shot.duration_ms or _BEAT_MS)
    if motion is not None and (motion.camera_move or motion.subject_move):
        base = max(base, _BEAT_MS + 700)
    return max(_BEAT_MIN, min(base, _BEAT_MAX))


def build_timeline(
    db: Session, plan: ShotPlan, *, voiceover: bool = False,
    fps: int = 24,
) -> dict[str, Any]:
    """把一章排成可播放的时间线。

    ``voiceover`` 只为拦截旧调用保留；电影时间线永远没有旁白。
    """
    if voiceover:
        raise ValueError("电影时间线不允许旁白；请使用有声书时间线")
    doc = db.get(ScriptDoc, plan.script_doc_id)
    chapter = db.get(Chapter, doc.chapter_id) if doc else None
    cfg = plan.config_json or {}
    aspect = cfg.get("aspect_ratio") or "16:9"

    shots = list(db.execute(
        select(Shot).where(Shot.shot_plan_id == plan.id).order_by(Shot.order_no)
    ).scalars())
    if not shots:
        return _empty(chapter, plan, aspect, fps, voiceover)
    sids = [s.id for s in shots]

    frames: dict[str, dict[str, FrameSpec]] = {}
    for f in db.execute(select(FrameSpec).where(FrameSpec.shot_id.in_(sids))).scalars():
        frames.setdefault(f.shot_id, {})[f.role.value] = f
    motions = {m.shot_id: m for m in db.execute(
        select(ShotMotion).where(ShotMotion.shot_id.in_(sids))).scalars()}

    scene_ids = [s.scene_id for s in shots if s.scene_id]
    scenes = {s.id: s for s in db.execute(
        select(Scene).where(Scene.id.in_(scene_ids))).scalars()} if scene_ids else {}

    by_shot: dict[str, list[AudioSpec]] = {}
    by_scene: dict[str, list[AudioSpec]] = {}
    for a in db.execute(select(AudioSpec).where(
        (AudioSpec.shot_id.in_(sids))
        | ((AudioSpec.shot_id.is_(None)) & (AudioSpec.scene_id.in_(scene_ids or [""])))
    )).scalars():
        (by_shot if a.shot_id else by_scene).setdefault(
            a.shot_id or a.scene_id or "", []).append(a)

    entities = {}
    if chapter:
        entities = {e.id: e for e in db.execute(
            select(WorldEntity).where(WorldEntity.novel_id == chapter.novel_id)).scalars()}

    assets = _assets(db, [
        *(f.asset_id for d in frames.values() for f in d.values()),
        *(a.asset_id for lst in by_shot.values() for a in lst),
        *(a.asset_id for lst in by_scene.values() for a in lst),
        *(s.video_asset_id for s in shots),
    ])

    #: 哪些音频算进这条时间线的时长
    voiced_kinds = {AudioKind.dialogue}

    clips: dict[str, list[dict[str, Any]]] = {t[0]: [] for t in TRACKS}
    gaps: list[dict[str, Any]] = []
    retimed: list[dict[str, Any]] = []
    #: 需要补机位的镜头。切成几段只是权宜 ——
    #: 真正该做的是让分镜按「一个镜头能承载多长」切，而不是按段落切
    needs_coverage: list[dict[str, Any]] = []
    #: 首尾帧之间没有可见变化的镜头 —— 成片里就是静止画面
    still_shots: list[dict[str, Any]] = []
    cursor = 0

    for shot in shots:
        specs = sorted(by_shot.get(shot.id, []),
                       key=lambda a: (a.kind != AudioKind.dialogue, a.id))
        voiced = [s for s in specs if s.kind in voiced_kinds]
        voiced_ms = sum(_dur(s, assets) for s in voiced)

        # **镜头长度：有台词按台词，没台词按画面拍子。**
        # 不能沿用 shot.duration_ms —— 它是按「对白+旁白」回填的，
        # 拿掉旁白后一个只有旁白的镜头会剩下九秒空画面
        motion = motions.get(shot.id)
        action_beat = sp.is_action_beat(
            shot.description, motion.subject_move if motion else None,
            motion.camera_move if motion else None)

        if voiced_ms:
            dur = voiced_ms + _PAD_MS * 2
            why = "按台词真实时长"
        else:
            dur = _beat_ms(shot, motion)
            why = "无对白视觉叙事镜头，按分镜信息量与画面拍子定长"

        # **首尾帧之间超过五秒就会审美疲劳。**
        # 走路、海浪、粒子 —— 五秒之内是一个动作，五秒之后是同一个动作重复。
        # 动态场景更短：一次出击、一次爆炸，三秒就该切。
        # 这不是审美偏好，是 i2v 的能力边界：它在首尾帧之间插值，
        # 时间越长插得越假，最后变成慢动作糊影。
        #
        # 台词比上限还长时**不砍台词** —— 砍了话就说不完。
        # 那种镜头要拆成两镜，而拆镜是分镜那一步的事，这里只报出来。
        capped, cap_why = sp.clamp_shot_ms(dur, action=action_beat)
        if capped != dur and not voiced_ms:
            dur, why = capped, cap_why or why
        # 有台词且超上限的不在这里砍 —— 砍了话就说不完。
        # 它们在下面按「画面拍子」切成多段，声音仍然连续。

        if abs(dur - shot.duration_ms) > 500:
            retimed.append({
                "shot": shot.order_no,
                "from_ms": shot.duration_ms, "to_ms": dur,
                "action_beat": action_beat, "why": why,
            })

        pair = frames.get(shot.id, {})
        first = pair.get(FrameRole.first.value)
        last = pair.get(FrameRole.last.value)
        first_url = _url(assets, first)
        last_url = _url(assets, last)
        video_url = _url_by_id(assets, shot.video_asset_id)

        if not (video_url or first_url):
            gaps.append({"track": "video", "shot": shot.order_no,
                         "why": "既没有视频也没有首帧，这一镜是黑的",
                         "fix": "去「章节工作台」出首帧"})

        # **首尾帧之间有没有看得见的变化。**
        # 「脚步声渐近」「他依然静坐」在画面上什么都不变，
        # i2v 插不出任何东西 —— 那一镜在成片里就是一张静止画面停几秒。
        # 缺图会黑屏（看得出来），缺变化只是「有点闷」（看不出原因）。
        vis_ok, vis_why = sp.is_visible_change(
            last.derive_instruction if last else None)
        if not vis_ok:
            still_shots.append({
                "shot": shot.order_no,
                "instruction": (last.derive_instruction if last else None),
                "why": vis_why,
            })

        # **一镜太长就切成几段画面，声音不动。**
        #
        # 这是让成片不像 PPT 的第一因，比缺 i2v 更靠前：分镜是按段落切的，
        # 一段二十秒的台词就得到一个二十秒的镜头。而首尾帧之间超过五秒
        # i2v 就插不动了，剩下的时间画面是静止的 —— 那就是幻灯片。
        #
        # 真实剪辑里，一段长台词本来就由好几个镜头覆盖（说话人、听者、手、
        # 环境）。这里没有那么多素材，退而求其次：把同一对首尾帧切成几段，
        # 每段独立走一次 i2v。**切点数量报出来** ——
        # 它等于「这一镜缺几个机位」，是回头补分镜的依据。
        n_seg = 1
        seg_cap = sp.ACTION_MAX_MS if action_beat else sp.STATIC_MAX_MS
        if dur > seg_cap:
            n_seg = -(-dur // seg_cap)      # 向上取整
            needs_coverage.append({
                "shot": shot.order_no, "duration_ms": dur, "segments": n_seg,
                "why": f"{dur/1000:.1f}s 的镜头切成 {n_seg} 段画面；"
                       f"真正该做的是补 {n_seg - 1} 个机位",
            })
        seg_ms = dur // n_seg
        for k in range(n_seg):
            start = cursor + k * seg_ms
            length = (dur - k * seg_ms) if k == n_seg - 1 else seg_ms
            clips["video"].append({
                "key": f"video:{shot.order_no}.{k}", "shot": shot.order_no,
                "seg": k, "segments": n_seg,
                "start_ms": start, "duration_ms": length,
                "video_url": video_url,
                "first_url": first_url, "last_url": last_url,
                "label": ((shot.description or "").strip()[:48]
                          or f"镜 {shot.order_no}")
                         + (f" · 第 {k+1}/{n_seg} 段" if n_seg > 1 else ""),
                "shot_size": shot.shot_size,
                "motion": (motion.motion_prompt_en if motion else None),
                "scene": (scenes.get(shot.scene_id or "").title
                          if scenes.get(shot.scene_id or "") else None),
                "kind": "video" if video_url else ("stills" if first_url else "black"),
            })

        local = _PAD_MS if voiced_ms else 0
        for spec in specs:
            track = spec.kind.value
            if track not in clips:
                continue
            if spec.kind == AudioKind.narration:
                continue
            asset = assets.get(spec.asset_id or "")
            d = _dur(spec, assets)
            who = entities.get(spec.entity_id or "")
            item = {
                "key": f"{track}:{shot.order_no}:{spec.id}",
                "shot": shot.order_no,
                "start_ms": cursor + (local if spec.kind in voiced_kinds
                                      else _at_ms(spec, dur)),
                "duration_ms": d or 0,
                "url": asset.url if asset else None,
                "text": (spec.text or "")[:120],
                "speaker": who.display_name if who else None,
                "ready": bool(asset),
            }
            clips[track].append(item)
            if not asset:
                gaps.append({"track": track, "shot": shot.order_no,
                             "why": f"{_cn(track)}还没生成",
                             "fix": "去「章节工作台」生成音频"})
            if spec.kind in voiced_kinds:
                local += d or 0
        cursor += dur

    # 整场铺底：配乐与环境声跨若干镜连续
    for sid, specs in by_scene.items():
        rng = [c for c in clips["video"] if _scene_of(shots, c["shot"]) == sid]
        if not rng:
            continue
        start = rng[0]["start_ms"]
        total = rng[-1]["start_ms"] + rng[-1]["duration_ms"] - start
        scene = scenes.get(sid)
        for spec in specs:
            track = spec.kind.value
            if track not in clips:
                continue
            asset = assets.get(spec.asset_id or "")
            clips[track].append({
                "key": f"{track}:{sid}", "shot": rng[0]["shot"],
                "start_ms": start, "duration_ms": total,
                "url": asset.url if asset else None,
                "text": (spec.params_json or {}).get("prompt_cn")
                        or (spec.params_json or {}).get("prompt") or "",
                "speaker": None, "ready": bool(asset),
                "scene": scene.title if scene else None,
                "loop": spec.kind == AudioKind.ambience,
            })
            if asset is None:
                gaps.append({
                    "track": track, "shot": rng[0]["shot"],
                    "why": f"场景{_cn(track)}还没生成",
                    "fix": "先从声音制作单编译声景，再生成对应音频",
                })

    out_tracks = []
    for tid, name, layer in TRACKS:
        items = sorted(clips[tid], key=lambda c: c["start_ms"])
        out_tracks.append({
            "id": tid, "name": name, "layer": layer, "clips": items,
            "ready": sum(1 for c in items
                         if c.get("ready") or c.get("video_url") or c.get("first_url")),
            "total": len(items),
        })

    video_items = clips["video"]
    placeholder_shots = sorted({
        int(c["shot"]) for c in video_items if c.get("kind") != "video"
    })
    duplicate = sp.duplicate_changes(
        [(s_.order_no,
          (frames.get(s_.id, {}).get(FrameRole.last.value).derive_instruction
           if frames.get(s_.id, {}).get(FrameRole.last.value) else None))
         for s_ in shots]
    )

    # 最终成片不只要求“每格有个文件”。八工种、调度、物理运动和最终
    # 提示词必须属于同一版；否则旧图旧视频虽然存在，内容已经过期。
    from app.pipelines.frame_compose import _production_inputs, _production_revision
    from app.worldview.crew import CREW

    required_roles = {item.role for item in CREW}
    crew_rows = list(db.execute(
        select(CrewSheet).where(CrewSheet.shot_id.in_(sids))
    ).scalars())
    crew_by_shot: dict[str, set[str]] = {}
    sound_sheet_by_shot: dict[str, CrewSheet] = {}
    for sheet in crew_rows:
        if (sheet.prompt_en and not sheet.missing_json and not sheet.rejected_json):
            crew_by_shot.setdefault(sheet.shot_id, set()).add(sheet.role)
        if sheet.role == "sound":
            sound_sheet_by_shot[sheet.shot_id] = sheet
    incomplete_crew = [
        shot.order_no for shot in shots
        if crew_by_shot.get(shot.id, set()) < required_roles
    ]

    staged_ids = set(db.execute(
        select(ShotPerformance.shot_id)
        .where(ShotPerformance.shot_id.in_(sids)).distinct()
    ).scalars())
    unstaged = []
    stale_prompts = []
    invalid_motion = []
    for shot in shots:
        pair = frames.get(shot.id, {})
        first = pair.get(FrameRole.first.value)
        last = pair.get(FrameRole.last.value)
        if first and first.entity_ids_json and shot.id not in staged_ids:
            unstaged.append(shot.order_no)
        prompts, motion, missing = _production_inputs(db, shot)
        if "motion" in missing:
            invalid_motion.append(shot.order_no)
        revision = _production_revision(prompts, motion)
        if any(
            frame is not None
            and (frame.params_json or {}).get("production_revision") != revision
            for frame in (first, last)
        ):
            stale_prompts.append(shot.order_no)

    # 声音制作单必须真正编译成规格。仅仅“写过声音设计”不算完成；
    # 反过来，制作单明确写无配乐／静默时也不能硬造一条声音。
    from app.pipelines.soundscape import (
        K_AMBIENCE, K_MUSIC, K_OFFSCREEN, K_SFX, _is_none, _payload_en,
        _split_cues,
    )

    soundscape_gaps: list[str] = []

    def requested(sheet: CrewSheet, key: str) -> tuple[str, str] | None:
        cn, en = _payload_en(sheet, key)
        if not cn or _is_none(cn) or _is_none(en):
            return None
        return cn, en

    for shot in shots:
        sheet = sound_sheet_by_shot.get(shot.id)
        if sheet is None:
            continue
        expected = sum(
            len(_split_cues(pair[0]))
            for key in (K_SFX, K_OFFSCREEN)
            if (pair := requested(sheet, key)) is not None
        )
        actual = sum(
            1 for spec in by_shot.get(shot.id, [])
            if spec.kind == AudioKind.sfx
            and (spec.params_json or {}).get("source") == "sound_sheet"
        )
        if actual < expected:
            soundscape_gaps.append(
                f"镜 {shot.order_no} 的声音单要求 {expected} 个音效点，只编译了 {actual} 个"
            )

    for scene_id, members in _shots_by_scene(shots).items():
        sheet = next(
            (sound_sheet_by_shot[s.id] for s in members
             if s.id in sound_sheet_by_shot), None,
        )
        if sheet is None:
            continue
        for key, kind, label in (
            (K_AMBIENCE, AudioKind.ambience, "环境床"),
            (K_MUSIC, AudioKind.bgm, "配乐"),
        ):
            if requested(sheet, key) is None:
                continue
            actual = any(
                spec.kind == kind
                and (spec.params_json or {}).get("source") == "sound_sheet"
                for spec in by_scene.get(scene_id, [])
            )
            if not actual:
                soundscape_gaps.append(f"场 {scene_id[-6:]} 的{label}制作单尚未编译")

    pace = runtime_window(chapter.content if chapter else "")
    blockers: list[str] = []
    if placeholder_shots:
        blockers.append(f"{len(placeholder_shots)} 镜还在用静帧或黑屏代替动态视频")
    if gaps:
        blockers.append(f"{len(gaps)} 个画面／声音素材缺口")
    if still_shots:
        blockers.append(f"{len(still_shots)} 镜没有可见的首尾变化")
    if duplicate:
        blockers.append(f"{len(duplicate)} 组镜头复用了同一变化")
    if needs_coverage:
        blockers.append(f"{len(needs_coverage)} 镜超过单支 i2v 的可信时长，还缺补充机位")
    if incomplete_crew:
        blockers.append(f"{len(incomplete_crew)} 镜的八工种制作单不完整")
    if unstaged:
        blockers.append(f"{len(unstaged)} 个有人物的镜头缺站位、视线与表演调度")
    if invalid_motion:
        blockers.append(f"{len(invalid_motion)} 镜缺完整物理运动链")
    if stale_prompts:
        blockers.append(f"{len(stale_prompts)} 镜的提示词早于最新制作单，必须重新拼装")
    if soundscape_gaps:
        blockers.append(f"{len(soundscape_gaps)} 处声音制作单尚未编译成可生成规格")
    if cursor < pace["min_ms"]:
        blockers.append(
            f"成片仅 {cursor/60000:.1f} 分钟，低于本章信息量的紧凑下限 "
            f"{pace['min_ms']/60000:.1f} 分钟；需补视觉叙事与反应机位"
        )
    if cursor > pace["max_ms"]:
        blockers.append(
            f"成片 {cursor/60000:.1f} 分钟，超过单集节奏上限 "
            f"{pace['max_ms']/60000:.1f} 分钟；需压缩或拆集"
        )
    quality = {
        "grade": "final" if not blockers else "preview",
        "production_ready": not blockers,
        "blockers": blockers,
        "placeholder_shots": placeholder_shots,
        "actual_video_shots": len(shots) - len(set(placeholder_shots)),
        "total_shots": len(shots),
        "runtime_window": pace,
        "incomplete_crew_shots": incomplete_crew,
        "unstaged_shots": unstaged,
        "invalid_motion_shots": invalid_motion,
        "stale_prompt_shots": stale_prompts,
        "soundscape_gaps": soundscape_gaps,
    }

    return {
        "chapter": {"id": chapter.id if chapter else None,
                    "title": chapter.title if chapter else None,
                    "novel_id": chapter.novel_id if chapter else None},
        "shot_plan_id": plan.id,
        "language": plan.target_language_code,
        "aspect_ratio": aspect, "fps": fps,
        "voiceover": False,
        "duration_ms": cursor,
        "shots": len(shots),
        "tracks": out_tracks,
        "gaps": gaps,
        "retimed": retimed,
        "needs_coverage": needs_coverage,
        "still_shots": still_shots,
        "duplicate_changes": duplicate,
        "quality": quality,
        "notes": "电影投影：无旁白；小说叙述由动作、反应、环境与视觉转场承担。",
    }


def _cn(track: str) -> str:
    return dict((t[0], t[1]) for t in TRACKS).get(track, track)


def _scene_of(shots: Sequence[Shot], order_no: int) -> str | None:
    for s in shots:
        if s.order_no == order_no:
            return s.scene_id
    return None


def _shots_by_scene(shots: Sequence[Shot]) -> dict[str, list[Shot]]:
    out: dict[str, list[Shot]] = {}
    for shot in shots:
        if shot.scene_id:
            out.setdefault(shot.scene_id, []).append(shot)
    return out


def _dur(spec: AudioSpec, assets: dict[str, Asset]) -> int:
    if spec.duration_ms:
        return int(spec.duration_ms)
    asset = assets.get(spec.asset_id or "")
    if asset is not None:
        return int((asset.meta_json or {}).get("duration_ms") or 0)
    return 0


def _at_ms(spec: AudioSpec, shot_dur: int) -> int:
    """音效在镜头内的相对位置。取不到就放开头 —— 不要编一个位置。"""
    at = (spec.params_json or {}).get("at_ms")
    try:
        return max(0, min(int(at), max(0, shot_dur - 200)))
    except (TypeError, ValueError):
        return 0


def _url(assets: dict[str, Asset], frame: FrameSpec | None) -> str | None:
    if frame is None or not frame.asset_id:
        return None
    a = assets.get(frame.asset_id)
    return a.url if a else None


def _url_by_id(assets: dict[str, Asset], aid: str | None) -> str | None:
    a = assets.get(aid or "")
    return a.url if a else None


def _empty(chapter, plan, aspect, fps, voiceover) -> dict[str, Any]:
    return {
        "chapter": {"id": chapter.id if chapter else None,
                    "title": chapter.title if chapter else None,
                    "novel_id": chapter.novel_id if chapter else None},
        "shot_plan_id": plan.id, "language": plan.target_language_code,
        "aspect_ratio": aspect, "fps": fps, "voiceover": False,
        "duration_ms": 0, "shots": 0,
        "tracks": [{"id": t, "name": n, "layer": l, "clips": [], "ready": 0, "total": 0}
                   for t, n, l in TRACKS],
        "gaps": [{"track": "video", "shot": 0, "why": "这一章还没有分镜",
                  "fix": "先到「剧本转换」编译分镜"}],
        "retimed": [], "needs_coverage": [], "still_shots": [],
        "duplicate_changes": [],
        "quality": {
            "grade": "preview", "production_ready": False,
            "blockers": ["还没有分镜"], "placeholder_shots": [],
            "actual_video_shots": 0, "total_shots": 0,
        },
        "notes": "这一章还没有分镜。",
    }


# ── 成片导出 ──────────────────────────────────────────────────────────────────

def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _local(url: str | None) -> Path | None:
    """把本地媒体 URL 换成磁盘路径。

    **只接本地产物。** 外部地址一律不下载 —— 导出要在几分钟内跑完，
    而一条外链卡住就是整段导出卡住，且看不出是卡在哪一个素材上。
    """
    from app.capability.mediastore import media_root

    if not url or "/media/" not in url:
        return None
    p = Path(media_root()) / url.rsplit("/media/", 1)[-1].split("?")[0]
    return p if p.exists() else None


def render(db: Session, plan: ShotPlan, *, voiceover: bool = False,
           width: int = 1280, height: int = 720, fps: int = 24,
           timeout_sec: int = 900) -> dict[str, Any]:
    """把时间线渲成一支 mp4。

    每镜一段：有视频用视频，没有就把首尾帧做成一段缓慢的交叉溶解 ——
    **静止两张图也远比黑屏有用**，而且一眼看得出这一镜还没出视频。
    声音按轨道混合，各轨音量固定（对白 0dB、音效 -6dB、环境声 -18dB、
    配乐 -20dB）—— 那是配音压过底噪的常规比例，不是随手定的。
    """
    from app.capability.mediastore import media_root, store_bytes

    if not ffmpeg_available():
        raise RuntimeError("这台机器上没有 ffmpeg，无法导出成片")

    tl = build_timeline(db, plan, voiceover=voiceover, fps=fps)
    if not tl["duration_ms"]:
        raise RuntimeError("时间线是空的，没有可导出的内容")
    doc = db.get(ScriptDoc, plan.script_doc_id)
    chapter = db.get(Chapter, doc.chapter_id) if doc else None

    video_clips = next(t["clips"] for t in tl["tracks"] if t["id"] == "video")
    work = Path(tempfile.mkdtemp(prefix="cut_"))
    try:
        segs: list[Path] = []
        missing: list[int] = []
        for c in video_clips:
            seg = work / f"seg_{c['shot']:04d}.mp4"
            secs = max(0.2, c["duration_ms"] / 1000)
            vid = _local(c.get("video_url"))
            first = _local(c.get("first_url"))
            last = _local(c.get("last_url"))
            if vid:
                cmd = ["ffmpeg", "-y", "-i", str(vid), "-t", f"{secs:.3f}",
                       "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                              f"crop={width}:{height},fps={fps}",
                       "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(seg)]
            elif first and last:
                # 首帧慢慢化到尾帧：这一镜的「变化」是有的，只是还没出视频
                cmd = ["ffmpeg", "-y", "-loop", "1", "-t", f"{secs:.3f}", "-i", str(first),
                       "-loop", "1", "-t", f"{secs:.3f}", "-i", str(last),
                       "-filter_complex",
                       f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
                       f"crop={width}:{height},fps={fps}[a];"
                       f"[1:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
                       f"crop={width}:{height},fps={fps}[b];"
                       f"[a][b]xfade=transition=fade:duration={max(0.4, secs*0.7):.3f}"
                       f":offset={max(0.1, secs*0.25):.3f}[v]",
                       "-map", "[v]", "-t", f"{secs:.3f}",
                       "-c:v", "libx264", "-pix_fmt", "yuv420p", str(seg)]
            elif first:
                cmd = ["ffmpeg", "-y", "-loop", "1", "-t", f"{secs:.3f}", "-i", str(first),
                       "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                              f"crop={width}:{height},fps={fps}",
                       "-c:v", "libx264", "-pix_fmt", "yuv420p", str(seg)]
            else:
                missing.append(c["shot"])
                cmd = ["ffmpeg", "-y", "-f", "lavfi",
                       "-i", f"color=c=black:s={width}x{height}:r={fps}",
                       "-t", f"{secs:.3f}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                       str(seg)]
            _run(cmd, timeout_sec)
            segs.append(seg)

        listfile = work / "segs.txt"
        listfile.write_text("".join(f"file '{p}'\n" for p in segs), encoding="utf-8")
        silent = work / "silent.mp4"
        _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
              "-c", "copy", str(silent)], timeout_sec)

        total_s = tl["duration_ms"] / 1000
        mixed = _mix_audio(tl, work, timeout_sec, total_s)
        out = work / "out.mp4"
        if mixed is None:
            shutil.copy(silent, out)
        else:
            # **不能用 -shortest。** 最后一句台词往往在片尾之前就说完了，
            # 于是音轨比画面短，-shortest 会把结尾几镜整个切掉 ——
            # 而被切掉的恰恰是安静的收尾镜，不播到最后根本发现不了。
            # 实跑里 168.7s 的片子被切成 161.9s，少了七秒。
            # 改成把音轨补静音到片长，画面长度说了算。
            _run(["ffmpeg", "-y", "-i", str(silent), "-i", str(mixed),
                  "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                  "-map", "0:v:0", "-map", "1:a:0",
                  "-t", f"{total_s:.3f}", str(out)], timeout_sec)

        media = store_bytes(out.read_bytes(), mime="video/mp4")
        quality = tl.get("quality") or {}
        meta = {
            "purpose": "final_cut",
            "chapter_id": chapter.id if chapter else None,
            "shot_plan_id": plan.id,
            "grade": quality.get("grade") or "preview",
            "quality_blockers": quality.get("blockers") or [],
            "duration_ms": tl["duration_ms"],
            "width": width, "height": height, "fps": fps,
            "voiceover": voiceover,
        }
        asset = db.execute(
            select(Asset).where(
                Asset.novel_id == (chapter.novel_id if chapter else None),
                Asset.url == str(media["url"]),
            )
        ).scalars().first()
        if asset is None:
            asset = Asset(
                id=new_id("as"), kind=AssetKind.video,
                url=str(media["url"]), sha256=str(media["sha256"]),
                mime=str(media["mime"]), bytes=int(media["bytes"]),
                meta_json=meta, source=AssetSource.generated,
                novel_id=chapter.novel_id if chapter else None,
            )
            db.add(asset)
        else:
            asset.meta_json = meta
        db.flush()
        return {
            "asset_id": asset.id, "url": media["url"], "bytes": media["bytes"],
            "duration_ms": tl["duration_ms"], "shots": len(video_clips),
            "voiceover": voiceover,
            "width": width, "height": height, "fps": fps,
            "grade": quality.get("grade") or "preview",
            "production_ready": bool(quality.get("production_ready")),
            "quality_blockers": quality.get("blockers") or [],
            # **黑屏的镜号要报出来。** 一支片子里几秒黑屏很容易被当成转场，
            # 而它其实是「这一镜什么都没有」
            "black_shots": missing,
            "note": (f"{len(missing)} 镜是黑屏（没有视频也没有首帧）"
                     if missing else "每一镜都有画面"),
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)


#: 各轨音量。对白 0dB 打底，其余依次压低 ——
#: 环境声与配乐若不压，对白会被盖住，而那是唯一承载信息的一轨
_GAIN_DB = {"dialogue": 0.0, "sfx": -6.0,
            "ambience": -18.0, "bgm": -20.0}


def _mix_audio(tl: dict[str, Any], work: Path, timeout_sec: int,
               total_s: float) -> Path | None:
    """把所有音频轨按时间码混成一条，**补静音到整片长度**。

    不补的话音轨止于最后一句台词，与画面对不齐；
    再配上 -shortest 就会把片尾几镜切掉。
    """
    inputs: list[str] = []
    filters: list[str] = []
    labels: list[str] = []
    n = 0
    for track in tl["tracks"]:
        if track["layer"] != "audio":
            continue
        gain = _GAIN_DB.get(track["id"], -6.0)
        for c in track["clips"]:
            path = _local(c.get("url"))
            if path is None:
                continue
            inputs += ["-i", str(path)]
            # adelay 的单位是毫秒，且**必须每声道各给一次**，
            # 只给一个值的话立体声素材只有左声道被延迟，右声道从 0 开始
            delay = max(0, int(c["start_ms"]))
            filters.append(
                f"[{n}:a]adelay={delay}|{delay},volume={gain}dB[a{n}]")
            labels.append(f"[a{n}]")
            n += 1
    if not n:
        return None
    out = work / "mix.m4a"
    graph = ";".join(filters) + ";" + "".join(labels) + (
        f"amix=inputs={n}:duration=longest:dropout_transition=0,"
        f"alimiter=limit=0.95,apad,atrim=0:{total_s:.3f}[m]")
    _run(["ffmpeg", "-y", *inputs, "-filter_complex", graph,
          "-map", "[m]", "-c:a", "aac", "-b:a", "192k", str(out)], timeout_sec)
    return out


def _run(cmd: list[str], timeout_sec: int) -> None:
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout_sec)
    if proc.returncode != 0:
        tail = proc.stderr.decode("utf-8", "replace")[-600:]
        raise RuntimeError(f"ffmpeg 失败（{cmd[-1]}）：{tail}")


def to_edl_json(tl: dict[str, Any]) -> str:
    """时间线的机器可读形态，给外部剪辑工具。"""
    return json.dumps(tl, ensure_ascii=False, indent=1)


# ── 图生视频 ──────────────────────────────────────────────────────────────────

def generate_videos(
    db: Session, plan: ShotPlan, *, limit: int = 0, regenerate: bool = False,
    max_ms: int | None = None,
) -> dict[str, Any]:
    """给镜头出 i2v。首尾帧都在的才发 —— 只有首帧的插不出运动。

    **limit 是必须的，不是可选的。** 一支 i2v 两三分钟、额度按次算，
    一章三十镜就是一小时和三十次额度。没有 limit 的话，
    一次手滑就把整月的额度花在一章上。

    max_ms 收住单支时长：i2v 在首尾帧之间插值，超过五秒就开始
    变成慢动作糊影 —— 那正是「看起来像 PPT」的另一半原因。
    """
    from app.capability.schemas import Capability
    from app.models import SpecStatus
    from app.pipelines.frame_compose import _production_inputs, _production_revision
    from app.pipelines.base import checkpoint
    from app.capability.service import submit_task
    from app.worldview.crew import CREW

    shots = list(db.execute(
        select(Shot).where(Shot.shot_plan_id == plan.id).order_by(Shot.order_no)
    ).scalars())
    sids = [s.id for s in shots]
    frames: dict[str, dict[str, FrameSpec]] = {}
    for f in db.execute(select(FrameSpec).where(FrameSpec.shot_id.in_(sids))).scalars():
        frames.setdefault(f.shot_id, {})[f.role.value] = f
    motions = {m.shot_id: m for m in db.execute(
        select(ShotMotion).where(ShotMotion.shot_id.in_(sids))).scalars()}
    required_roles = {item.role for item in CREW}
    crew_by_shot: dict[str, set[str]] = {}
    for sheet in db.execute(
        select(CrewSheet).where(CrewSheet.shot_id.in_(sids))
    ).scalars():
        if (sheet.prompt_en and not sheet.missing_json and not sheet.rejected_json):
            crew_by_shot.setdefault(sheet.shot_id, set()).add(sheet.role)
    assets = _assets(db, [f.asset_id for d in frames.values() for f in d.values()])

    doc = db.get(ScriptDoc, plan.script_doc_id)
    chapter = db.get(Chapter, doc.chapter_id) if doc else None

    todo: list[tuple[Shot, str, str, int]] = []
    skipped: list[dict[str, Any]] = []
    for shot in shots:
        if shot.video_asset_id and not regenerate:
            continue
        pair = frames.get(shot.id, {})
        a = _url(assets, pair.get(FrameRole.first.value))
        b = _url(assets, pair.get(FrameRole.last.value))
        if not a:
            skipped.append({"shot": shot.order_no, "why": "没有首帧"})
            continue
        if not b:
            # 只有首帧也能出，但那是「从一张图生一段运动」，
            # 模型自己编运动 —— 与分镜算好的首尾差异无关，说清楚
            skipped.append({"shot": shot.order_no,
                            "why": "只有首帧，没有尾帧；出来的运动是模型自己编的，"
                                   "与分镜算好的首尾差异无关"})
            continue
        if crew_by_shot.get(shot.id, set()) < required_roles:
            skipped.append({
                "shot": shot.order_no,
                "why": "八工种制作单不完整；不把未定的灯光、美术、声音与剪辑交给模型猜",
            })
            continue
        prompts, motion, _missing_production = _production_inputs(db, shot)
        if (motion is None or not motion.motion_prompt_en
                or len(motion.deltas_en_json or []) < 2
                or not motion.start_frame_en or not motion.end_frame_en):
            skipped.append({
                "shot": shot.order_no,
                "why": "缺经验收的英文物理运动；不让视频模型自己猜动作",
            })
            continue
        revision = _production_revision(prompts, motion)
        if any(
            (frame.params_json or {}).get("production_revision") != revision
            for frame in (pair[FrameRole.first.value], pair[FrameRole.last.value])
        ):
            skipped.append({
                "shot": shot.order_no,
                "why": "首尾帧提示词早于最新制作单；请重新绑定拼装并出帧",
            })
            continue
        action = sp.is_action_beat(
            shot.description, motion.subject_move)
        cap = max_ms or (sp.ACTION_MAX_MS if action else sp.STATIC_MAX_MS)
        todo.append((shot, a, b, min(shot.duration_ms, cap)))

    if limit:
        todo = todo[:limit]

    submitted = []
    for shot, a, b, dur in todo:
        motion = motions.get(shot.id)
        # 这里不再回落到只有一个运镜词的 prompt。上面的门禁保证了
        # 每支视频都有主动作、惯性、受力、光影、面部与连续性约束。
        prompt = motion.motion_prompt_en or ""
        task = submit_task(
            db, Capability.video_i2v,
            {"first_frame": {"url": a}, "last_frame": {"url": b},
             "prompt": prompt, "duration_ms": dur},
            purpose="shot_video", ref_kind="shot", ref_id=shot.id,
            novel_id=chapter.novel_id if chapter else None,
            chapter_id=chapter.id if chapter else None,
            force=regenerate,
        )
        out = (task.result_json or {}).get("video") or {}
        if out.get("url"):
            from app.models import Asset as _A

            asset = db.execute(
                select(_A).where(_A.gen_task_id == task.id,
                                 _A.url == out["url"])).scalars().first()
            if asset is not None:
                shot.video_asset_id = asset.id
                shot.status = SpecStatus.ready
        submitted.append({"shot": shot.order_no, "task": task.id,
                          "status": task.status.value,
                          "duration_ms": dur, "prompt": prompt[:60]})
        checkpoint(db)      # 一支视频两三分钟且按次计费，出一支落一支

    return {
        "submitted": len(submitted), "items": submitted,
        "skipped": skipped,
        "remaining": max(0, len([s for s in shots if not s.video_asset_id])),
    }


def _camera_text(shot: Shot) -> str:
    cam = shot.camera_json or {}
    bits = [str(cam.get("move") or "static").replace("_", " ")]
    if cam.get("speed") is not None:
        bits.append(f"speed {cam['speed']}")
    return ", ".join(bits)
