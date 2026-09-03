"""剪辑台 —— 把一章拼成能直接播放的时间线，以及能导出的成片。

前两种投影是 `delivery`（给下游程序的 JSON）与 `handoff`（给人照着手搓的
提示词）。这是第三种：**给眼睛和耳朵**。轨道排开、按时间码对齐、点一下能播。

它回答的是前两种回答不了的那个问题：**「拼起来到底是什么样」**。
分镜看着合理、每张图单看都不错、每句配音单听都对，
连起来却可能这一镜停三秒没事发生、下一镜台词还没说完就切了。
那只有播一遍才知道。

## 旁白不进视频

小说要旁白，影片不要 —— 影片里那些内容由画面承担。
原来的交付清单把旁白与对白同等对待（它服务的是有声书与视频两种下游），
到了剪辑台必须分开：`voiceover=False` 时旁白整轨不出现。

**这会改变镜头长度。** 镜头时长本来按「对白+旁白」的真实时长回填，
一个只有旁白的镜头因此长达九秒；旁白拿掉后，那九秒就没有依据了 ——
画面停在那里不动，观众会以为卡住了。所以无旁白投影要按「画面拍子」
重算这类镜头的长度，并把改动报出来。

## 时长权威仍然是音频

有对白的镜头，长度由对白决定，不由分镜时的估算决定 ——
这条在前两种投影里就是这样，这里不能例外，否则同一章在
剪辑台和交付清单里长度不一样，而两边都说自己是对的。
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Asset, AudioKind, AudioSpec, Chapter, FrameRole, FrameSpec, Scene,
    ScriptDoc, Shot, ShotMotion, ShotPlan, WorldEntity,
)

log = logging.getLogger(__name__)


#: 轨道。顺序即**叠放顺序**：先画面后声音，声音里对白在最上层 ——
#: 剪辑软件里也是这么排的，换个顺序人会找不到。
TRACKS: tuple[tuple[str, str, str], ...] = (
    ("video", "画面", "visual"),
    ("dialogue", "对白", "audio"),
    ("narration", "旁白", "audio"),
    ("sfx", "音效", "audio"),
    ("ambience", "环境声", "audio"),
    ("bgm", "配乐", "audio"),
)

#: 没有对白的镜头给多长。**不是随便定的**：
#: 一个只有画面的镜头低于两秒观众来不及看清，高于五秒开始觉得卡住。
#: 只在旁白被拿掉、镜头失去时长依据时才用到。
_BEAT_MS = 2600
_BEAT_MIN = 1600
_BEAT_MAX = 5200

#: 对白前后各留一点，否则切点压在字上
_PAD_MS = 200


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
    base = _BEAT_MS
    if motion is not None and (motion.camera_move or motion.subject_move):
        base += 700
    return max(_BEAT_MIN, min(base, _BEAT_MAX))


def build_timeline(
    db: Session, plan: ShotPlan, *, voiceover: bool = False,
    fps: int = 24,
) -> dict[str, Any]:
    """把一章排成可播放的时间线。

    voiceover=False（默认，影片）：旁白不出现，只有旁白的镜头按画面拍子给长度。
    voiceover=True（有声书式）：旁白照常，与对白同轨排列。
    """
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
    if voiceover:
        voiced_kinds.add(AudioKind.narration)

    clips: dict[str, list[dict[str, Any]]] = {t[0]: [] for t in TRACKS}
    gaps: list[dict[str, Any]] = []
    retimed: list[dict[str, Any]] = []
    cursor = 0

    for shot in shots:
        specs = sorted(by_shot.get(shot.id, []),
                       key=lambda a: (a.kind != AudioKind.dialogue, a.id))
        voiced = [s for s in specs if s.kind in voiced_kinds]
        voiced_ms = sum(_dur(s, assets) for s in voiced)

        # **镜头长度：有台词按台词，没台词按画面拍子。**
        # 不能沿用 shot.duration_ms —— 它是按「对白+旁白」回填的，
        # 拿掉旁白后一个只有旁白的镜头会剩下九秒空画面
        if voiced_ms:
            dur = voiced_ms + _PAD_MS * 2
        else:
            dur = _beat_ms(shot, motions.get(shot.id))
            if abs(dur - shot.duration_ms) > 500:
                retimed.append({
                    "shot": shot.order_no,
                    "from_ms": shot.duration_ms, "to_ms": dur,
                    "why": ("这一镜只有旁白，影片投影里旁白不出现，"
                            "按画面拍子重算" if specs else "这一镜没有音频，按画面拍子"),
                })

        pair = frames.get(shot.id, {})
        first = pair.get(FrameRole.first.value)
        last = pair.get(FrameRole.last.value)
        first_url = _url(assets, first)
        last_url = _url(assets, last)
        video_url = _url_by_id(assets, shot.video_asset_id)
        motion = motions.get(shot.id)

        if not (video_url or first_url):
            gaps.append({"track": "video", "shot": shot.order_no,
                         "why": "既没有视频也没有首帧，这一镜是黑的",
                         "fix": "去「章节工作台」出首帧"})

        clips["video"].append({
            "key": f"video:{shot.order_no}", "shot": shot.order_no,
            "start_ms": cursor, "duration_ms": dur,
            "video_url": video_url,
            # 没有视频时用首尾帧做一次交叉溶解 —— 静止两张图也比黑屏好，
            # 而且它正好说明了「这一镜还没出视频」
            "first_url": first_url, "last_url": last_url,
            "label": (shot.description or "").strip()[:48] or f"镜 {shot.order_no}",
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
            if spec.kind == AudioKind.narration and not voiceover:
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

    out_tracks = []
    for tid, name, layer in TRACKS:
        if tid == "narration" and not voiceover:
            continue
        items = sorted(clips[tid], key=lambda c: c["start_ms"])
        out_tracks.append({
            "id": tid, "name": name, "layer": layer, "clips": items,
            "ready": sum(1 for c in items
                         if c.get("ready") or c.get("video_url") or c.get("first_url")),
            "total": len(items),
        })

    return {
        "chapter": {"id": chapter.id if chapter else None,
                    "title": chapter.title if chapter else None,
                    "novel_id": chapter.novel_id if chapter else None},
        "shot_plan_id": plan.id,
        "language": plan.target_language_code,
        "aspect_ratio": aspect, "fps": fps,
        "voiceover": voiceover,
        "duration_ms": cursor,
        "shots": len(shots),
        "tracks": out_tracks,
        "gaps": gaps,
        "retimed": retimed,
        "notes": (
            "影片投影：**旁白不出现** —— 那是小说的手法，影片里由画面承担。"
            if not voiceover else
            "有声书投影：旁白与对白同轨排列。"
        ),
    }


def _cn(track: str) -> str:
    return dict((t[0], t[1]) for t in TRACKS).get(track, track)


def _scene_of(shots: Sequence[Shot], order_no: int) -> str | None:
    for s in shots:
        if s.order_no == order_no:
            return s.scene_id
    return None


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
        "aspect_ratio": aspect, "fps": fps, "voiceover": voiceover,
        "duration_ms": 0, "shots": 0,
        "tracks": [{"id": t, "name": n, "layer": l, "clips": [], "ready": 0, "total": 0}
                   for t, n, l in TRACKS if not (t == "narration" and not voiceover)],
        "gaps": [{"track": "video", "shot": 0, "why": "这一章还没有分镜",
                  "fix": "先到「剧本转换」编译分镜"}],
        "retimed": [],
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
        return {
            "url": media["url"], "bytes": media["bytes"],
            "duration_ms": tl["duration_ms"], "shots": len(video_clips),
            "voiceover": voiceover,
            "width": width, "height": height, "fps": fps,
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
_GAIN_DB = {"dialogue": 0.0, "narration": -1.0, "sfx": -6.0,
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
