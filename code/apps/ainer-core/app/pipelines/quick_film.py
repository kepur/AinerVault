"""快速成片（纳逗式一条龙）：一个想法 + 一张人物照片（+ 服装照片 / 场景图，可选）→ 2–4 镜带声短片。

不依赖小说、剧本、分镜表，给旅拍、相册、短视频这类外部系统直接调。全部本机：

1. 本机 LLM（LM Studio，路由 director_review）把想法拆成：场景、人物外观、2–4 个分镜（首帧静态描述 + LTX 运动描述），
   镜头之间首尾呼应（下一镜的首帧接上一镜的结尾）；
2. 人物照片 → 定妆照（FLUX.2-klein-edit：同一个人、全身、灰底、手自然下垂）；
3. 有服装照片：定妆照 + 服装照 → 换装定妆照（纳逗第二步，「滑雪定妆照」）；
4. 场景图：给了就用，没给就按 LLM 写的场景文生图（空镜、不带人）；
5. 每镜分镜图：场景图当底图 + 定妆照当身份参考；默认出 2 张，本机视觉模型对着定妆照挑一张；
6. 视频：
   - one_take（默认）：几镜叠在**一次** LTX 2.5 生成里 —— 第一镜分镜图钉第 0 帧，后面每镜的分镜图钉在它开始那一帧，
     segments 按时间给每镜的动作提示词，模型自带同步音轨；总长不超过 LTX 上限（20 秒）；
   - cuts：逐镜出（钉首帧），再拼成一支。

状态只放内存（core 重启就没了；已经出的图、视频都已落库，不会白出）。
"""
from __future__ import annotations

import json
import logging
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.capability.schemas import Capability
from app.db import SessionLocal
from app.ids import new_id
from app.models import GenTask, TaskStatus

log = logging.getLogger("ainer-core")

IMAGE_MODEL = "flux2-klein-4b-edit"
T2I_MODEL = "flux2-klein-4b"
VIDEO_MODEL = "ltx-2.5-22b-distilled"
PORTRAIT = (576, 1024)
FRAME = (800, 480)
VIDEO = (768, 448)
FPS = 24
MAX_SHOT_SEC = 5.0
#: LTX 2.5 一次最多 481 帧（20 秒）；留点余量
MAX_TAKE_MS = 19000
TASK_TIMEOUT_S = 40 * 60
POLL_S = 6.0
MODES = ("cuts", "one_take")

PLAN_SYSTEM = """You are a film director planning a very short cinematic film (2 to 4 shots, one location, one main character) for local image and video models.
Input: the creator's idea (any language), how many shots, whether an outfit photo and a location photo are provided.
Hard Rules:
- SEGMENT DURATION LIMIT: "seconds": 2 to 5 per shot. HARD LIMIT: NEVER exceed 5.0 seconds per shot.
- PHYSICAL LAWS & REALISM: Follow physical momentum, gravity, and material dynamics. In action/sports (e.g. skiing, falling), speed carries forward.
- CINEMATOGRAPHY: Vary shot sizes (e.g. wide WS -> close-up CU -> medium MS). Each shot has ONE primary camera movement. No 360 orbits or spins.
- CONTINUITY & TRANSITION (ANTI-STUTTER STANDARD):
  * If an action phase shifts (e.g. from skiing to tumbling, or from tumbling to standing), you MUST use a "cut" with a dramatic shot size change (e.g. WS -> CU). NEVER use "continuation" on an uncompleted action that causes the character to repeat falling/tumbling twice!
  * "cut": A deliberate perspective cut to a different shot size or angle (e.g. WS to ground CU).
  * "continuation": Only for smooth uninterrupted physical continuation without action resets.
- "first_frame": one static snapshot in English (<= 70 words): shot size and angle, pose, expression, gear.
- "motion": English for LTX-2 (<= 60 words, one paragraph): first sentence = main action, chronological details, last sentence = camera movement.
- "seconds": integer or float from 2.0 to 5.0 (NEVER > 5.0).
- "scene": English description of empty location, <= 60 words.
- "look": English description of character outfit, <= 40 words.
- "audio": one English line of grounded ambient sound.
- "title": a short Chinese title.
Output ONLY JSON: {"title": "...", "scene": "...", "look": "...", "audio": "...", "shots": [{"size": "ws|fs|ms|cu|ecu", "angle": "eye_level|low_angle|high_angle|dutch", "camera_move": "handheld_tracking|slow_push_in|dolly_pull_out|low_angle_pan|static_lock_off", "transition": "cut|continuation", "first_frame": "...", "motion": "...", "seconds": 3.0}]}"""

_LOCK = threading.Lock()
_JOBS: dict[str, dict[str, Any]] = {}


# ── 状态 ────────────────────────────────────────────────────────────────────

def get(job_id: str) -> dict[str, Any] | None:
    with _LOCK:
        j = _JOBS.get(job_id)
        return json.loads(json.dumps(j)) if j else None


def _set(job_id: str, **kw: Any) -> None:
    with _LOCK:
        _JOBS[job_id].update(kw)


def _out(job_id: str, kind: str, title: str, asset: tuple[str, str], **extra: Any) -> None:
    """登记一个产物（前端按顺序摆到画布上）。"""
    with _LOCK:
        _JOBS[job_id]["outputs"].append({"kind": kind, "title": title, "asset_id": asset[0], "url": asset[1], **extra})


def start(spec: dict[str, Any]) -> dict[str, Any]:
    jid = new_id("qf")
    with _LOCK:
        _JOBS[jid] = {"id": jid, "state": "running", "step": "plan", "error": None, "notes": [], "plan": None,
                      "outputs": [], "spec": {k: v for k, v in spec.items() if k != "idea"} | {"idea": spec.get("idea", "")[:500]},
                      "started_at": time.time()}
    threading.Thread(target=_run, args=(jid, spec), name=f"quick-film-{jid}", daemon=True).start()
    return get(jid) or {}


# ── 能力调用 ────────────────────────────────────────────────────────────────

def _submit(db, capability: Capability, model: str, payload: dict[str, Any], purpose: str):
    from app.capability.service import submit_task
    from app.pipelines.keyframe import _route

    route, _local, blocked = _route(db, capability.value, model)
    if route is None or blocked:
        raise RuntimeError(f"{model} 不能用：{blocked}")
    task = submit_task(db, capability, payload, purpose=purpose, ref_kind="quick_film", route=route, force=True)
    db.commit()
    return task


def _wait(db, task_ids: list[str]) -> dict[str, GenTask]:
    """等一批任务都结束（主动问网关）；返回 id → 任务。"""
    from app.capability.service import poll_task

    deadline = time.time() + TASK_TIMEOUT_S
    done: dict[str, GenTask] = {}
    while len(done) < len(task_ids) and time.time() < deadline:
        for tid in task_ids:
            if tid in done:
                continue
            db.expire_all()
            t = db.get(GenTask, tid)
            if t is not None and t.status not in (TaskStatus.succeeded, TaskStatus.failed, TaskStatus.cancelled):
                try:
                    t = poll_task(db, t)
                    db.commit()
                except Exception:                     # noqa: BLE001 —— 网关一时连不上：下一轮再问
                    db.rollback()
            if t is None or t.status in (TaskStatus.succeeded, TaskStatus.failed, TaskStatus.cancelled):
                done[tid] = t
        if len(done) < len(task_ids):
            time.sleep(POLL_S)
    if len(done) < len(task_ids):
        raise RuntimeError(f"{len(task_ids) - len(done)} 个任务超过 {TASK_TIMEOUT_S // 60} 分钟没出完")
    return done


def _asset(db, task: GenTask | None, kind: str = "image") -> tuple[str, str]:
    from app.models import Asset, AssetKind

    if task is None or task.status != TaskStatus.succeeded:
        msg = (task.error_json or {}).get("message") if task is not None and isinstance(task.error_json, dict) else None
        raise RuntimeError(msg or "任务失败")
    a = db.execute(select(Asset).where(Asset.gen_task_id == task.id, Asset.kind == AssetKind(kind))).scalars().first()
    if a is None:
        raise RuntimeError("任务成功了但没有产物")
    return a.id, a.url


def _image(db, prompt: str, *, base: str | None, refs: list[dict[str, Any]], size: tuple[int, int],
           seeds: list[int | None], purpose: str) -> list[tuple[str, str]]:
    """出图（有底图走图像编辑，没有走文生图），几个种子并排出；返回成功的产物。"""
    tids = []
    for seed in seeds:
        params = {"seed": seed} if seed is not None else {}
        if base:
            payload = {"image": {"url": base}, "prompt": prompt, "width": size[0], "height": size[1], "style": "photoreal",
                       "strength": 0.9, "reference_images": refs, "params": params}
            tids.append(_submit(db, Capability.image_i2i, IMAGE_MODEL, payload, purpose).id)
        else:
            payload = {"prompt": prompt, "width": size[0], "height": size[1], "style": "photoreal", "params": params}
            tids.append(_submit(db, Capability.image_t2i, T2I_MODEL, payload, purpose).id)
    got = _wait(db, tids)
    out = []
    for tid in tids:
        try:
            out.append(_asset(db, got.get(tid)))
        except RuntimeError as exc:
            log.warning("quick_film 出图失败 %s：%s", tid, exc)
    if not out:
        raise RuntimeError("这一步的图全部没出成")
    return out


def _ref(url: str, tag: str, identity: bool = True, role: str = "character") -> dict[str, Any]:
    # 网关（klein 编辑）只收 identity=true 的参考图，并跳过和底图相同的那张；服装、道具参考也得标 identity 才送得进去
    return {"ref": {"url": url}, "role": role, "identity": identity, "tag": tag}


def describe_outfit(db, url: str) -> str:
    """本机视觉模型把服装照写成一句英文（换装时文字 + 参考图一起给，klein 才肯换）。失败返回空串。"""
    from app.pipelines.director_review import _chat
    from app.pipelines.frame_select import data_url

    msg = [{"type": "text", "text": "Describe the clothing in this photo for an image model, in ONE English sentence "
                                    "(<= 40 words): garments, colours, patterns, materials, accessories. No other text."},
           {"type": "image_url", "image_url": {"url": data_url(url)}}]
    try:
        text, _model = _chat(db, "You describe garments precisely and briefly.", msg, purpose="frame_select",
                             max_tokens=1500, temperature=0.0)
    except Exception as exc:                          # noqa: BLE001 —— 描述不出来就只靠参考图
        log.warning("quick_film 服装描述失败：%s", exc)
        return ""
    import re
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip().strip('"')[:300]


# ── 规划 ────────────────────────────────────────────────────────────────────

def plan_idea(db, idea: str, n: int, *, has_outfit: bool, has_scene: bool) -> dict[str, Any]:
    from app.pipelines.director_review import _chat, parse_json

    user = json.dumps({"idea": idea, "shots": n, "outfit_photo": has_outfit, "location_photo": has_scene}, ensure_ascii=False)
    text, model = _chat(db, PLAN_SYSTEM, user, max_tokens=8000, temperature=0.5)
    data = parse_json(text)
    shots = []
    for i, s in enumerate(data.get("shots") or []):
        if not isinstance(s, dict) or not str(s.get("first_frame") or "").strip():
            continue
        shots.append({"size": str(s.get("size") or "ms").lower()[:3],
                      "angle": str(s.get("angle") or "eye_level").lower(),
                      "camera_move": str(s.get("camera_move") or "handheld_tracking").lower(),
                      "transition": str(s.get("transition") or ("continuation" if i > 0 else "cut")).lower(),
                      "first_frame": str(s["first_frame"]).strip()[:700],
                      "motion": str(s.get("motion") or "").strip()[:600],
                      "seconds": max(2.0, min(5.0, float(s.get("seconds") or 3))),
                      "audio": str(s.get("audio") or data.get("audio") or "")[:200]})
    if len(shots) < 1:
        raise RuntimeError("LLM 没拆出分镜")
    return {"title": str(data.get("title") or "快速成片")[:40], "scene": str(data.get("scene") or "")[:600],
            "look": str(data.get("look") or "")[:400], "audio": str(data.get("audio") or "")[:300],
            "shots": shots[:n], "model": model}


# ── 视频 ────────────────────────────────────────────────────────────────────

def take_layout(seconds: list[float], max_ms: int = MAX_TAKE_MS) -> list[tuple[int, int]]:
    """一镜一段：(start_ms, end_ms)。总长超上限就按比例压。"""
    total = sum(seconds) * 1000
    k = min(1.0, max_ms / total) if total else 1.0
    out, t = [], 0
    for s in seconds:
        d = int(round(s * 1000 * k))
        out.append((t, t + d))
        t += d
    return out


def one_take_payload(frames: list[str], motions: list[str], seconds: list[float], audio: str,
                     strength: float = 0.9) -> dict[str, Any]:
    """几镜叠一次生成：第一镜钉第 0 帧，后面每镜钉在它开始那一帧；segments 按时间给每镜的动作。"""
    spans = take_layout(seconds)
    total = spans[-1][1]
    nframes = int(round(total / 1000 * FPS)) + 1
    keys = []
    for (start, _end), url in list(zip(spans, frames))[1:]:
        idx = min(nframes - 2, max(1, int(round(start / 1000 * FPS))))
        keys.append({"image": {"url": url}, "frame_idx": idx, "strength": strength})
    lead = " ".join(m for m in motions if m)[:1500]
    return {
        "prompt": f"{lead}\n\nLive-action film footage, photorealistic, cinematic lighting, the same person throughout.\n\n"
                  f"Audio: {audio or 'natural ambient sound of the location'}. No dialogue.",
        "first_frame": {"url": frames[0]}, "keyframes": keys,
        "segments": [{"prompt": m, "start_ms": a, "end_ms": b} for m, (a, b) in zip(motions, spans)],
        "duration_ms": total, "width": VIDEO[0], "height": VIDEO[1], "fps": FPS, "quality": "final",
        "audio": {"mode": "generate"}, "params": {},
    }


def _extract_last_frame_ffmpeg(video_path: Path) -> bytes:
    """网关未返回 last_frame 时的 ffmpeg 本地兜底抽取。"""
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "last_frame.png"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-sseof", "-0.1", "-i", str(video_path),
                        "-update", "1", "-q:v", "2", str(out)], check=True, timeout=30)
        return out.read_bytes()


def _get_video_and_last_frame(db, task: GenTask | None) -> tuple[tuple[str, str], tuple[str, str] | None]:
    """获取生成的视频产物及尾帧（支持 DB 检索、网关返回及本地 FFmpeg 截取）。"""
    from app.capability.mediastore import store_bytes
    from app.models import Asset, AssetKind, AssetSource
    from app.pipelines.frame_select import _media_path

    if task is None or task.status != TaskStatus.succeeded:
        msg = (task.error_json or {}).get("message") if task is not None and isinstance(task.error_json, dict) else None
        raise RuntimeError(msg or "视频生成任务失败")

    vid = db.execute(select(Asset).where(Asset.gen_task_id == task.id, Asset.kind == AssetKind.video)).scalars().first()
    if vid is None:
        raise RuntimeError("视频任务成功但没有生成视频产物")

    lf = db.execute(select(Asset).where(Asset.gen_task_id == task.id, Asset.kind == AssetKind.image)).scalars().first()
    if lf is not None:
        return (vid.id, vid.url), (lf.id, lf.url)

    if isinstance(task.result_json, dict) and task.result_json.get("last_frame"):
        lf_url = task.result_json["last_frame"].get("url")
        if lf_url:
            return (vid.id, vid.url), (f"lf_{task.id}", lf_url)

    p = _media_path(vid.url)
    if p and p.exists():
        try:
            raw = _extract_last_frame_ffmpeg(p)
            stored = store_bytes(raw, mime="image/png")
            a = Asset(id=new_id("as"), kind=AssetKind.image, url=str(stored["url"]), mime="image/png",
                      source=AssetSource.generated, gen_task_id=task.id)
            db.add(a)
            db.commit()
            return (vid.id, vid.url), (a.id, a.url)
        except Exception as exc:
            log.warning("quick_film 截取尾帧兜底失败：%s", exc)

    return (vid.id, vid.url), None


def _concat(db, urls: list[str]) -> tuple[str, str]:
    """逐镜的片子拼成一支（重新编码，音轨一起接），存进媒体库。"""
    from app.capability.mediastore import store_bytes
    from app.models import Asset, AssetKind, AssetSource
    from app.pipelines.frame_select import _media_path

    paths = [_media_path(u) for u in urls]
    if any(p is None for p in paths):
        raise RuntimeError("有一镜的视频不在本地媒体库，拼不了")
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "film.mp4"
        inputs = sum((["-i", str(p)] for p in paths), [])
        n = len(paths)
        graph = "".join(f"[{i}:v][{i}:a]" for i in range(n)) + f"concat=n={n}:v=1:a=1[v][a]"
        try:
            subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", graph, "-map", "[v]", "-map", "[a]",
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(out)], check=True, timeout=600)
        except subprocess.CalledProcessError:
            graph_v = "".join(f"[{i}:v]" for i in range(n)) + f"concat=n={n}:v=1:a=0[v]"
            subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", graph_v, "-map", "[v]",
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)], check=True, timeout=600)
        stored = store_bytes(out.read_bytes(), mime="video/mp4")
    a = Asset(id=new_id("as"), kind=AssetKind.video, url=str(stored["url"]), mime="video/mp4",
              source=AssetSource.generated, meta_json={"quick_film": True, "parts": urls})
    db.add(a)
    db.commit()
    return a.id, a.url


# ── 主流程 ──────────────────────────────────────────────────────────────────

def _run(jid: str, spec: dict[str, Any]) -> None:
    from app.pipelines import frame_select
    from app.pipelines.keyframe import keyframe_prompt

    db = SessionLocal()
    try:
        n = max(2, min(4, int(spec.get("shots") or 3)))
        person, outfit, scene = spec["person_url"], spec.get("outfit_url"), spec.get("scene_url")
        cands = max(1, min(3, int(spec.get("candidates") or 2)))
        mode = spec.get("mode") if spec.get("mode") in MODES else "cuts"

        _set(jid, step="plan")
        plan = plan_idea(db, spec.get("idea") or "", n, has_outfit=bool(outfit), has_scene=bool(scene))
        _set(jid, plan=plan)

        _set(jid, step="look")
        wear = "" if outfit else (f" Wearing {plan['look']}." if plan.get("look") else "")
        look = _image(db, "Studio full-body photo of the same person as reference image 1: keep the face, hairstyle, "
                          "skin tone and body shape exactly." + wear + " Standing naturally facing the camera, arms relaxed "
                          "at the sides, whole body from head to shoes visible, plain mid-grey seamless background, soft even "
                          "light. One single person, no text.",
                      base=person, refs=[_ref(person, "person 1")], size=PORTRAIT, seeds=[None], purpose="quick_film_look")[0]
        _out(jid, "look", "定妆照", look)
        if outfit:
            _set(jid, step="outfit")
            wear = describe_outfit(db, outfit)
            _set(jid, notes=[f"服装：{wear}"] if wear else [])
            # 底图是定妆照（管脸和身形），服装照作第二张参考图（管衣服）；文字再说一遍衣服，klein 才肯真换
            look = _image(db, "Change only the clothes. The person in the first image now wears exactly the outfit from the "
                              f"second image{': ' + wear if wear else ''}. Remove the old clothes completely. Keep the same face, "
                              "hairstyle, skin tone and body. Full body, standing naturally facing the camera, arms relaxed, "
                              "plain mid-grey seamless background. One single person, no text.",
                          base=look[1], refs=[_ref(outfit, "outfit", role="style")],
                          size=PORTRAIT, seeds=[None], purpose="quick_film_look")[0]
            _out(jid, "look", "换装定妆照", look)

        # 多角度定妆照（头肩/3/4侧面视角，对标纳逗Pro多角度定妆照，方便近景与角度切换保持角色一致）
        multi_angle = None
        try:
            _set(jid, step="multi_angle")
            ma_res = _image(db, "Studio portrait shot of the same person from head to chest: keep the same face, "
                                "hairstyle, skin tone. Wearing the same outfit. "
                                "Three-quarter left angle, looking slightly to the side, natural expression, soft studio lighting, "
                                "plain mid-grey background. One single person, no text.",
                            base=look[1], refs=[_ref(look[1], "costume")], size=PORTRAIT, seeds=[None],
                            purpose="quick_film_look")
            if ma_res:
                multi_angle = ma_res[0]
                _out(jid, "look", "多角度定妆照", multi_angle)
        except Exception as exc:
            log.warning("quick_film 多角度定妆照生成跳过：%s", exc)

        _set(jid, step="scene")
        if scene:
            plate = scene
        else:
            got = _image(db, f"{plan['scene']} Wide establishing shot, empty, no people, photorealistic film still, natural light.",
                         base=None, refs=[], size=FRAME, seeds=[None], purpose="quick_film_scene")[0]
            _out(jid, "scene", "场景图", got)
            plate = got[1]

        motions = [s["motion"] or s["first_frame"] for s in plan["shots"]]
        seconds = [s["seconds"] for s in plan["shots"]]
        if mode == "one_take":
            # one_take 单次多关键帧生成模式
            frames: list[str] = []
            for i, sh in enumerate(plan["shots"]):
                _set(jid, step=f"frame:{i + 1}")
                prompt = keyframe_prompt(people=["the same person as the reference, same face, hair and outfit"], size=sh["size"],
                                         framing=sh["first_frame"], action="", location=plan["scene"], background="",
                                         has_plate=True)
                got = _image(db, prompt, base=plate, refs=[_ref(look[1], "person 1")], size=FRAME,
                             seeds=[101 + 17 * i + 9973 * k for k in range(cands)], purpose="quick_film_frame")
                choice = frame_select.pick(db, [("the character — reference portrait", look[1])], [u for _, u in got],
                                           sh["first_frame"])
                best = got[choice["best"]] if choice["best"] < len(got) else got[0]
                frames.append(best[1])
                _out(jid, "frame", f"分镜 {i + 1}", best, shot=i + 1, pick={"best": choice["best"], "of": len(got),
                                                                           "reason": choice["reason"]})

            _set(jid, step="video")
            task = _submit(db, Capability.video_i2v, VIDEO_MODEL, one_take_payload(frames, motions, seconds, plan["audio"]),
                           "quick_film_video")
            video = _asset(db, _wait(db, [task.id])[task.id], "video")
            _out(jid, "video", plan["title"], video)
        else:
            # cuts 逐镜物理接续与剪辑（解决潜空间连续形变，下一镜直接使用上一镜尾帧作为首帧，保证动量守恒与物理规律）
            parts: list[str] = []
            prev_last_frame: tuple[str, str] | None = None
            for i, sh in enumerate(plan["shots"]):
                _set(jid, step=f"shot:{i + 1}")
                is_cont = (sh.get("transition") == "continuation" and prev_last_frame is not None)

                if is_cont:
                    frame_url = prev_last_frame[1]
                    _out(jid, "frame", f"分镜 {i + 1}（尾帧接续）", prev_last_frame, shot=i + 1,
                         continuation=True, note="继承上一镜实际物理尾帧，保证动量守恒与光影连续")
                else:
                    _set(jid, step=f"frame:{i + 1}")
                    sh_size = sh.get("size", "ms").lower()
                    if sh_size in ("cu", "ecu", "mcu") and multi_angle:
                        prompt = f"Cinematic {sh_size.upper()} close-up shot: {sh['first_frame']}. Same character as reference. Natural film lighting."
                        got = _image(db, prompt, base=multi_angle[1], refs=[_ref(multi_angle[1], "person 1")],
                                     size=FRAME, seeds=[101 + 17 * i + 9973 * k for k in range(cands)], purpose="quick_film_frame")
                    else:
                        prompt = keyframe_prompt(people=["the same person as the reference, same face, hair and outfit"],
                                                 size=sh["size"], framing=sh["first_frame"], action="", location=plan["scene"],
                                                 background="", has_plate=True)
                        got = _image(db, prompt, base=plate, refs=[_ref(look[1], "person 1")], size=FRAME,
                                     seeds=[101 + 17 * i + 9973 * k for k in range(cands)], purpose="quick_film_frame")
                    choice = frame_select.pick(db, [("the character — reference portrait", look[1])], [u for _, u in got],
                                               sh["first_frame"])
                    best = got[choice["best"]] if choice["best"] < len(got) else got[0]
                    frame_url = best[1]
                    _out(jid, "frame", f"分镜 {i + 1}", best, shot=i + 1, pick={"best": choice["best"], "of": len(got),
                                                                               "reason": choice["reason"]})

                _set(jid, step=f"video:{i + 1}")
                motion_desc = sh.get("motion") or sh["first_frame"]
                if is_cont:
                    motion_desc = f"The action continues seamlessly from the initial frame. {motion_desc}"
                payload = {
                    "prompt": f"{motion_desc}\n\nLive-action film footage, photorealistic, cinematic lighting.\n\n"
                              f"Audio: {sh.get('audio') or plan['audio'] or 'natural ambient sound of the scene'}. No dialogue.",
                    "first_frame": {"url": frame_url},
                    "duration_ms": int(min(float(sh.get("seconds", 3.0)), MAX_SHOT_SEC) * 1000),
                    "width": VIDEO[0], "height": VIDEO[1],
                    "fps": FPS, "quality": "final",
                    "audio": {"mode": "generate"},
                    "params": {},
                }
                task = _submit(db, Capability.video_i2v, VIDEO_MODEL, payload, "quick_film_video")
                waited_task = _wait(db, [task.id])[task.id]
                vid, lf = _get_video_and_last_frame(db, waited_task)
                parts.append(vid[1])
                _out(jid, "clip", f"镜头 {i + 1}", vid, shot=i + 1)
                if lf:
                    prev_last_frame = lf
                    _out(jid, "last_frame", f"镜头 {i + 1} 尾帧", lf, shot=i + 1)

            _set(jid, step="concat")
            video = _concat(db, parts)
            _out(jid, "video", plan["title"], video)

        _set(jid, state="done", step="done", finished_at=time.time())
    except Exception as exc:                          # noqa: BLE001 —— 后台线程：错误放进状态给前端看
        db.rollback()
        log.warning("quick_film %s failed: %s", jid, exc)
        _set(jid, state="failed", error=str(exc)[:400], finished_at=time.time())
    finally:
        db.close()
