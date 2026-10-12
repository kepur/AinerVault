"""第一章 20 镜：走 world-greybox 闭环端到端重跑（Codex preview-twenty-v3 的同一批镜头）。

  World DB（走廊 + 街道两个区域，整场一次表演） → 按 Codex 已审核首帧的卡片站位拟合每镜相机
  → Blender world_multicam 出白模/深度/骨架（check 失败有界修正 ≤2 轮）
  → LTX 2.5（网关，一次一个任务）：动作镜 layout 控制 + 首帧 + 现场生成声音；对白镜 a2v 台词驱动；无声近景 i2v
  → 逐镜 QA 闸门（positions / camera / motion / audio / mood），失败有界重渲 ≤2 次
  → 两段配乐（acestep）→ 拼成片（带声音 + 字幕轨）→ qa_report.json / .md

可断点续跑：状态在 var/world_greybox/chapter01/state.json。
用法：python -m scripts.world_greybox.run_chapter01 [--only 1,5] [--skip-music]
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

import httpx

from app.db import SessionLocal
from app.models import WorldTake
from app.worldmodel import blender_run, qa, staging
from app.worldmodel import compile as wc
from app.worldmodel import geometry as geo
from app.worldmodel import service as ws
from app.worldmodel.seeds import chapter01_corridor as ch1

REPO = Path(__file__).resolve().parents[5]
CORE_DIR = Path(__file__).resolve().parents[2]
MEDIA = CORE_DIR / "var" / "media"
CODEX = REPO.parent / "AiComicStudio" / "var" / "chapter-01" / "preview-twenty-v3"
OUT = REPO / "var" / "world_greybox" / "chapter01"
CORE = "http://127.0.0.1:8100"
GATEWAY = "http://127.0.0.1:7999"
LTX25 = "ltx-2.5-22b-distilled"
MAX_RETRY = 2          # 每镜最多重渲 2 次（共 3 次生成）
MAX_CHECK_ROUNDS = 2   # 白模 check 失败最多修正 2 轮

STYLE = ("2D anime cel animation, flat colors, clean line art. Keep every character's face, hair, body shape "
         "and clothes exactly as in the first frame.")
CAMERA_TEXT = {
    "hold": "Locked camera, no zoom.",
    "push_in": "The camera slowly dollies forward in one continuous gentle push-in, keeping the subjects framed.",
    "pull_out": "The camera gently pulls back to reveal the space around the subjects.",
    "pan_left": "One gentle horizontal camera pan to the left; no cuts.",
    "pan_right": "One gentle horizontal camera pan to the right; no cuts.",
    "truck_right": "The camera slides sideways to the right in one smooth tracking move; no cuts.",
    "truck_left": "The camera slides sideways to the left in one smooth tracking move; no cuts.",
    "crane_down": "The camera slowly lowers in one smooth crane-down move; no cuts.",
    "crane_up": "The camera slowly rises in one smooth crane-up move; no cuts.",
}
MOOD_TEXT = {
    "menace": "Tense, menacing, threatening atmosphere.", "fear": "Frightened, tense, trembling fear.",
    "violence": "A sudden, harsh, tense moment of school bullying, non-graphic.",
    "anger": "Angry, aggressive, harsh tone.", "pain": "Quiet pain, a tear in his eye, hurt.",
    "mockery": "Mocking, sneering laugh.", "contempt": "Cold contempt, a sneer of scorn.",
    "despair": "Broken despair, trembling, lonely.", "loneliness": "Lonely, empty evening, alone.",
}
ACTION_EN = {
    1: "In a 1990s school corridor, three delinquent boys corner the thin black-haired Thomas against the lockers. "
       "The bullies lean in and shift their weight menacingly; Thomas shrinks back.",
    3: "Thomas lowers his head, presses his back against the lockers and covers his trouser pockets with both hands. "
       "The bullies loom over him.",
    5: "The tall red-haired Tyler suddenly raises his hand and slaps Thomas across the face once; Thomas's head snaps "
       "aside and he recoils. Non-graphic.",
    7: "Close-up of Thomas: a thin trickle of blood at the corner of his mouth, tears welling in his eyes, he bites "
       "his lip to keep from crying. His mouth stays closed.",
}
NAMES = {"thomas": "Thomas", "brad": "Brad", "tyler": "Tyler", "kyle": "Kyle"}
SPEAKER_DESC = {"tyler": "the tall red-haired Tyler", "brad": "the stocky green-haired Brad",
                "thomas": "the thin black-haired Thomas"}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ------------------------------------------------------------------ 状态
def load_state() -> dict:
    p = OUT / "state.json"
    return json.loads(p.read_text()) if p.exists() else {"shots": {}}


def save_state(st: dict):
    (OUT / "state.json").write_text(json.dumps(st, ensure_ascii=False, indent=1))


def codex_run() -> dict:
    return json.loads((CODEX / "run.json").read_text())


def media_path(url: str) -> Path:
    return MEDIA / url.rsplit("/", 1)[-1]


# ------------------------------------------------------------------ 网关
def gateway(capability: str, model: str, inp: dict, key: str, ckpt: Path, timeout_s: int = 1800) -> dict:
    """一次一个网关任务；不抢占 core 正在跑的视频；任务 id 落盘可续。"""
    with httpx.Client(timeout=60) as c:
        task = json.loads(ckpt.read_text()) if ckpt.exists() else None
        if task:
            r = c.get(f"{GATEWAY}/cap/v1/tasks/{task['task_id']}")
            task = None if r.status_code == 404 else r.json()
            if task and task["status"] == "failed":
                task = None
        t0 = time.monotonic()
        if task is None:
            while True:
                try:
                    if not c.get(CORE + "/api/v2/gen-tasks/summary").json().get("active"):
                        break
                except Exception:  # noqa: BLE001  core 重载中：稍后再问
                    pass
                if time.monotonic() - t0 > timeout_s:
                    raise TimeoutError("等待 core 现有视频任务结束超时（未抢占）")
                time.sleep(5)
            r = c.post(GATEWAY + "/cap/v1/tasks", json={"capability": capability, "model": model,
                       "idempotency_key": key, "input": inp, "options": {"timeout_ms": timeout_s * 1000}})
            if r.status_code >= 400:
                raise RuntimeError(f"gateway {r.status_code}: {r.text[:400]}")
            task = r.json()
            ckpt.write_text(json.dumps({"task_id": task["task_id"]}))
            if "output" not in task:
                task = c.get(f"{GATEWAY}/cap/v1/tasks/{task['task_id']}").json()
        while task["status"] in ("submitted", "queued", "running"):
            if time.monotonic() - t0 > timeout_s:
                raise TimeoutError(f"网关任务 {task['task_id']} 超时")
            time.sleep(4)
            task = c.get(f"{GATEWAY}/cap/v1/tasks/{task['task_id']}").json()
        if task["status"] != "succeeded":
            raise RuntimeError(f"{capability} 失败：{json.dumps(task.get('error'), ensure_ascii=False)[:400]}")
        return task


def download(url: str, dest: Path) -> Path:
    with httpx.Client(timeout=300) as c:
        r = c.get(url)
        r.raise_for_status()
        dest.write_bytes(r.content)
    return dest


def first_url(obj) -> str | None:
    if isinstance(obj, dict):
        if isinstance(obj.get("url"), str):
            return obj["url"]
        for v in obj.values():
            u = first_url(v)
            if u:
                return u
    if isinstance(obj, list):
        for v in obj:
            u = first_url(v)
            if u:
                return u
    return None


def ff(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def b64(p: Path) -> str:
    return base64.b64encode(p.read_bytes()).decode()


# ------------------------------------------------------------------ 准备：世界 + 相机拟合
def take_of(db, n: int) -> tuple:
    perf = ws.performance_for_scene(db, ch1.STREET_SCENE_KEY if n in ch1.STREET_SHOTS else ch1.SCENE_KEY)
    return perf, db.query(WorldTake).filter_by(performance_id=perf.id, order_no=n).one()


def prepare(db, run: dict, st: dict):
    ch1.build(db)
    eid2name = {v["entity_id"]: k for k, v in ch1.ACTORS.items()}
    for s in ch1.SHOTS:
        n = s["n"]
        rec = st["shots"].setdefault(str(n), {})
        if rec.get("camera_fit") is not None or s["kind"] != "action":
            continue
        frame = run["completed"][str(n)]["frame"]
        if frame.get("binding_mode") != "card_layout":
            rec["camera_fit"] = {"skipped": "close card frame; designed camera"}
            continue
        perf, t = take_of(db, n)
        pl = {eid2name[m["source_id"]]: m["placement"] for m in frame["reference_manifest"][1:]
              if m.get("view_key", "").startswith("body_") and m.get("source_id") in eid2name}
        actors = {a: (geo.lerp_track(perf.tracks[a]["keys"], t.start_ms)[0], ch1.ACTORS[a]["height_m"]) for a in pl}
        if n in ch1.STREET_SHOTS:
            cam = ch1.street_camera()   # 街道首帧直接按地平线 + 机高标定（表演起点就是从这台相机反投影的）
            err = staging.placement_error(cam, actors, pl, ch1.FRAME_W, ch1.FRAME_H)
        elif pl == {k: list(v) for k, v in ch1.OPENING_PLACEMENTS.items()}:
            cam = ch1.opening_camera()  # 与开场同一张卡布局：直接用开场标定相机
            err = staging.placement_error(cam, actors, pl, ch1.FRAME_W, ch1.FRAME_H)
        else:
            # 只在走廊“储物柜在画左”的半圈里搜（相机在人群 -X 侧看 +X），防止拟合出镜像机位
            # 首帧里没有的人（此刻也在走廊里）不许挡住首帧人物；相机必须在两墙之间
            others = {a: (geo.lerp_track(tr["keys"], t.start_ms)[0], ch1.ACTORS[a]["height_m"])
                      for a, tr in perf.tracks.items() if a not in pl}
            cam, err = staging.fit_camera(actors, pl, ch1.FRAME_W, ch1.FRAME_H, az_range=(120, 241), others=others,
                                          free_y=(-1.0, 0.8), lens_choices=(24, 28, 35, 45, 55, 70),
                                          dists=(1.0, 1.4, 1.8, 2.2, 2.6, 3.2, 4.0, 5.0))
            err = min(err, 1e6)
        err = round(float(err), 5)
        rec["camera_fit"] = {"camera": cam, "error": err, "actors": sorted(pl)}
        if err <= 0.08:
            t.camera = {**cam, "move": t.camera.get("move"), "size": t.camera.get("size")}
            rec["camera_fit"]["applied"] = True
        else:
            rec["camera_fit"]["applied"] = False  # 卡片站位与世界里的位置对不上：保留设计机位，记录误差
        db.flush()
        log(f"shot {n}: camera fit err={err} applied={rec['camera_fit']['applied']}")
    db.commit()
    save_state(st)


# ------------------------------------------------------------------ 白模
def greybox(db, n: int, rec: dict, attempt: int, move_scale: float = 1.0) -> dict:
    perf, t = take_of(db, n)
    out = OUT / f"shot{n:02d}" / f"greybox_a{attempt}"
    take = ws.take_out(t)
    if move_scale != 1.0:
        mv = dict(take["camera"]["move"])
        mv["amount"] = round(float(mv["amount"]) * move_scale, 3)
        take["camera"] = {**take["camera"], "move": mv}
    snap = ws.snapshot(db, perf.world_id, perf.world_version, [perf.region_key])
    perf_d = ws.performance_out(perf)
    keep = (rec.get("camera_fit") or {}).get("actors")
    if keep:
        # 首帧里没有的人按“出画”处理（影视里的 cheat）：表演里他们还在原位，只是本镜白模不画，避免 layout 驱动多出人来
        hidden = sorted(set(perf_d["tracks"]) - set(keep))
        perf_d = {**perf_d, "tracks": {a: tr for a, tr in perf_d["tracks"].items() if a in keep}}
        take["focus"] = [a for a in (take.get("focus") or []) if a in keep]
        rec["hidden_off_camera"] = hidden
    fixes = []
    for rnd in range(MAX_CHECK_ROUNDS + 1):
        job = wc.compile_take_job(snap, perf_d, take, out_dir=str(out), resolution=(640, 384),
                                  actors_meta=ch1.ACTORS)
        m = blender_run.run(job, timeout_s=900, log_path=str(out / "blender.log"))
        chk = m["check"]
        if chk["ok"] or rnd == MAX_CHECK_ROUNDS:
            break
        cam = dict(take["camera"])
        pos, tgt = cam["pos"], cam["target"]
        if chk.get("camera_in_collision"):   # 机位进了墙：沿视线往人物方向挪 0.35m
            d = [tgt[i] - pos[i] for i in range(3)]
            L = math.sqrt(sum(x * x for x in d)) or 1
            cam["pos"] = [round(pos[i] + d[i] / L * 0.35, 3) for i in range(3)]
            fixes.append({"round": rnd, "fix": "camera_out_of_wall"})
        if chk.get("focus_out_of_frame"):    # 焦点人物出画：运镜幅度减半
            mv = dict(cam["move"])
            mv["amount"] = round(float(mv["amount"]) * 0.5, 3)
            cam["move"] = mv
            fixes.append({"round": rnd, "fix": "halve_move", "who": chk["focus_out_of_frame"][:3]})
        take["camera"] = cam
    rec.setdefault("greybox", []).append({"attempt": attempt, "dir": str(out), "check": chk, "fixes": fixes,
                                          "timings": m.get("timings"), "world_version": m.get("world_version")})
    return {"dir": out, "manifest": m, "camera_json": json.loads((out / "camera.json").read_text()),
            "move": take["camera"]["move"]}


# ------------------------------------------------------------------ 生成
def prompt_for(s: dict, attempt: int, failed: list[str], brief: dict) -> str:
    n, mv = s["n"], s["move"]["type"]
    parts = [STYLE]
    if s["kind"] == "speech":
        who = s["focus"][0]
        parts.append(f"{SPEAKER_DESC.get(who, NAMES[who])} speaks only the supplied dialogue, at the exact pace of "
                     "the audio. Clear matching lip shapes for every word; mouth closed before the first word and "
                     "after the last. Small natural head and shoulder movement, blinking.")
    elif s["kind"] == "inner":
        parts.append("Close-up of Thomas lost in thought, inner monologue: his mouth stays CLOSED the whole time. "
                     "His eyes glisten, his lip trembles, he slowly lowers his gaze; small breathing movement.")
    else:
        parts.append(ACTION_EN.get(n) or brief.get("action_en") or "")
        if n in (1, 3, 5, 9, 12, 14, 16, 18, 19):
            parts.append("Match the first frame and keep the same people, place and camera as the driver.")
    parts.append(CAMERA_TEXT.get(mv, ""))
    parts.append(MOOD_TEXT.get(s["mood"], ""))
    if s["kind"] in ("action", "inner"):
        parts.append("Audible room tone: " + ("quiet evening street ambience, slow footsteps." if n == 19 else
                     "school corridor ambience, shoe scuffs, clothing rustle; no speech, no music."))
    if attempt and "motion" in failed:
        parts.append("Clearly visible continuous body movement throughout the clip, never a still frame.")
    if attempt and "camera" in failed:
        parts.append("The camera movement must be clearly noticeable from start to end.")
    if attempt and "audio" in failed:
        parts.append("Clearly audible natural sound effects for the whole clip.")
    return " ".join(p for p in parts if p)


def generate(db, s: dict, run: dict, rec: dict, attempt: int, failed: list[str]) -> dict:
    n = s["n"]
    sd = OUT / f"shot{n:02d}"
    sd.mkdir(parents=True, exist_ok=True)
    comp = run["completed"][str(n)]
    frame = comp["frame"]
    brief = frame.get("director_brief") or {}
    seed = 31000 + n * 10 + attempt
    prompt = prompt_for(s, attempt, failed, brief)
    gb = None
    layout = s["kind"] == "action" and frame.get("binding_mode") == "card_layout"
    close = frame.get("binding_mode") == "card_close"
    W, H = (384, 256) if close else (640, 384)
    inp = {"prompt": prompt, "first_frame": {"url": CORE + frame["url"]}, "width": W, "height": H,
           "fps": s["fps"], "duration_ms": s["dur"], "params": {"seed": seed, "stage2_steps": 2}}
    voice = CODEX / f"voice-{n:02d}.wav"
    if layout:
        scale = 1.5 if (attempt and "camera" in failed) else 1.0
        gb = greybox(db, n, rec, attempt, scale)
        inp["control"] = {"type": "layout", "video": {"b64": b64(gb["dir"] / "clay.mp4")}}
        inp["audio"] = {"mode": "generate"}
        route = "ltx25_layout(world greybox clay)"
    elif s["kind"] == "speech":
        inp["motion"] = "animate"
        inp["audio"] = {"mode": "drive", "track": {"b64": b64(voice)}}
        route = "dialogue_a2v(voice drive)"
    else:
        inp["motion"] = "animate"
        inp["audio"] = {"mode": "generate"}
        route = "ltx25_i2v(audio generate)" + (" + voice-over mix" if voice.exists() else "")
    log(f"shot {n} attempt {attempt}: {route} {W}x{H}@{s['fps']} {s['dur']}ms seed={seed}")
    task = gateway("video.image_to_video", LTX25, inp, f"world-greybox-ch01:s{n:02d}:a{attempt}:v2",
                   sd / f"task_a{attempt}.json")
    raw = download(task["output"]["video"]["url"], sd / f"raw_a{attempt}.mp4")
    out = raw
    post = []
    if s["kind"] == "inner" and voice.exists():  # 内心独白：嘴不动，台词作画外音混进去
        out = sd / f"vo_a{attempt}.mp4"
        ff("-i", str(raw), "-i", str(voice), "-filter_complex",
           "[0:a]volume=0.5[a0];[1:a]volume=1.0[a1];[a0][a1]amix=inputs=2:duration=first:normalize=0[a]",
           "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-ar", "48000", str(out))
        post.append("voice_over_mix")
    return {"attempt": attempt, "route": route, "seed": seed, "prompt": prompt, "task_id": task["task_id"],
            "video": str(out), "raw": str(raw), "greybox": gb, "post": post, "size": [W, H]}


def add_foley(n: int, video: Path, attempt: int) -> Path:
    """声音闸门的有界补救：mmaudio 按画面配环境声/动作声（只在生成音轨近乎静音时用）。"""
    sd = OUT / f"shot{n:02d}"
    prompt = ("quiet evening street ambience, slow footsteps" if n == 19 else
              "indoor school corridor ambience, shoe scuffs, clothing rustle, body movement")
    rel = video.relative_to(REPO) if False else None  # noqa
    # 网关要可取的地址：把片段放进 core media（内容寻址文件名）
    import hashlib
    h = hashlib.sha256(video.read_bytes()).hexdigest()
    dst = MEDIA / f"{h}.mp4"
    if not dst.exists():
        shutil.copy(video, dst)
    task = gateway("audio.foley", "mmaudio-large-44k-v2",
                   {"video": {"url": f"{CORE}/media/{h}.mp4"}, "prompt": prompt, "params": {"steps": 10, "seed": 400 + n}},
                   f"world-greybox-ch01:foley:s{n:02d}:a{attempt}:v1", sd / f"foley_a{attempt}.json", timeout_s=900)
    return download(first_url(task["output"].get("video") or task["output"]), sd / f"foley_a{attempt}.mp4")


def composite_move(n: int, video: Path, move: str, attempt: int) -> Path:
    """镜头运动闸门最后一道：合成层推镜（诚实标注 composited），不改原生成内容。"""
    sd = OUT / f"shot{n:02d}"
    info = qa.probe(str(video))
    fps = info.get("fps") or 8
    W, H = info["width"], info["height"]
    frames = max(2, round(info["duration_s"] * fps))
    if move == "pull_out":
        z = f"1.10-0.10*on/{frames}"
    else:
        z = f"1+0.10*on/{frames}"
    out = sd / f"comp_a{attempt}.mp4"
    ff("-i", str(video), "-vf", f"scale={W*2}:{H*2},zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={fps}",
       "-c:a", "copy", str(out))
    return out


# ------------------------------------------------------------------ QA
def music_cue_for(s: dict) -> str:
    return "despair" if s["start_ms"] >= MUSIC_SPLIT_MS else "tension"


MUSIC_SPLIT_MS = 0


def gate(s: dict, g: dict, run: dict) -> dict:
    frame = run["completed"][str(s["n"])]["frame"]
    voice = CODEX / f"voice-{s['n']:02d}.wav"
    vs = float(qa.probe(str(voice))["duration_s"]) if voice.exists() else None
    return qa.gate_shot(g["video"], kind=s["kind"], planned_move=s["move"]["type"], duration_s=s["dur"] / 1000,
                        mood=s["mood"], prompt=g["prompt"], first_frame=str(media_path(frame["url"])),
                        greybox=(g["greybox"] or {}).get("camera_json"), voice_s=vs, music_cue=music_cue_for(s))


def run_shot(db, s: dict, run: dict, st: dict):
    n = s["n"]
    rec = st["shots"].setdefault(str(n), {})
    if rec.get("final"):
        return
    rec.setdefault("attempts", [])
    failed: list[str] = []
    best = None
    for attempt in range(len(rec["attempts"]), MAX_RETRY + 1):
        try:
            g = generate(db, s, run, rec, attempt, failed)
        except Exception as e:  # noqa: BLE001
            log(f"shot {n} attempt {attempt} ERROR {e}")
            rec["attempts"].append({"attempt": attempt, "error": str(e), "trace": traceback.format_exc()[-1500:]})
            save_state(st)
            continue
        q = gate(s, g, run)
        # 有界补救（不算新生成）：静音 → mmaudio 配音效；对白/近景机位没动 → 合成推镜
        if not q["audio"]["ok"] and s["kind"] == "action" and q["audio"]["rms_db"] <= qa.TH["audio_rms_db"]:
            try:
                g["video"] = str(add_foley(n, Path(g["video"]), attempt))
                g["post"].append("mmaudio_foley")
                q = gate(s, g, run)
            except Exception as e:  # noqa: BLE001
                g["post"].append(f"foley_failed: {e}")
        if not q["camera"]["ok"] and attempt == MAX_RETRY:
            g["video"] = str(composite_move(n, Path(g["video"]), s["move"]["type"], attempt))
            g["post"].append("composited_camera_move")
            q = gate(s, g, run)
        gg = {k: v for k, v in g.items() if k != "greybox"}
        if g["greybox"]:
            gg["greybox_dir"] = str(g["greybox"]["dir"])
            gg["greybox_move"] = g["greybox"]["move"]
        rec["attempts"].append({**gg, "qa": q})
        save_state(st)
        log(f"shot {n} attempt {attempt}: pass={q['pass']} failed={q['failed']}")
        score = (q["pass"], -len(q["failed"]))
        if best is None or score > best[0]:
            best = (score, len(rec["attempts"]) - 1)
        if q["pass"]:
            break
        failed = q["failed"]
    ok_attempts = [i for i, a in enumerate(rec["attempts"]) if "qa" in a]
    if ok_attempts:
        bi = max(ok_attempts, key=lambda i: (rec["attempts"][i]["qa"]["pass"], -len(rec["attempts"][i]["qa"]["failed"])))
        rec["final"] = {"attempt_index": bi, "video": rec["attempts"][bi]["video"],
                        "pass": rec["attempts"][bi]["qa"]["pass"], "failed": rec["attempts"][bi]["qa"]["failed"]}
    save_state(st)


# ------------------------------------------------------------------ 配乐 + 成片
def music(st: dict, total_ms: int):
    cues = [("tension", 0, MUSIC_SPLIT_MS,
             "tense dark cinematic underscore, low strings pulse, muted percussion, menacing, school bullying scene, instrumental",
             92, "D minor"),
            ("despair", MUSIC_SPLIT_MS, total_ms,
             "slow sad piano and soft strings, lonely, despair, quiet evening, instrumental", 66, "A minor")]
    st.setdefault("music", {})
    for name, a, b, p, bpm, key in cues:
        if st["music"].get(name):
            continue
        dur = b - a + 500
        try:
            task = gateway("audio.music", "acestep-1.5-turbo",
                           {"prompt": p, "duration_ms": dur, "params": {"bpm": bpm, "keyscale": key, "seed": 77}},
                           f"world-greybox-ch01:music:{name}:v1", OUT / f"music_{name}.json", timeout_s=900)
            path = download(first_url(task["output"]), OUT / f"music_{name}.audio")
            wav = OUT / f"music_{name}.wav"
            ff("-i", str(path), "-ar", "48000", "-ac", "2", str(wav))
            st["music"][name] = {"path": str(wav), "start_ms": a, "end_ms": b, "prompt": p}
        except Exception as e:  # noqa: BLE001
            st["music"][name] = None
            st.setdefault("blockers", []).append(f"music {name}: {e}")
            log("music error", e)
        save_state(st)


def normalize(src: str, dst: Path, dur_s: float):
    ff("-i", src, "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-filter_complex",
       f"[0:v]scale=640:384:flags=lanczos,fps=24,tpad=stop_mode=clone:stop_duration=2,trim=duration={dur_s:.3f},setpts=PTS-STARTPTS[v];"
       f"[0:a]aresample=48000,aformat=channel_layouts=stereo,apad,atrim=duration={dur_s:.3f},asetpts=PTS-STARTPTS[a]",
       "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-c:a", "aac",
       "-b:a", "192k", str(dst))


def srt_time(ms: int) -> str:
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def finish(st: dict, tl: list[dict]) -> dict:
    parts = OUT / "parts"
    parts.mkdir(exist_ok=True)
    lst = []
    for s in tl:
        rec = st["shots"].get(str(s["n"]), {})
        src = (rec.get("final") or {}).get("video")
        dst = parts / f"{s['n']:02d}.mp4"
        if not src:
            # 没有任何可用生成：用 Codex 已审核首帧做静帧占位，并在报告里标为失败（不伪造）
            frame = codex_run()["completed"][str(s["n"])]["frame"]
            ff("-loop", "1", "-i", str(media_path(frame["url"])), "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
               "-t", f"{s['dur']/1000:.3f}", "-vf", "scale=640:384,fps=24", "-c:v", "libx264", "-pix_fmt", "yuv420p",
               "-c:a", "aac", str(dst))
            rec["placeholder"] = True
        else:
            normalize(src, dst, s["dur"] / 1000)
        lst.append(f"file '{dst}'")
    (parts / "list.txt").write_text("\n".join(lst))
    body = OUT / "body.mp4"
    ff("-f", "concat", "-safe", "0", "-i", str(parts / "list.txt"), "-c", "copy", str(body))
    srt = []
    i = 1
    for s in tl:
        if s["kind"] in ("speech", "inner"):
            srt.append(f"{i}\n{srt_time(s['start_ms'])} --> {srt_time(s['end_ms'])}\n{s['text']}\n")
            i += 1
    (OUT / "chapter01.srt").write_text("\n".join(srt))
    final = OUT / "chapter01_world_greybox.mp4"
    mus = [m for m in (st.get("music") or {}).values() if m]
    if mus:
        ins, flt = ["-i", str(body)], []
        for k, m in enumerate(mus, start=1):
            ins += ["-i", m["path"]]
            d = (m["end_ms"] - m["start_ms"]) / 1000
            flt.append(f"[{k}:a]atrim=duration={d:.3f},afade=t=in:d=0.6,afade=t=out:st={max(0, d-1.0):.3f}:d=1.0,"
                       f"volume=0.22,adelay={m['start_ms']}|{m['start_ms']}[m{k}]")
        mix = "".join(f"[m{k}]" for k in range(1, len(mus) + 1))
        flt.append(f"[0:a]{mix}amix=inputs={len(mus)+1}:duration=first:normalize=0[a]")
        ff(*ins, "-i", str(OUT / "chapter01.srt"), "-filter_complex", ";".join(flt), "-map", "0:v", "-map", "[a]",
           "-map", f"{len(mus)+1}:s", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-c:s", "mov_text",
           "-metadata:s:s:0", "language=eng", str(final))
    else:
        ff("-i", str(body), "-i", str(OUT / "chapter01.srt"), "-map", "0:v", "-map", "0:a", "-map", "1:s",
           "-c:v", "copy", "-c:a", "copy", "-c:s", "mov_text", str(final))
    return {"video": str(final), "probe": qa.probe(str(final))}


def report(st: dict, tl: list[dict], fin: dict):
    rows = []
    for s in tl:
        rec = st["shots"].get(str(s["n"]), {})
        fz = rec.get("final") or {}
        a = rec["attempts"][fz["attempt_index"]] if fz else {}
        q = a.get("qa") or {}
        rows.append({"shot": s["n"], "kind": s["kind"], "route": a.get("route"), "dur_s": s["dur"] / 1000,
                     "fps": s["fps"], "move": s["move"]["type"], "mood": s["mood"],
                     "attempts": len(rec.get("attempts", [])), "pass": bool(fz.get("pass")),
                     "failed": fz.get("failed", ["no_render"]) if fz else ["no_render"],
                     "post": a.get("post", []), "placeholder": bool(rec.get("placeholder")),
                     "camera_fit_err": (rec.get("camera_fit") or {}).get("error"),
                     "greybox_check": [g["check"]["ok"] for g in rec.get("greybox", [])],
                     "metrics": {"first_corr": (q.get("positions") or {}).get("first_frame_corr"),
                                 "energy_in_staging": (q.get("positions") or {}).get("motion_energy_in_staging"),
                                 "cam_scale": (q.get("camera") or {}).get("scale"),
                                 "cam_shift": [(q.get("camera") or {}).get("shift_x"), (q.get("camera") or {}).get("shift_y")],
                                 "mean_diff": (q.get("motion") or {}).get("mean_diff"),
                                 "nondup": (q.get("motion") or {}).get("nondup"),
                                 "audio_db": (q.get("audio") or {}).get("rms_db")}})
    rep = {"final": fin, "thresholds": qa.TH, "shots": rows, "music": st.get("music"),
           "blockers": st.get("blockers", []), "passed": sum(r["pass"] for r in rows), "total": len(rows)}
    (OUT / "qa_report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1))
    L = ["# Chapter 1 — world-greybox closed loop re-run — QA report", "",
         f"Final: `{fin['video']}` — {fin['probe']['duration_s']:.2f}s, {fin['probe']['width']}x{fin['probe']['height']}, audio={fin['probe']['has_audio']}",
         f"Passed all gates: {rep['passed']}/{rep['total']}", "",
         "Gates are automatic proxies (see app/worldmodel/qa.py); they do not replace watching the film.", "",
         "| # | kind | route | move | att | pass | failed | post | first_corr | energy_in | cam_scale | diff | audio dB |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        m = r["metrics"]
        L.append(f"| {r['shot']} | {r['kind']} | {r['route']} | {r['move']} | {r['attempts']} | {'✅' if r['pass'] else '❌'} | "
                 f"{','.join(r['failed'])} | {','.join(r['post'])} | {m['first_corr']} | {m['energy_in_staging']} | "
                 f"{m['cam_scale']} | {m['mean_diff']} | {m['audio_db']} |")
    if rep["blockers"]:
        L += ["", "## Blockers", *[f"- {b}" for b in rep["blockers"]]]
    (OUT / "qa_report.md").write_text("\n".join(L) + "\n")
    return rep


def main():
    global MUSIC_SPLIT_MS
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--skip-music", action="store_true")
    ap.add_argument("--no-finish", action="store_true")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    st = load_state()
    run = codex_run()
    tl = ch1.timeline()
    MUSIC_SPLIT_MS = next(s["start_ms"] for s in tl if s["n"] == 17)  # 钱被拿走之后转入绝望
    only = {int(x) for x in a.only.split(",") if x}
    db = SessionLocal()
    try:
        prepare(db, run, st)
        for s in tl:
            if only and s["n"] not in only:
                continue
            run_shot(db, s, run, st)
        if not a.skip_music:
            music(st, tl[-1]["end_ms"])
        if not a.no_finish:
            fin = finish(st, tl)
            save_state(st)
            rep = report(st, tl, fin)
            log("DONE", fin["video"], fin["probe"]["duration_s"], f"{rep['passed']}/{rep['total']} passed")
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
