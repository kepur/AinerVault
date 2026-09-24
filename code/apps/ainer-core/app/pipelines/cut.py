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
from app.pipelines.base import PipelineError

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


def dialogue_padding(shot: Shot) -> tuple[int, int]:
    """Explicit acting beats around speech; defaults preserve existing timing."""
    camera = shot.camera_json or {}
    return tuple(max(0, min(3000, int(camera.get(key, _PAD_MS))))
                 for key in ("dialogue_lead_ms", "dialogue_tail_ms"))


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

    优先用动作导演判的 action_ms —— 它看着首尾帧在判断「这个动作在现实里
    要多久」，比任何词表都准。

    ## 那个运动下限为什么不能无条件加

    原来是「有运动就至少 _BEAT_MS + 700（3.3 秒）」。它当初是防止视觉
    叙事镜被一律砍成 2.6 秒，但分镜现在已经按内容分档了（打斗 2 秒、
    对话 8 秒），下限就反过来跟分镜打架：

    实跑的镜 1 是一个 1.2 秒的动作拍子，被撑到 3.3 秒 —— 画面是 1.7 秒
    动作加 1.6 秒定格，而**声音是按撑过的槽排的**，于是整段听起来
    和看起来对不上。「打脸不需要五秒」正是在这里被撑回去的。

    所以下限只兜「分镜没给时长」的情况；分镜给了就信它。
    """
    natural = getattr(motion, "action_ms", None) if motion is not None else None
    if natural:
        return max(_BEAT_MIN, min(int(natural), _BEAT_MAX))
    planned = int(shot.duration_ms or 0)
    if planned:
        return max(_BEAT_MIN, min(planned, _BEAT_MAX))
    base = _BEAT_MS
    if motion is not None and (motion.camera_move or motion.subject_move):
        base = _BEAT_MS + 700
    return max(_BEAT_MIN, min(base, _BEAT_MAX))


def _motion_kind(shot: Shot) -> str:
    """读取新版三态动静标记，并兼容已经落库的 first_only 镜头。"""
    camera = shot.camera_json or {}
    kind = str(camera.get("motion_kind") or "").strip().lower()
    if kind in {"hold", "camera", "animate"}:
        return kind
    if camera.get("frame_mode") == "first_only":
        return "hold" if camera.get("held_reason") else "camera"
    return "animate"


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
        # held 是分镜阶段模型明示的「这一镜不动」。
        # **它优先于 is_action_beat 的关键词猜测** —— 后者是词表兜底
        # （打斗/挥刀/奔…），「他推开门走出去」一个词都不命中，
        # 会被判成静态给到 8 秒。模型的标注是判断，词表是猜。
        motion_kind = _motion_kind(shot)
        held = motion_kind == "hold"
        camera_only = motion_kind == "camera"
        action_beat = (not held) and sp.is_action_beat(
            shot.description, motion.subject_move if motion else None,
            motion.camera_move if motion else None)

        if voiced_ms:
            dur = voiced_ms + sum(dialogue_padding(shot))
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
        capped, cap_why = sp.clamp_shot_ms(dur, action=action_beat, held=held)
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
        last_url = (None if motion_kind in {"hold", "camera"}
                    else _url(assets, last))
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
        if held:
            # 真静态镜的目标就是保持。不能再把「没有首尾变化」当质量缺陷。
            vis_ok = True
            vis_why = "分镜明确指定真正静态镜"
        elif camera_only:
            planned = motions.get(shot.id)
            camera = planned.camera_move if planned else ""
            # 单首帧的动态镜靠连续运镜／口型／微表演，不需要伪造第二张静帧。
            vis_ok, _ = sp.is_camera_motion(
                camera, planned.motion_prompt_en if planned else None,
                planned.subject_move if planned else None,
            )
            vis_why = "camera 镜需要明确的连续运镜／口型／微表演"
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
        # A hand gesture during a short line is still one dialogue shot. Using
        # the action cap here repeats the same video from its first frame.
        if voiced_ms:
            seg_cap = sp.STATIC_MAX_MS          # 有台词：按台词切，声音连续
        elif held:
            seg_cap = sp.HELD_MAX_MS            # 无声定格，4 秒以上观众以为卡了
        elif action_beat:
            seg_cap = sp.ACTION_MAX_MS
        else:
            seg_cap = sp.STATIC_MAX_MS
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
                "motion_kind": motion_kind,
                "scene": (scenes.get(shot.scene_id or "").title
                          if scenes.get(shot.scene_id or "") else None),
                "kind": "video" if video_url else ("stills" if first_url else "black"),
            })

        local = dialogue_padding(shot)[0] if voiced_ms else 0
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
    intentional_static_shots = sorted({
        int(c["shot"]) for c in video_items
        if c.get("kind") == "stills" and c.get("motion_kind") == "hold"
    })
    placeholder_shots = sorted({
        int(c["shot"]) for c in video_items
        if c.get("kind") != "video" and c.get("motion_kind") != "hold"
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
    if (plan.config_json or {}).get("sample"):
        pace = {"source_units": 0, "min_ms": 1,
                "max_ms": (plan.config_json or {}).get("target_duration_ms", 30_000)}
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
    # **场记检查早就写好了，只是没人用。** crew_sheets.check_continuity 能查
    # 光位跳变、越轴、视线、道具凭空出现／消失，一直只挂在 GET /continuity 上，
    # 结果不进任何闸 —— 查出来也照样出片。
    #
    # 只拦 high（现在是越轴）：medium／low 照报不拦。道具出没、色温漂移那几类
    # 规则太粗，全拦的话告警立刻变成噪声，人就不看了。
    continuity = _continuity_report(db, plan)
    hard = [i for i in continuity.get("items", []) if i.get("severity") == "high"]
    if hard:
        blockers.append(
            f"{len(hard)} 处场记硬伤（越轴等），相邻镜头会让观众以为人物换了位置")
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
        "actual_video_shots": sum(1 for s in shots if s.video_asset_id),
        "intentional_static_shots": intentional_static_shots,
        "total_shots": len(shots),
        "runtime_window": pace,
        "incomplete_crew_shots": incomplete_crew,
        "unstaged_shots": unstaged,
        "invalid_motion_shots": invalid_motion,
        "stale_prompt_shots": stale_prompts,
        "soundscape_gaps": soundscape_gaps,
        "continuity": continuity,
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


def _continuity_report(db: Session, plan: ShotPlan) -> dict[str, Any]:
    """场记检查。查不了（没镜头、缺数据）就如实返回空，不让时间线跟着失败。"""
    from app.pipelines.crew_sheets import check_continuity

    try:
        return check_continuity(db, plan)
    except PipelineError:
        return {"total": 0, "items": [], "by_severity": {}, "by_kind": {}}


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
           width: int | None = None, height: int | None = None, fps: int = 24,
           timeout_sec: int = 900) -> dict[str, Any]:
    """把时间线渲成一支 mp4。

    每镜一段：有视频用视频，没有就把首尾帧做成一段缓慢的交叉溶解 ——
    **静止两张图也远比黑屏有用**，而且一眼看得出这一镜还没出视频。
    声音按轨道混合，各轨音量固定（对白 0dB、音效 -6dB、环境声 -18dB、
    配乐 -20dB）—— 那是配音压过底噪的常规比例，不是随手定的。

    不传尺寸就跟全局档位走 —— 素材是 832×480 而成片按 1280×720 渲，
    等于把每一帧放大一遍，糊，且白花时间。
    """
    from app.capability.mediastore import media_root, store_bytes
    from app.pipelines.frame_compose import _size_for

    if width is None or height is None:
        width, height = _size_for(
            (plan.config_json or {}).get("aspect_ratio") or "16:9")

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
                # **不足镜头槽的部分定格补足。**
                # 视频按动作的自然长度出（耳光 0.8 秒），而镜头槽可能是
                # 5 秒。只用 -t 截取的话这一段就只有 0.8 秒，后面每一镜
                # 连同声音一起往前错位 —— 而错位不会报错，只是嘴型对不上。
                # tpad 把最后一帧持续到槽满：定格远好过把动作拉成慢动作。
                cmd = ["ffmpeg", "-y", "-i", str(vid),
                       "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                              f"crop={width}:{height},fps={fps},"
                              f"tpad=stop_mode=clone:stop_duration={secs:.3f}",
                       "-t", f"{secs:.3f}",
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
    # **normalize=0 不能省。** amix 默认把每一路都除以输入数 —— 它假设
    # 这些路是同时在响的背景音。可这里的每一条都按时间码排在自己的位置上，
    # 同一时刻真正重叠的最多三条（对白＋环境声＋配乐）。
    #
    # 于是片子越长、片段越多，声音越小：整章 232 镜有上百条片段，
    # 每条被压掉 1/n，实测混出来 mean −57.4dB（源文件是 −16.3dB），
    # 等于全片静音。而这一路上没有任何一步报错 —— ffmpeg 成功、
    # 成片里有 aac 轨、时间线也报「四条轨就绪」，只是听不见。
    #
    # 两条镜头的小样反而是好的（n=2 只掉 6dB），所以试片时发现不了。
    # 重叠处的削顶交给后面的 alimiter，不该由 amix 提前把整片压平。
    graph = ";".join(filters) + ";" + "".join(labels) + (
        f"amix=inputs={n}:duration=longest:dropout_transition=0:normalize=0,"
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
    from app.pipelines.frame_compose import (
        _CJK, _production_inputs, _production_revision,
    )
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

    todo: list[tuple[Shot, str, str, int, str]] = []
    skipped: list[dict[str, Any]] = []
    for shot in shots:
        if shot.video_asset_id and not regenerate:
            continue
        motion_kind = _motion_kind(shot)
        if motion_kind == "hold":
            skipped.append({
                "shot": shot.order_no,
                "why": "真正静态镜由最终渲染器直接保持首帧，不调用视频模型",
            })
            continue
        pair = frames.get(shot.id, {})
        a = _url(assets, pair.get(FrameRole.first.value))
        b = _url(assets, pair.get(FrameRole.last.value))
        if not a:
            skipped.append({"shot": shot.order_no, "why": "没有首帧"})
            continue
        if not b and motion_kind != "camera":
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
        # 「字段名叫 _en」不等于「内容是英文」。存量运动单里有整段中文
        # 混在 motion_prompt_en 里，而 i2v 的门禁只看它非空 ——
        # 视频模型不认中文，那段节奏与物理约束等于没写过，
        # 而它正是「动起来像不像人」的关键一条。
        # 存量重出一遍运动单就好；这里只负责不让它花钱跑出废片。
        if _CJK.search(motion.motion_prompt_en or ""):
            skipped.append({
                "shot": shot.order_no,
                "why": "英文运动提示词里混着中文；请重出这一镜的运动单",
            })
            continue
        revision = _production_revision(prompts, motion)
        if any(
            (frame.params_json or {}).get("production_revision") != revision
            for frame in ([pair[FrameRole.first.value]] if motion_kind == "camera" else
                          [pair[FrameRole.first.value], pair[FrameRole.last.value]])
        ):
            skipped.append({
                "shot": shot.order_no,
                "why": "首尾帧提示词早于最新制作单；请重新绑定拼装并出帧",
            })
            continue
        # **时长按动作本身给，不按镜头槽摊。**
        # i2v 拿到多长就把动作铺满多长：一记耳光本来 0.8 秒，摊到 5 秒
        # 就是慢动作，而观众一眼看得出那不对。
        #
        # 从前是 min(镜头时长, 动作镜 2s / 对话镜 8s)，而「是不是动作镜」
        # 靠关键词猜 —— 猜不中就按 8 秒上限走，于是一批镜头全是慢动作。
        # 动作导演在写运动时本来就在判断这个动作怎么发生，让它一并给时长。
        #
        # 比镜头槽短的部分在渲染时定格补足；定格远好过慢动作。
        natural = getattr(motion, "action_ms", None)
        if natural:
            dur = max(400, min(int(natural), shot.duration_ms))
        else:
            # 同上：分镜标了静态就按静态，不让词表覆盖模型的判断
            if motion_kind == "camera":
                cap = max_ms or sp.STATIC_MAX_MS
            else:
                action = sp.is_action_beat(shot.description, motion.subject_move)
                cap = max_ms or (sp.ACTION_MAX_MS if action else sp.STATIC_MAX_MS)
            dur = min(shot.duration_ms, cap)
        todo.append((shot, a, b, dur, motion_kind))

    if limit:
        todo = todo[:limit]

    #: 交给工作台的 auto 档：让它**按实测像素差**判，而不是按我们的标签判。
    #:
    #: LTXV 是忠实插值器 —— 首尾帧一样，它会老老实实还你一段静止视频，
    #: 白烧 100 秒。auto 会先量差异，低于阈值就改走 ffmpeg 静帧（约 1 秒），
    #: 并在 motion_reason 里说明为什么。那句说明正是「这一镜的尾帧没改动，
    #: 该回炉重做」的依据 —— 比我们自己猜准。
    #:
    #: camera 档不映射成 kenburns：那是静帧缓推，会丢掉对白口型与呼吸，
    #: 而 camera 镜恰恰承担这些。只有下面「没有尾帧」那一支才强制 animate。
    _MOTION_MODE = {"camera": "auto", "animate": "auto"}

    submitted = []
    still_shots: list[dict[str, Any]] = []
    for shot, a, b, dur, motion_kind in todo:
        motion = motions.get(shot.id)
        # **每镜重算，别用上面那个循环留下的 motion_kind。**
        # 那是构建 todo 的循环里的变量，跑到这里只剩最后一镜的值，
        # 于是全部镜头共用同一个类型：最后一镜是 camera 就全体丢尾帧
        # （首尾帧控制整批失效），是 animate 就给 camera 镜塞上不该有的尾帧。
        # 两种都不会报错，只会让成片整体不对，而数据看着完全正常。
        motion_kind = _motion_kind(shot)
        # 这里不再回落到只有一个运镜词的 prompt。上面的门禁保证了
        # 每支视频都有主动作、惯性、受力、光影、面部与连续性约束。
        prompt = motion.motion_prompt_en or ""
        payload = {"first_frame": {"url": a}, "prompt": prompt, "duration_ms": dur,
                   "motion": _MOTION_MODE.get(motion_kind, "auto")}
        if b and motion_kind == "animate":
            payload["last_frame"] = {"url": b}
        else:
            # camera 镜只有首帧，但必须真的跑单帧驱动视频：它承担对白口型、
            # 呼吸和连续运镜。不能把首帧复制成尾帧，否则模型最终会回到原位。
            payload["motion"] = "animate"
        task = submit_task(
            db, Capability.video_i2v, payload,
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
        # **把它为什么没动记下来。** 静帧不是失败，是省了 100 秒；
        # 但「尾帧和首帧几乎一样」是上游的问题，不说出来就没人去修，
        # 而成片里那一镜看起来只是「有点闷」
        # 判定在 result 顶层，不在 result["video"] 里
        res = task.result_json or {}
        decision = str(res.get("motion_decision") or "")
        if decision in ("hold", "kenburns"):
            still_shots.append({
                "shot": shot.order_no,
                "decision": decision,
                "why": str(res.get("motion_reason") or ""),
                "frame_delta": res.get("frame_delta"),
                "fix": "尾帧相对首帧几乎没变 —— 回「分镜调度」重写变化说明再出尾帧",
            })
        submitted.append({"shot": shot.order_no, "task": task.id,
                          "status": task.status.value,
                          "duration_ms": dur, "prompt": prompt[:60],
                          "motion_decision": decision or None})
        checkpoint(db)      # 一支视频两三分钟且按次计费，出一支落一支

    return {
        "submitted": len(submitted), "items": submitted,
        "skipped": skipped,
        # 被判成静帧的镜头。省了钱，但每一条都是一个该修的尾帧
        "still_shots": still_shots,
        "remaining": max(0, len([
            s for s in shots
            if not s.video_asset_id and _motion_kind(s) != "hold"
        ])),
    }


def _camera_text(shot: Shot) -> str:
    cam = shot.camera_json or {}
    bits = [str(cam.get("move") or "static").replace("_", " ")]
    if cam.get("speed") is not None:
        bits.append(f"speed {cam['speed']}")
    return ", ".join(bits)
