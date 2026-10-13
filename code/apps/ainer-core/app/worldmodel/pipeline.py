"""world-greybox 闭环：通用、可续跑的流水线作业（**可选路径**，默认关；见 app/worldmodel/switches.py）。

一次运行（WorldPipelineRun）= 一个世界里的若干场表演 + 一组镜头。步骤：
  build      世界：seed 模块 / LLM 章节 → delta（propose → apply）/ 已有世界
  stage      每场一次表演（world_check 有界修正）+ 每镜 take（时间窗 + 相机）
  fit        每镜相机按“原管线已审核首帧”的人物框拟合（设计机位已贴合就不动；方位窗 + 自由空间 + 遮挡约束）
  greybox    Blender 白模/深度/骨架 + 碰撞/入画检查（有界修正）
  generate   LTX 2.5：动作镜 layout（身份丢失时升级：union 深度+骨架 → 分段关键帧接力）；对白镜 a2v；近景 i2v
  qa         逐镜闸门（positions/identity、camera（与白模实测运镜对向）、motion、audio、mood），有界重渲
  sound      无声动作镜：mmaudio 配音效 → 仍静音则铺环境底噪（标注）
  select     每镜在 greybox 尝试与原管线成片之间选择：闸门过 → greybox；不过且允许回退 → 原管线（逐镜回退）
  music/concat/report

配置（run.config）里没有任何章节硬编码；第一章的配置由 seeds/chapter01_corridor.pipeline_config() 生成。
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import shutil
import subprocess
import time
import traceback
from pathlib import Path
from typing import Any, Callable

import httpx
from sqlalchemy.orm import Session

from app.models import WorldPerformance, WorldPipelineRun, WorldTake
from app.worldmodel import blender_run, qa, staging
from app.worldmodel import compile as wc
from app.worldmodel import geometry as geo
from app.worldmodel import service as ws

CORE_ROOT = Path(__file__).resolve().parents[2]
MEDIA = CORE_ROOT / "var" / "media"
DEFAULT_CORE = "http://127.0.0.1:8100"
DEFAULT_GATEWAY = "http://127.0.0.1:7999"
LTX25 = "ltx-2.5-22b-distilled"

STYLE = ("2D anime cel animation, flat colors, clean line art. Keep every character's face, hair, body shape "
         "and clothes exactly as in the first frame.")
CAMERA_TEXT = {
    "hold": "Locked camera, no zoom.",
    "push_in": "The camera slowly dollies forward in one continuous gentle push-in, keeping the subjects framed.",
    "zoom_in": "The camera slowly zooms in, keeping the subjects framed.",
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
    "violence": "A sudden, harsh, tense moment, non-graphic.", "anger": "Angry, aggressive, harsh tone.",
    "pain": "Quiet pain, a tear in the eye, hurt.", "mockery": "Mocking, sneering laugh.",
    "contempt": "Cold contempt, a sneer of scorn.", "despair": "Broken despair, trembling, lonely.",
    "loneliness": "Lonely, empty, alone.",
}
DEFAULTS = {"max_retry": 2, "max_check_rounds": 2, "resolution": [640, 384], "close_resolution": [384, 256],
            "fit_max_error": 0.08, "keep_designed_if_error_below": 0.012, "az_window_deg": 70,
            "fallback_to_original": True, "music_gain": 0.22, "room_tone_db": -34,
            # 只有这些镜头类型走白模；对白/内心/反应镜头直接用原管线的面部安全版（清晰脸 + 嘴型同步）
            "greybox_kinds": ["action"]}


class PipelineError(RuntimeError):
    pass


# ================================================================== 运行上下文
class Ctx:
    def __init__(self, db: Session, run: WorldPipelineRun, log: Callable[[str], None] | None = None):
        self.db, self.run = db, run
        self.cfg = {**DEFAULTS, **(run.config or {})}
        self.st: dict = run.state or {"shots": {}}
        self.out = Path(run.out_dir)
        self.out.mkdir(parents=True, exist_ok=True)
        self.core = self.cfg.get("core_url") or DEFAULT_CORE
        self.gateway_url = self.cfg.get("gateway_url") or DEFAULT_GATEWAY
        self._log = log or (lambda m: None)
        self._frames: dict | None = None

    def log(self, msg: str):
        line = time.strftime("%H:%M:%S") + " " + msg
        self._log(line)
        with open(self.out / "pipeline.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def save(self, progress: float | None = None, status: str | None = None):
        self.run.state = json.loads(json.dumps(self.st))   # 新对象，SQLAlchemy 才认 JSONB 变更
        if progress is not None:
            self.run.progress = round(progress, 4)
        if status:
            self.run.status = status
        self.db.commit()

    def shot_cfg(self, n: int) -> dict:
        return next(s for s in self.cfg["shots"] if s["n"] == n)

    def rec(self, n: int) -> dict:
        return self.st["shots"].setdefault(str(n), {})

    # ---- 原管线（动态漫剧）的首帧、站位、配音、成片
    def frames(self) -> dict:
        if self._frames is None:
            src = self.cfg.get("frames") or {}
            if src.get("type") == "comic_run":
                self._frames = json.loads(Path(src["path"]).read_text())["completed"]
            else:
                self._frames = {}
        return self._frames

    def frame(self, n: int) -> dict | None:
        c = self.frames().get(str(n))
        return (c or {}).get("frame")

    def face_safe(self) -> dict:
        """原管线面部安全版样片（如 Codex 的 twenty-shot preview）：整片 + shot-order.json 逐镜切点/帧率/时长。"""
        src = self.cfg.get("face_safe_source") or {}
        if not src.get("video") or not Path(src["video"]).exists():
            return {}
        if not hasattr(self, "_fs"):
            self._fs = {o["number"]: o for o in json.loads(Path(src["order"]).read_text())}
        return self._fs

    def original_clip(self, n: int) -> str | None:
        o = self.face_safe().get(n)
        if o:
            dst = self.out / "face_safe" / f"{n:02d}.mp4"
            if not dst.exists():
                dst.parent.mkdir(exist_ok=True)
                ff("-ss", f"{o['start_s']:.4f}", "-i", self.cfg["face_safe_source"]["video"], "-t", f"{o['duration_s']:.4f}",
                   "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(dst))
            return str(dst)
        c = self.frames().get(str(n)) or {}
        url = (c.get("asset") or {}).get("url")
        p = media_path(url) if url else None
        return str(p) if p and p.exists() else None

    def voice(self, n: int) -> Path | None:
        v = self.cfg.get("voices") or {}
        if not v.get("dir"):
            return None
        p = Path(v["dir"]) / v.get("pattern", "voice-{n:02d}.wav").format(n=n)
        return p if p.exists() else None


def media_path(url: str) -> Path:
    return MEDIA / url.rsplit("/", 1)[-1]


def b64(p: Path) -> str:
    return base64.b64encode(Path(p).read_bytes()).decode()


def ff(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def publish(p: Path, ext: str) -> str:
    """把本地文件放进 core media（内容寻址），返回 /media/... 相对地址，网关可取。"""
    h = hashlib.sha256(Path(p).read_bytes()).hexdigest()
    dst = MEDIA / f"{h}.{ext}"
    if not dst.exists():
        MEDIA.mkdir(parents=True, exist_ok=True)
        shutil.copy(p, dst)
    return f"/media/{h}.{ext}"


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


# ================================================================== 网关（一次一个任务；不抢 core 正在跑的视频）
def gateway(ctx: Ctx, capability: str, model: str, inp: dict, key: str, ckpt: Path, timeout_s: int = 1800) -> dict:
    with httpx.Client(timeout=60) as c:
        task = json.loads(ckpt.read_text()) if ckpt.exists() else None
        if task:
            r = c.get(f"{ctx.gateway_url}/cap/v1/tasks/{task['task_id']}")
            task = None if r.status_code == 404 else r.json()
            if task and task["status"] == "failed":
                task = None
        t0 = time.monotonic()
        if task is None:
            while True:
                try:
                    if not c.get(ctx.core + "/api/v2/gen-tasks/summary").json().get("active"):
                        break
                except Exception:  # noqa: BLE001
                    pass
                if time.monotonic() - t0 > timeout_s:
                    raise TimeoutError("等待 core 现有视频任务结束超时（未抢占）")
                time.sleep(5)
            r = c.post(ctx.gateway_url + "/cap/v1/tasks", json={"capability": capability, "model": model,
                       "idempotency_key": key, "input": inp, "options": {"timeout_ms": timeout_s * 1000}})
            if r.status_code >= 400:
                raise PipelineError(f"gateway {r.status_code}: {r.text[:400]}")
            task = r.json()
            ckpt.parent.mkdir(parents=True, exist_ok=True)
            ckpt.write_text(json.dumps({"task_id": task["task_id"]}))
            if "output" not in task:
                task = c.get(f"{ctx.gateway_url}/cap/v1/tasks/{task['task_id']}").json()
        while task["status"] in ("submitted", "queued", "running"):
            if time.monotonic() - t0 > timeout_s:
                raise TimeoutError(f"网关任务 {task['task_id']} 超时")
            time.sleep(4)
            task = c.get(f"{ctx.gateway_url}/cap/v1/tasks/{task['task_id']}").json()
        if task["status"] != "succeeded":
            raise PipelineError(f"{capability} 失败：{json.dumps(task.get('error'), ensure_ascii=False)[:400]}")
        return task


def download(url: str, dest: Path) -> Path:
    with httpx.Client(timeout=300) as c:
        r = c.get(url)
        r.raise_for_status()
        dest.write_bytes(r.content)
    return dest


# ================================================================== 世界与表演
def takes(ctx: Ctx) -> dict[int, tuple[WorldPerformance, WorldTake]]:
    out = {}
    for pid in ctx.cfg["performances"]:
        perf = ctx.db.get(WorldPerformance, pid)
        if perf is None:
            raise PipelineError(f"表演 {pid} 不存在")
        for t in ctx.db.query(WorldTake).filter_by(performance_id=perf.id):
            out[t.order_no] = (perf, t)
    return out


def _azimuth(cam: dict, center) -> float:
    return math.degrees(math.atan2(cam["pos"][1] - center[1], cam["pos"][0] - center[0])) % 360


def _free_space(ctx: Ctx, perf: WorldPerformance):
    """相机可以待的地方：区域包围盒内收 0.25m，且不在任何碰撞实例里。"""
    snap = ws.snapshot(ctx.db, perf.world_id, perf.world_version, [perf.region_key])
    region = next(r for r in snap["regions"] if r["key"] == perf.region_key)
    lo, hi = region["bounds_aabb"]["min"], region["bounds_aabb"]["max"]
    boxes = [i["aabb"] for i in snap["instances"] if i["region"] == perf.region_key and i.get("collision", True)]
    boxes = [b for b in boxes if b]

    def ok(p) -> bool:
        if not (lo[0] + 0.25 <= p[0] <= hi[0] - 0.25 and lo[1] + 0.25 <= p[1] <= hi[1] - 0.25):
            return False
        return not any(b["min"][0] - 0.15 <= p[0] <= b["max"][0] + 0.15 and b["min"][1] - 0.15 <= p[1] <= b["max"][1] + 0.15
                       and b["min"][2] <= p[2] <= b["max"][2] for b in boxes)
    return ok


def fit(ctx: Ctx):
    """每镜相机：原管线首帧里的人物框 → 世界机位。已拟合的不重做。"""
    W, H = ctx.cfg["frame_w"], ctx.cfg["frame_h"]
    actors_meta = ctx.cfg["actors"]
    eid2name = {v["entity_id"]: k for k, v in actors_meta.items()}
    for n, (perf, t) in sorted(takes(ctx).items()):
        rec = ctx.rec(n)
        if rec.get("camera_fit") is not None:
            continue
        frame = ctx.frame(n) or {}
        if frame.get("binding_mode") != "card_layout":
            rec["camera_fit"] = {"skipped": "no full-body layout frame; designed camera kept"}
            continue
        pl = {eid2name[m["source_id"]]: m["placement"] for m in frame.get("reference_manifest", [])[1:]
              if str(m.get("view_key", "")).startswith("body_") and m.get("source_id") in eid2name}
        if not pl:
            rec["camera_fit"] = {"skipped": "frame has no placed known actors"}
            continue
        actors = {a: (geo.lerp_track(perf.tracks[a]["keys"], t.start_ms)[0], actors_meta[a]["height_m"]) for a in pl}
        others = {a: (geo.lerp_track(tr["keys"], t.start_ms)[0], actors_meta[a]["height_m"])
                  for a, tr in perf.tracks.items() if a not in pl}
        designed = {k: t.camera[k] for k in ("pos", "target", "lens_mm")}
        d_err = staging.placement_error(designed, actors, pl, W, H)
        if d_err <= ctx.cfg["keep_designed_if_error_below"]:
            cam, err, how = designed, d_err, "designed camera already matches the reviewed frame"
        else:
            center = [sum(p[0] for p, _ in actors.values()) / len(actors), sum(p[1] for p, _ in actors.values()) / len(actors)]
            az0 = _azimuth(designed, center)
            win = ctx.cfg["az_window_deg"]
            cam, err = staging.fit_camera(actors, pl, W, H, az_range=(int(az0 - win), int(az0 + win) + 1), others=others,
                                          valid_pos=_free_space(ctx, perf), lens_choices=(24, 28, 35, 45, 55, 70),
                                          dists=(1.0, 1.4, 1.8, 2.2, 2.6, 3.2, 4.0, 5.0))
            how = f"fitted within ±{win}° of the designed azimuth, free-space + occlusion constrained"
        err = round(float(min(err, 1e6)), 5)
        # 首帧没有、但在世界里此刻站在画内的人：不能凭空消失 —— 明确标注为“与原首帧冲突、本镜白模不画”
        in_frame, off_frame = [], []
        for a, (p, h) in others.items():
            fx, fy, dd = staging.project(cam, p, W, H)
            hx, hy, _ = staging.project(cam, [p[0], p[1], h], W, H)
            vis = dd > 0.2 and not math.isnan(fx) and -0.05 * W < (fx + hx) / 2 < 1.05 * W and min(fy, hy) < H and max(fy, hy) > 0
            (in_frame if vis else off_frame).append(a)
        rec["camera_fit"] = {"camera": cam, "error": err, "actors": sorted(pl), "how": how,
                             "world_actors_off_frame": sorted(off_frame),
                             "world_conflict_hidden": sorted(in_frame)}
        applied = err <= ctx.cfg["fit_max_error"]
        rec["camera_fit"]["applied"] = applied
        if applied:
            t.camera = {**cam, "move": t.camera.get("move"), "size": t.camera.get("size")}
        ctx.db.flush()
        ctx.log(f"shot {n}: camera {how}; err={err} applied={applied} hidden={in_frame}")
    ctx.save()


# ================================================================== 白模
def greybox(ctx: Ctx, n: int, attempt: int, *, move_scale: float = 1.0, tag: str = "") -> dict:
    perf, t = takes(ctx)[n]
    rec = ctx.rec(n)
    out = ctx.out / f"shot{n:02d}" / f"greybox_a{attempt}{tag}"
    take = ws.take_out(t)
    if move_scale != 1.0:
        mv = dict(take["camera"]["move"])
        mv["amount"] = round(float(mv["amount"]) * move_scale, 3)
        take["camera"] = {**take["camera"], "move": mv}
    snap = ws.snapshot(ctx.db, perf.world_id, perf.world_version, [perf.region_key])
    perf_d = ws.performance_out(perf)
    hidden = (rec.get("camera_fit") or {}).get("world_conflict_hidden") or []
    if hidden:   # 只藏“画内且与原首帧冲突”的人；画外的人照常放在世界里（白模里本来也看不见）
        perf_d = {**perf_d, "tracks": {a: tr for a, tr in perf_d["tracks"].items() if a not in hidden}}
        take["focus"] = [a for a in (take.get("focus") or []) if a not in hidden]
    fixes, m, chk = [], {}, {}
    W, H = ctx.cfg["resolution"]
    for rnd in range(ctx.cfg["max_check_rounds"] + 1):
        job = wc.compile_take_job(snap, perf_d, take, out_dir=str(out), resolution=(W, H), actors_meta=ctx.cfg["actors"])
        m = blender_run.run(job, timeout_s=900, log_path=str(out / "blender.log"))
        chk = m["check"]
        if chk["ok"] or rnd == ctx.cfg["max_check_rounds"]:
            break
        cam = dict(take["camera"])
        pos, tgt = cam["pos"], cam["target"]
        if chk.get("camera_in_collision"):
            d = [tgt[i] - pos[i] for i in range(3)]
            L = math.sqrt(sum(x * x for x in d)) or 1
            cam["pos"] = [round(pos[i] + d[i] / L * 0.35, 3) for i in range(3)]
            fixes.append({"round": rnd, "fix": "camera_out_of_wall"})
        if chk.get("focus_out_of_frame"):
            mv = dict(cam["move"])
            mv["amount"] = round(float(mv["amount"]) * 0.5, 3)
            cam["move"] = mv
            fixes.append({"round": rnd, "fix": "halve_move"})
        take["camera"] = cam
    clay = out / "clay.mp4"
    clay_cam = qa.camera_motion(qa.frames_gray(str(clay))) if clay.exists() else None
    rec.setdefault("greybox", []).append({"attempt": attempt, "dir": str(out), "check": chk, "fixes": fixes,
                                          "world_version": m.get("world_version"), "clay_camera": clay_cam})
    return {"dir": out, "camera_json": json.loads((out / "camera.json").read_text()), "move": take["camera"]["move"],
            "clay_camera": clay_cam}


# ================================================================== 生成
def prompt_for(ctx: Ctx, s: dict, attempt: int, failed: list[str], strategy: str) -> str:
    mv = s["move"]["type"]
    actors = ctx.cfg["actors"]
    parts = [STYLE]
    if s["kind"] == "speech":
        who = s["focus"][0]
        parts.append(f"{actors[who].get('desc', who)} speaks only the supplied dialogue, at the exact pace of the audio. "
                     "Clear matching lip shapes for every word; mouth closed before the first word and after the last. "
                     "Small natural head and shoulder movement, blinking.")
    elif s["kind"] == "inner":
        who = s["focus"][0]
        parts.append(f"Close-up of {actors[who].get('desc', who)} lost in thought, inner monologue: the mouth stays CLOSED "
                     "the whole time. Eyes glisten, lip trembles, gaze slowly lowers; small breathing movement.")
    else:
        brief = (ctx.frame(s["n"]) or {}).get("director_brief") or {}
        parts.append(s.get("action_en") or brief.get("action_en") or s.get("text", ""))
        if s.get("layout"):
            parts.append("Match the first frame and keep the same people, place and camera as the driver.")
    if strategy != "a2v" and s["kind"] == "action" and s.get("layout") and ("positions" in failed or strategy != "layout"):
        # 身份加固：点名画里每个人（来自世界里的角色描述），不许消失或融化
        present = (ctx.rec(s["n"]).get("camera_fit") or {}).get("actors") or s.get("focus") or []
        names = "; ".join(actors[a].get("desc", a) for a in present if a in actors)
        parts.append(f"Exactly {len(present)} people stay fully visible and solid the whole clip: {names}. "
                     "Nobody fades, melts, merges or disappears.")
    parts.append(CAMERA_TEXT.get(mv, ""))
    parts.append(MOOD_TEXT.get(s.get("mood") or "", ""))
    if s["kind"] in ("action", "inner"):
        parts.append("Audible room tone: " + (s.get("ambience") or "ambient room tone, clothing rustle; no speech, no music."))
    if attempt and "motion" in failed:
        parts.append("Clearly visible continuous body movement throughout the clip, never a still frame.")
    if attempt and "camera" in failed:
        parts.append("The camera movement must be clearly noticeable from start to end.")
    if attempt and "audio" in failed:
        parts.append("Clearly audible natural sound effects for the whole clip.")
    return " ".join(p for p in parts if p)


def strategy_for(s: dict, attempt: int, history: list[dict]) -> str:
    """动作镜（layout）的身份升级阶梯：layout → union(深度+骨架) → 分段关键帧接力。其它镜固定路由。"""
    if s["kind"] == "speech":
        return "a2v"
    if not s.get("layout"):
        return "i2v"
    identity_fail = any("positions" in (h.get("qa") or {}).get("failed", []) for h in history)
    if attempt == 0 or not identity_fail:
        return "layout"
    used = {h.get("strategy") for h in history}
    if "union" not in used:
        return "union"
    return "segments"


def _render(ctx: Ctx, s: dict, inp: dict, key: str, ckpt: Path, dst: Path) -> tuple[Path, str]:
    task = gateway(ctx, "video.image_to_video", LTX25, inp, key, ckpt)
    return download(task["output"]["video"]["url"], dst), task["task_id"]


def generate(ctx: Ctx, s: dict, attempt: int, failed: list[str], history: list[dict]) -> dict:
    n = s["n"]
    sd = ctx.out / f"shot{n:02d}"
    sd.mkdir(parents=True, exist_ok=True)
    frame = ctx.frame(n) or {}
    if not frame.get("url"):
        raise PipelineError("没有已审核的成片风格首帧（原管线首帧），greybox 不能出片")
    strategy = strategy_for(s, attempt, history)
    seed = int(ctx.cfg.get("seed_base", 31000)) + n * 10 + attempt
    prompt = prompt_for(ctx, s, attempt, failed, strategy)
    close = frame.get("binding_mode") == "card_close"
    W, H = ctx.cfg["close_resolution"] if close else ctx.cfg["resolution"]
    inp = {"prompt": prompt, "first_frame": {"url": ctx.core + frame["url"]}, "width": W, "height": H,
           "fps": s["fps"], "duration_ms": s["dur"], "params": {"seed": seed, "stage2_steps": 2}}
    voice = ctx.voice(n)
    key = f"{ctx.cfg.get('key_prefix', 'world-greybox:' + ctx.run.id)}:s{n:02d}:a{attempt}:{strategy}"
    gb, post, task_ids = None, [], []
    if strategy in ("layout", "union", "segments"):
        gb = greybox(ctx, n, attempt, move_scale=1.5 if (attempt and "camera" in failed) else 1.0)
        inp["audio"] = {"mode": "generate"}
    if strategy == "layout":
        inp["control"] = {"type": "layout", "video": {"b64": b64(gb["dir"] / "clay.mp4")}}
        raw, tid = _render(ctx, s, inp, key, sd / f"task_a{attempt}.json", sd / f"raw_a{attempt}.mp4")
        task_ids.append(tid)
        route = "greybox:ltx25_layout(clay)"
    elif strategy == "union":
        inp["control"] = {"type": "union", "videos": {"depth": {"b64": b64(gb["dir"] / "depth.mp4")},
                                                       "pose": {"b64": b64(gb["dir"] / "pose.mp4")}},
                          "strengths": {"depth": 0.6, "pose": 0.85}}
        raw, tid = _render(ctx, s, inp, key, sd / f"task_a{attempt}.json", sd / f"raw_a{attempt}.mp4")
        task_ids.append(tid)
        route = "greybox:ltx25_union(depth+pose)"
    elif strategy == "segments":
        # 短窗口 + 关键帧接力：前半段 layout；取前半段最后一帧（身份仍完好）作后半段首帧，再按后半段白模出
        clay = gb["dir"] / "clay.mp4"
        fps = s["fps"]
        nf = int(round(qa.probe(str(clay))["duration_s"] * fps))
        h = int(math.ceil(max(nf / 2 - 1, 8) / 8) * 8 + 1)              # 前段帧数：≥ 一半的 8k+1
        r = int(math.ceil(max(nf - h, 8) / 8) * 8 + 1)                  # 后段帧数（含与前段共享的接力帧）
        c1, c2 = sd / f"clay_a{attempt}_1.mp4", sd / f"clay_a{attempt}_2.mp4"
        ff("-i", str(clay), "-vf", f"select='lt(n\\,{h})',setpts=N/{fps}/TB", "-r", str(fps), "-an", str(c1))
        ff("-i", str(clay), "-vf", f"select='gte(n\\,{h - 1})',setpts=N/{fps}/TB,tpad=stop_mode=clone:stop={r}",
           "-r", str(fps), "-frames:v", str(r), "-an", str(c2))
        p1 = {**inp, "duration_ms": int(h * 1000 / fps), "control": {"type": "layout", "video": {"b64": b64(c1)}}}
        r1, t1 = _render(ctx, s, p1, key + ":1", sd / f"task_a{attempt}_1.json", sd / f"raw_a{attempt}_1.mp4")
        last = sd / f"key_a{attempt}.png"
        ff("-i", str(r1), "-vf", f"select='eq(n\\,{h - 1})'", "-frames:v", "1", str(last))
        p2 = {**inp, "duration_ms": int(r * 1000 / fps), "first_frame": {"url": ctx.core + publish(last, "png")},
              "control": {"type": "layout", "video": {"b64": b64(c2)}}, "params": {"seed": seed + 5, "stage2_steps": 2}}
        r2, t2 = _render(ctx, s, p2, key + ":2", sd / f"task_a{attempt}_2.json", sd / f"raw_a{attempt}_2.mp4")
        raw = sd / f"raw_a{attempt}.mp4"
        dur = nf / fps
        ff("-i", str(r1), "-i", str(r2), "-filter_complex",
           f"[0:v]fps={fps},trim=end_frame={h},setpts=N/{fps}/TB[v1];[1:v]fps={fps},trim=start_frame=1,setpts=N/{fps}/TB[v2];"
           f"[0:a]atrim=duration={h / fps:.4f},asetpts=PTS-STARTPTS[a1];[1:a]atrim=start={1 / fps:.4f},asetpts=PTS-STARTPTS[a2];"
           f"[v1][a1][v2][a2]concat=n=2:v=1:a=1[vv][aa];[vv]trim=end_frame={nf}[v];[aa]atrim=duration={dur:.4f}[a]",
           "-map", "[v]", "-map", "[a]", "-r", str(fps), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(raw))
        task_ids += [t1, t2]
        post.append("keyframe_relay_2_segments")
        route = "greybox:ltx25_layout x2 (keyframe relay)"
    elif strategy == "a2v":
        if not voice:
            raise PipelineError("对白镜缺配音轨")
        inp["motion"] = "animate"
        inp["audio"] = {"mode": "drive", "track": {"b64": b64(voice)}}
        raw, tid = _render(ctx, s, inp, key, sd / f"task_a{attempt}.json", sd / f"raw_a{attempt}.mp4")
        task_ids.append(tid)
        route = "dialogue_a2v(voice drive)"
    else:
        inp["motion"] = "animate"
        inp["audio"] = {"mode": "generate"}
        raw, tid = _render(ctx, s, inp, key, sd / f"task_a{attempt}.json", sd / f"raw_a{attempt}.mp4")
        task_ids.append(tid)
        route = "ltx25_i2v(audio generate)"
    out = raw
    if s["kind"] == "inner" and voice:
        out = sd / f"vo_a{attempt}.mp4"
        ff("-i", str(raw), "-i", str(voice), "-filter_complex",
           "[0:a]volume=0.5[a0];[1:a]volume=1.0[a1];[a0][a1]amix=inputs=2:duration=first:normalize=0[a]",
           "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-ar", "48000", str(out))
        post.append("voice_over_mix")
        route += " + voice-over"
    ctx.log(f"shot {n} attempt {attempt}: {route} {W}x{H}@{s['fps']} {s['dur']}ms seed={seed}")
    return {"attempt": attempt, "strategy": strategy, "route": route, "seed": seed, "prompt": prompt,
            "task_ids": task_ids, "video": str(out), "raw": str(raw), "post": post, "size": [W, H],
            "greybox_dir": str(gb["dir"]) if gb else None, "greybox_move": gb["move"] if gb else None,
            "clay_camera": gb["clay_camera"] if gb else None}


# ================================================================== 声音补救
def add_foley(ctx: Ctx, s: dict, video: Path, attempt: int) -> Path:
    sd = ctx.out / f"shot{s['n']:02d}"
    url = publish(video, "mp4")
    task = gateway(ctx, "audio.foley", "mmaudio-large-44k-v2",
                   {"video": {"url": ctx.core + url}, "prompt": s.get("ambience") or "ambient room tone, clothing rustle, body movement",
                    "params": {"steps": 10, "seed": 400 + s["n"]}},
                   f"{ctx.cfg.get('key_prefix', 'wg')}:foley:s{s['n']:02d}:a{attempt}", sd / f"foley_a{attempt}.json", timeout_s=900)
    return download(first_url(task["output"].get("video") or task["output"]), sd / f"foley_a{attempt}.mp4")


def room_tone(ctx: Ctx, s: dict, video: Path, attempt: int) -> Path:
    """mmaudio 也给不出可闻声音时：铺一层环境底噪（低通粉噪 + 轻微嗡声），在报告里标注为 synthetic_room_tone。"""
    sd = ctx.out / f"shot{s['n']:02d}"
    sd.mkdir(parents=True, exist_ok=True)
    out = sd / f"roomtone_a{attempt}.mp4"
    dur = qa.probe(str(video))["duration_s"]
    db = ctx.cfg["room_tone_db"]
    has_a = qa.probe(str(video))["has_audio"]
    tone = (f"anoisesrc=color=pink:amplitude=1:d={dur:.3f}:r=48000,lowpass=f=700,highpass=f=60,"
            f"volume={db}dB,aformat=channel_layouts=stereo[t]")
    if has_a:
        flt = f"{tone};[0:a]aresample=48000,aformat=channel_layouts=stereo[o];[o][t]amix=inputs=2:duration=first:normalize=0[a]"
    else:
        flt = tone.replace("[t]", "[a]")
    ff("-i", str(video), "-filter_complex", flt, "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", str(out))
    return out


def composite_move(ctx: Ctx, s: dict, video: Path, attempt: int) -> Path:
    sd = ctx.out / f"shot{s['n']:02d}"
    info = qa.probe(str(video))
    fps = info.get("fps") or 8
    W, H = info["width"], info["height"]
    frames = max(2, round(info["duration_s"] * fps))
    z = f"1.10-0.10*on/{frames}" if s["move"]["type"] == "pull_out" else f"1+0.10*on/{frames}"
    out = sd / f"comp_a{attempt}.mp4"
    ff("-i", str(video), "-vf", f"scale={W*2}:{H*2},zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={fps}",
       "-c:a", "copy", str(out))
    return out


# ================================================================== QA
def music_cue_for(ctx: Ctx, s: dict) -> str | None:
    cue = None
    for m in ctx.cfg.get("music") or []:
        if s["n"] >= m["from_shot"]:
            cue = m["name"]
    return cue


def gate(ctx: Ctx, s: dict, a: dict) -> dict:
    frame = ctx.frame(s["n"]) or {}
    voice = ctx.voice(s["n"])
    vs = float(qa.probe(str(voice))["duration_s"]) if voice else None
    gbj = None
    if a.get("greybox_dir") and (Path(a["greybox_dir"]) / "camera.json").exists():
        gbj = json.loads((Path(a["greybox_dir"]) / "camera.json").read_text())
    ref = a.get("clay_camera")
    if ref is None and a.get("greybox_dir") and (Path(a["greybox_dir"]) / "clay.mp4").exists():
        ref = qa.camera_motion(qa.frames_gray(str(Path(a["greybox_dir"]) / "clay.mp4")))
    return qa.gate_shot(a["video"], kind=s["kind"], planned_move=s["move"]["type"], duration_s=s["dur"] / 1000,
                        mood=s.get("mood"), prompt=a["prompt"],
                        first_frame=str(media_path(frame["url"])) if frame.get("url") else None,
                        greybox=gbj, voice_s=vs, music_cue=music_cue_for(ctx, s), reference_camera=ref,
                        hue_of={a: m["hue"] for a, m in ctx.cfg["actors"].items() if m.get("hue")})


def _score(q: dict) -> tuple:
    return (q["pass"], -len(q["failed"]))


def run_shot(ctx: Ctx, s: dict, *, force: bool = False):
    n = s["n"]
    rec = ctx.rec(n)
    if rec.get("final") and not force:
        return
    rec.setdefault("attempts", [])
    if s["kind"] not in ctx.cfg["greybox_kinds"] and ctx.original_clip(n) and not (rec.get("override") or {}).get("source") == "greybox":
        rec["final"] = {"source": "original", "video": ctx.original_clip(n), "pass": None, "failed": [],
                        "why": f"{s['kind']} shot: face-safe original route (sharp face, lip-sync); greybox only for {ctx.cfg['greybox_kinds']}"}
        ctx.log(f"shot {n}: {s['kind']} → face-safe original take")
        ctx.save()
        return
    failed: list[str] = []
    # 已有尝试按当前闸门重判（闸门改过也一致）；过了就不重渲
    for a in rec["attempts"]:
        if "qa" in a and Path(a["video"]).exists():
            a["qa"] = gate(ctx, s, a)
            failed = a["qa"]["failed"]
    if not force and any(a.get("qa", {}).get("pass") for a in rec["attempts"]):
        ctx.log(f"shot {n}: existing attempt passes current gates")
    else:
        start = len(rec["attempts"])
        budget = ctx.cfg["max_retry"] + 1 + (start if force else 0)
        for attempt in range(start, budget):
            try:
                g = generate(ctx, s, attempt, failed, rec["attempts"])
            except Exception as e:  # noqa: BLE001
                ctx.log(f"shot {n} attempt {attempt} ERROR {e}")
                rec["attempts"].append({"attempt": attempt, "error": str(e), "trace": traceback.format_exc()[-1500:]})
                ctx.save()
                continue
            q = gate(ctx, s, g)
            if not q["audio"]["ok"] and s["kind"] in ("action", "inner") and q["audio"]["rms_db"] <= qa.TH["audio_rms_db"]:
                try:
                    g["video"] = str(add_foley(ctx, s, Path(g["video"]), attempt))
                    g["post"].append("mmaudio_foley")
                    q = gate(ctx, s, g)
                except Exception as e:  # noqa: BLE001
                    g["post"].append(f"foley_failed: {e}")
                if q["audio"]["rms_db"] <= qa.TH["audio_rms_db"]:
                    g["video"] = str(room_tone(ctx, s, Path(g["video"]), attempt))
                    g["post"].append("synthetic_room_tone")
                    q = gate(ctx, s, g)
            if not q["camera"]["ok"] and attempt == budget - 1 and s["kind"] != "action":
                g["video"] = str(composite_move(ctx, s, Path(g["video"]), attempt))
                g["post"].append("composited_camera_move")
                q = gate(ctx, s, g)
            rec["attempts"].append({**g, "qa": q})
            ctx.save()
            ctx.log(f"shot {n} attempt {attempt} ({g['strategy']}): pass={q['pass']} failed={q['failed']}")
            if q["pass"]:
                break
            failed = q["failed"]
    select(ctx, s)
    ctx.save()


def select(ctx: Ctx, s: dict):
    """逐镜选择：人工指定 > greybox 过闸门的尝试 > （允许回退时）原管线成片 > greybox 最好的失败尝试。"""
    n = s["n"]
    rec = ctx.rec(n)
    ok = [i for i, a in enumerate(rec.get("attempts", [])) if "qa" in a]
    orig = ctx.original_clip(n)
    ov = rec.get("override") or {}
    if ov.get("source") == "original" and orig:
        rec["final"] = {"source": "original", "video": orig, "pass": None, "failed": [], "why": "user override"}
        return
    if ov.get("source") == "greybox" and ov.get("attempt_index") is not None and ov["attempt_index"] in ok:
        i = ov["attempt_index"]
        a = rec["attempts"][i]
        rec["final"] = {"source": "greybox", "attempt_index": i, "video": a["video"], "pass": a["qa"]["pass"],
                        "failed": a["qa"]["failed"], "why": "user override"}
        return
    passing = [i for i in ok if rec["attempts"][i]["qa"]["pass"]]
    if passing:
        i = passing[0]
        rec["final"] = {"source": "greybox", "attempt_index": i, "video": rec["attempts"][i]["video"], "pass": True,
                        "failed": [], "why": "greybox passed all gates"}
        return
    best = max(ok, key=lambda i: _score(rec["attempts"][i]["qa"])) if ok else None
    if orig and ctx.cfg["fallback_to_original"]:
        rec["final"] = {"source": "original", "video": orig, "pass": None,
                        "failed": rec["attempts"][best]["qa"]["failed"] if best is not None else ["no_render"],
                        "why": "greybox failed gates after bounded retries → fell back to original pipeline take",
                        "best_greybox_attempt": best}
        return
    if best is not None:
        a = rec["attempts"][best]
        rec["final"] = {"source": "greybox", "attempt_index": best, "video": a["video"], "pass": False,
                        "failed": a["qa"]["failed"], "why": "best failing greybox attempt (no fallback)"}
    else:
        rec["final"] = None


# ================================================================== 配乐 + 成片 + 报告
def timeline(ctx: Ctx) -> list[dict]:
    t, out = 0, []
    for s in sorted(ctx.cfg["shots"], key=lambda x: x["n"]):
        out.append({**s, "start_ms": t, "end_ms": t + s["dur"]})
        t += s["dur"]
    return out


def music(ctx: Ctx, tl: list[dict]):
    cues = ctx.cfg.get("music") or []
    ctx.st.setdefault("music", {})
    total = tl[-1]["end_ms"]
    for k, m in enumerate(cues):
        if ctx.st["music"].get(m["name"]):
            continue
        a = next(s["start_ms"] for s in tl if s["n"] == m["from_shot"])
        b = next((s["start_ms"] for s in tl if k + 1 < len(cues) and s["n"] == cues[k + 1]["from_shot"]), total)
        try:
            task = gateway(ctx, "audio.music", "acestep-1.5-turbo",
                           {"prompt": m["prompt"], "duration_ms": b - a + 500,
                            "params": {"bpm": m.get("bpm", 80), "keyscale": m.get("key", "A minor"), "seed": m.get("seed", 77)}},
                           f"{ctx.cfg.get('key_prefix', 'wg')}:music:{m['name']}", ctx.out / f"music_{m['name']}.json", timeout_s=900)
            path = download(first_url(task["output"]), ctx.out / f"music_{m['name']}.audio")
            wav = ctx.out / f"music_{m['name']}.wav"
            ff("-i", str(path), "-ar", "48000", "-ac", "2", str(wav))
            ctx.st["music"][m["name"]] = {"path": str(wav), "start_ms": a, "end_ms": b, "prompt": m["prompt"]}
        except Exception as e:  # noqa: BLE001
            ctx.st["music"][m["name"]] = None
            ctx.st.setdefault("blockers", []).append(f"music {m['name']}: {e}")
        ctx.save()


def _normalize(src: str, dst: Path, dur_s: float, W: int, H: int):
    has_a = qa.probe(src)["has_audio"]
    a_in = "[0:a]" if has_a else "[1:a]"
    ff("-i", src, "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-filter_complex",
       f"[0:v]scale={W}:{H}:flags=lanczos,fps=24,tpad=stop_mode=clone:stop_duration=2,trim=duration={dur_s:.3f},setpts=PTS-STARTPTS[v];"
       f"{a_in}aresample=48000,aformat=channel_layouts=stereo,apad,atrim=duration={dur_s:.3f},asetpts=PTS-STARTPTS[a]",
       "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-c:a", "aac",
       "-b:a", "192k", str(dst))


def _srt_time(ms: int) -> str:
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def concat(ctx: Ctx, tl: list[dict]) -> dict:
    W, H = ctx.cfg["resolution"]
    parts = ctx.out / "parts"
    parts.mkdir(exist_ok=True)
    lst = []
    for s in tl:
        fz = ctx.rec(s["n"]).get("final") or {}
        dst = parts / f"{s['n']:02d}.mp4"
        if fz.get("video"):
            src = fz["video"]
            if (not qa.probe(src)["has_audio"]) or qa.audio_rms_db(src) <= qa.TH["audio_rms_db"]:
                src = str(room_tone(ctx, s, Path(src), "final"))   # 选中的镜头（含原管线回退）太静 → 铺环境底噪
                if "synthetic_room_tone" not in fz.setdefault("post", []):
                    fz["post"].append("synthetic_room_tone")
            _normalize(src, dst, s["dur"] / 1000, W, H)
        else:
            frame = ctx.frame(s["n"]) or {}
            if not frame.get("url"):
                raise PipelineError(f"镜 {s['n']} 既无成片也无首帧")
            ff("-loop", "1", "-i", str(media_path(frame["url"])), "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
               "-t", f"{s['dur']/1000:.3f}", "-vf", f"scale={W}:{H},fps=24", "-c:v", "libx264", "-pix_fmt", "yuv420p",
               "-c:a", "aac", str(dst))
            ctx.rec(s["n"])["placeholder"] = True
        lst.append(f"file '{dst}'")
    (parts / "list.txt").write_text("\n".join(lst))
    body = ctx.out / "body.mp4"
    ff("-f", "concat", "-safe", "0", "-i", str(parts / "list.txt"), "-c", "copy", str(body))
    srt, i = [], 1
    for s in tl:
        if s["kind"] in ("speech", "inner") and s.get("text"):
            srt.append(f"{i}\n{_srt_time(s['start_ms'])} --> {_srt_time(s['end_ms'])}\n{s['text']}\n")
            i += 1
    srt_p = ctx.out / "subtitles.srt"
    srt_p.write_text("\n".join(srt))
    final = ctx.out / (ctx.cfg.get("output_name") or "final.mp4")
    mus = [m for m in (ctx.st.get("music") or {}).values() if m]
    ins, flt = ["-i", str(body)], []
    for k, m in enumerate(mus, start=1):
        ins += ["-i", m["path"]]
        d = (m["end_ms"] - m["start_ms"]) / 1000
        flt.append(f"[{k}:a]atrim=duration={d:.3f},afade=t=in:d=0.6,afade=t=out:st={max(0, d-1.0):.3f}:d=1.0,"
                   f"volume={ctx.cfg['music_gain']},adelay={m['start_ms']}|{m['start_ms']}[m{k}]")
    mix = "".join(f"[m{k}]" for k in range(1, len(mus) + 1))
    flt.append(f"[0:a]{mix}amix=inputs={len(mus)+1}:duration=first:normalize=0[a]")
    ff(*ins, "-i", str(srt_p), "-filter_complex", ";".join(flt), "-map", "0:v", "-map", "[a]",
       "-map", f"{len(mus)+1}:s", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-c:s", "mov_text", str(final))
    return {"video": str(final), "probe": qa.probe(str(final))}


def shot_rows(ctx: Ctx) -> list[dict]:
    rows = []
    for s in timeline(ctx):
        rec = ctx.rec(s["n"])
        fz = rec.get("final") or {}
        atts = [a for a in rec.get("attempts", []) if "qa" in a]
        ai = fz.get("attempt_index", fz.get("best_greybox_attempt"))
        a = rec["attempts"][ai] if ai is not None else {}
        q = a.get("qa") or {}
        rows.append({"shot": s["n"], "kind": s["kind"], "move": s["move"]["type"], "mood": s.get("mood"),
                     "dur_s": s["dur"] / 1000, "fps": s["fps"], "attempts": len(rec.get("attempts", [])),
                     "greybox_pass": any(x["qa"]["pass"] for x in atts),
                     "source": fz.get("source"), "pass": fz.get("pass"), "failed": fz.get("failed", []),
                     "why": fz.get("why"), "route": a.get("route"), "strategy": a.get("strategy"),
                     "post": a.get("post", []), "placeholder": bool(rec.get("placeholder")),
                     "camera_fit": {k: (rec.get("camera_fit") or {}).get(k) for k in
                                    ("error", "how", "world_conflict_hidden", "world_actors_off_frame", "skipped")},
                     "greybox_video": a.get("video"), "clay": (str(Path(a["greybox_dir"]) / "clay.mp4") if a.get("greybox_dir") else None),
                     "original_video": ctx.original_clip(s["n"]), "final_video": fz.get("video"),
                     "approved": bool(rec.get("approved")), "override": rec.get("override"),
                     "metrics": {"first_corr": (q.get("positions") or {}).get("first_frame_corr"),
                                 "identity": (q.get("positions") or {}).get("identity"),
                                 "energy_in_staging": (q.get("positions") or {}).get("motion_energy_in_staging"),
                                 "cam_scale": (q.get("camera") or {}).get("scale"),
                                 "cam_shift_x": (q.get("camera") or {}).get("shift_x"),
                                 "cam_reference": (q.get("camera") or {}).get("reference"),
                                 "cam_why": (q.get("camera") or {}).get("why"),
                                 "mean_diff": (q.get("motion") or {}).get("mean_diff"),
                                 "audio_db": (q.get("audio") or {}).get("rms_db")}})
    return rows


def report(ctx: Ctx, fin: dict) -> dict:
    rows = shot_rows(ctx)
    rep = {"final": fin, "thresholds": qa.TH, "shots": rows, "music": ctx.st.get("music"),
           "blockers": ctx.st.get("blockers", []),
           "greybox_passed": sum(r["greybox_pass"] for r in rows),
           "used_greybox": sum(r["source"] == "greybox" for r in rows),
           "used_original": sum(r["source"] == "original" for r in rows), "total": len(rows)}
    (ctx.out / "qa_report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1))
    L = [f"# {ctx.run.title or 'world-greybox run'} — QA report", "",
         f"Final: `{fin['video']}` — {fin['probe']['duration_s']:.2f}s, {fin['probe']['width']}x{fin['probe']['height']}, audio={fin['probe']['has_audio']}",
         f"Greybox passed all gates: {rep['greybox_passed']}/{rep['total']} · used greybox {rep['used_greybox']} · fell back to original {rep['used_original']}", "",
         "Gates are automatic proxies (app/worldmodel/qa.py); they do not replace watching the film.", "",
         "| # | kind | source | strategy | move | att | greybox pass | failed | post | identity | cam (scale/shift vs clay) | audio dB |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        m = r["metrics"]
        L.append(f"| {r['shot']} | {r['kind']} | {r['source']} | {r['strategy']} | {r['move']} | {r['attempts']} | "
                 f"{'✅' if r['greybox_pass'] else '❌'} | {','.join(r['failed'])} | {','.join(r['post'])} | {m['identity']} | "
                 f"{m['cam_scale']}/{m['cam_shift_x']} ref={m['cam_reference']} | {m['audio_db']} |")
    if rep["blockers"]:
        L += ["", "## Blockers", *[f"- {b}" for b in rep["blockers"]]]
    (ctx.out / "qa_report.md").write_text("\n".join(L) + "\n")
    ctx.st["report"] = {k: rep[k] for k in ("greybox_passed", "used_greybox", "used_original", "total")}
    ctx.st["final"] = fin
    return rep


# ================================================================== 驱动
def execute(db: Session, run_id: str, *, only: set[int] | None = None, force: set[int] | None = None,
            log: Callable[[str], None] | None = print) -> dict:
    run = db.get(WorldPipelineRun, run_id)
    if run is None:
        raise PipelineError(f"运行 {run_id} 不存在")
    ctx = Ctx(db, run, log)
    for sc in ctx.cfg["shots"]:   # 时长/推理帧率与面部安全版对齐（真实配音/动作时长，不拉伸）
        o = ctx.face_safe().get(sc["n"])
        if o:
            sc["dur"], sc["fps"] = int(round(o["duration_s"] * 1000)), int(o.get("inference_fps") or sc["fps"])
    import os
    ctx.st["worker_pid"] = os.getpid()
    try:
        ctx.save(0.01, "running")
        build = (ctx.cfg.get("build") or {})
        if build.get("type") == "seed":
            import importlib
            importlib.import_module(build["module"]).build(db)
            db.commit()
        elif build.get("type") == "llm_delta" and not ctx.st.get("llm_delta_id"):
            from app.worldmodel import llm_build
            d = llm_build.propose_chapter_delta(db, run.world_id, chapter_id=build["chapter_id"], text=build["text"])
            ctx.st["llm_delta_id"] = d.id
            if build.get("auto_apply"):
                ws.apply_delta(db, d.id)
            db.commit()
        fit(ctx)
        tl = timeline(ctx)
        reqs = {int(k) for k, v in ctx.st["shots"].items() if v.get("rerender_requested")}
        force = (force or set()) | reqs
        for i, s in enumerate(tl):
            if only and s["n"] not in only and s["n"] not in force:
                continue
            run_shot(ctx, s, force=s["n"] in force)
            ctx.rec(s["n"]).pop("rerender_requested", None)
            ctx.save(0.05 + 0.85 * (i + 1) / len(tl))
        music(ctx, tl)
        fin = concat(ctx, tl)
        rep = report(ctx, fin)
        ctx.st.pop("worker_pid", None)
        ctx.save(1.0, "done")
        ctx.log(f"DONE {fin['video']} {fin['probe']['duration_s']}s greybox {rep['greybox_passed']}/{rep['total']}")
        return rep
    except Exception as e:  # noqa: BLE001
        db.rollback()
        run = db.get(WorldPipelineRun, run_id)
        run.status, run.error = "failed", f"{e}\n{traceback.format_exc()[-2000:]}"
        db.commit()
        raise
