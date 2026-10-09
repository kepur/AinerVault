"""导演审片：出分镜图之前，让懂镜头语言的模型把一场戏的镜头连起来过一遍。

分镜计划是逐镜生成的（qwen3.8-flash、不开思考），实跑出来的毛病都是「没把这场戏连起来看」：

- 同一个「领头少年」一镜是高个少年、下一镜成了李爽（译名 Tyler Stone / Brad Miller 还混着用）；
- 镜 11、12、13 三镜描述一字不差；
- 「血在嘴角和眼睛」这种歧义，图像模型就把血画到眼睛上；
- 一镜的描述直接拿去画静态图，里面混着「从左脸慢慢摇到正面」这种运镜句。

这里借 HKUDS/ViMax（MIT）的分镜师规则：每镜一个叙事目的；画面里的人写清位置、朝向、哪个部位；
一镜拆成「首帧静态快照 / 尾帧 / 运动过程」。运动过程按 LTX 官方提示词结构写：第一句主要动作、按时间顺序、
运镜放最后一句、不超过 80 词。

结果写在 shots.camera_json["review"]，不改分镜原文：
    {"cast": [实体 id，首帧里看得见的人], "focus": 实体 id, "first_frame": str, "last_frame": str,
     "motion": str, "issues": [中文说明], "model": str, "at": iso 时间}
关键帧（keyframe.keyframe_request）和钉关键帧出片（ltx25_shots，identity="frame"）有 review 就用 review。
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.capability.schemas import Capability
from app.models import AudioKind, AudioSpec, FrameRole, FrameSpec, Shot, ShotMotion, ShotPlan, TaskStatus

log = logging.getLogger("ainer-core")

PURPOSE = "director_review"
#: 一次审几镜：一场戏连起来看才查得出谁是谁（「把钱交出来」那句台词在镜 2，「领头少年扇耳光」在镜 5）；
#: 画布一张板按场次分好最多十几镜，一批放得下
BATCH = 16
MAX_TOKENS = 16000

SYSTEM = """You are a film director and storyboard supervisor preparing shots for an image model (keyframes) and the LTX-2 video model.
You receive one scene: its summary, the characters (with Chinese name, English screen name and look), and the shots in order.

Your job, for EVERY shot:
1. Decide who is VISIBLE in the first frame ("cast", character ids, at most 3, ordered left to right as they appear in frame).
   Resolve generic roles ("the leader", "领头少年", "the bully", "the victim") from the dialogue speakers, the screen names and the staging,
   and keep the same person for the same role across all shots. Never swap who does what.
   Close-ups (ecu, cu) show only the focus person, unless it is an over-the-shoulder shot.
2. "focus": the character the shot is about (the speaker if someone speaks).
3. "first_frame": ONE static snapshot at the very start of the shot, in English, <= 90 words:
   shot size and angle; for each visible person their position in frame (left / center / right, foreground / background),
   facing direction, pose, expression; the exact body part and detail that matters (e.g. "a thin line of blood at the left corner of
   his mouth, his eyes are wet with tears but not bleeding"). Refer to people by visible features, not by name.
   No ongoing or future actions ("about to", "starts to", "begins"), no camera movement, no lens jargon beyond the shot size.
4. "last_frame": the static snapshot at the end of the shot, same rules, consistent with the motion.
5. "motion": what happens between them, written for LTX-2, in English, <= 80 words, ONE paragraph:
   first sentence = the main action; then gestures and expression changes in chronological order; refer to people by visible
   features; if someone speaks, say who speaks; the LAST sentence is the camera: static, slow push-in, slow pull-back, gentle pan
   or slight handheld only (no orbit, no whip pan, no crane, no rotation). Keep everyone inside the frame.
6. If two shots are (near) duplicates, make them different moments or angles of the same beat.
7. Keep it cinematic and non-graphic: blood is a thin trickle, violence is implied by reactions.
8. "issues": short notes IN CHINESE about what you corrected (who the leader is, duplicates, ambiguities). Empty list if nothing.

Output ONLY a JSON object, no prose, no code fences:
{"shots": [{"shot": "s1", "cast": ["c1", "c2"], "focus": "c1", "first_frame": "...", "last_frame": "...", "motion": "...", "issues": ["..."]}],
 "continuity": ["中文：整场戏层面的说明"]}
Return one entry per input shot, using the given shot ids (s1, s2, ...) and character ids (c1, c2, ...)."""


class ReviewError(RuntimeError):
    """审片没做成（模型不可用、返回的不是 JSON）。消息直接给人看。"""


def review_of(shot: Shot) -> dict[str, Any] | None:
    rv = (shot.camera_json or {}).get("review") if isinstance(shot.camera_json, dict) else None
    return rv if isinstance(rv, dict) and rv.get("first_frame") else None


# ── 组上下文 ─────────────────────────────────────────────────────────────────

def _names(db: Session, plan: ShotPlan, ids: Iterable[str]) -> dict[str, str]:
    """实体 id → 译名（世界观映射里的 target_name，例如 李爽 → Brad Miller）。"""
    from sqlalchemy import text

    ids = [i for i in ids if i]
    if not ids or not plan.transform_id:
        return {}
    rows = db.execute(text("select entity_id, target_name from core.entity_world_names "
                           "where transform_id = :t and entity_id = any(:ids)"),
                      {"t": plan.transform_id, "ids": ids}).all()
    return {e: n for e, n in rows if n}


def _staging(db: Session, shot_id: str) -> list[dict[str, Any]]:
    from app.models import ShotPerformance

    out = []
    for p in db.execute(select(ShotPerformance).where(ShotPerformance.shot_id == shot_id)).scalars():
        row = {"who": p.entity_id, "position": getattr(p.position, "value", p.position),
               "facing": getattr(p.facing, "value", p.facing)}
        for k in ("gaze_target", "expression", "expression_end", "action", "action_end"):
            v = getattr(p, k, None)
            if v:
                row[k] = str(v)[:160]
        out.append(row)
    return out


def build_context(db: Session, plan: ShotPlan, shots: Sequence[Shot]) -> tuple[str, dict[str, str], dict[str, str]]:
    """给模型的输入（JSON 文本）＋ 编号映射（s1 → shot id，c1 → entity id）。"""
    from app.director.from_shot import director_brief
    from app.models import Scene, WorldEntity

    shot_alias = {f"s{i + 1}": s.id for i, s in enumerate(shots)}
    briefs = {s.id: director_brief(db, s, plan) for s in shots}
    staging = {s.id: _staging(db, s.id) for s in shots}
    dialogue = {s.id: [a for a in db.execute(select(AudioSpec).where(AudioSpec.shot_id == s.id,
                                                                      AudioSpec.kind == AudioKind.dialogue)).scalars()]
                for s in shots}
    people: list[str] = []
    for s in shots:
        people += briefs[s.id]["cast"] + [r["who"] for r in staging[s.id]] + [a.entity_id for a in dialogue[s.id] if a.entity_id]
    people = [p for p in dict.fromkeys(people) if p]
    char_alias = {f"c{i + 1}": eid for i, eid in enumerate(people)}
    alias_of = {eid: a for a, eid in char_alias.items()}
    screen = _names(db, plan, people)

    from app.pipelines import ltx25_shots as L
    first = briefs[shots[0].id] if shots else {}
    chars = []
    for a, eid in char_alias.items():
        ent = db.get(WorldEntity, eid)
        chars.append({"id": a, "name": getattr(ent, "display_name", None) or eid, "screen_name": screen.get(eid),
                      "look": L.appearance(db, eid, first.get("chapter_order"), first.get("profile_id"))[:220]})

    scenes = {s.scene_id for s in shots if s.scene_id}
    scene_info = []
    for sid in scenes:
        sc = db.get(Scene, sid)
        if sc is not None:
            scene_info.append({k: v for k, v in {"title": sc.title, "location": sc.location_text, "time": sc.time_of_day,
                                                 "mood": sc.mood, "summary": (sc.summary or "")[:800]}.items() if v})

    def who(e: str | None) -> str | None:
        return alias_of.get(e or "")

    rows = []
    for a, sid in shot_alias.items():
        s = next(x for x in shots if x.id == sid)
        b = briefs[sid]
        fs = db.execute(select(FrameSpec).where(FrameSpec.shot_id == sid, FrameSpec.role == FrameRole.first)
                        ).scalars().first()
        mo = db.execute(select(ShotMotion).where(ShotMotion.shot_id == sid)).scalars().first()
        rows.append({k: v for k, v in {
            "shot": a, "no": s.order_no, "size": s.shot_size, "seconds": round((s.duration_ms or 0) / 1000, 1),
            "description": (s.description or "")[:300],
            "current_cast": [who(e) for e in b["cast"] if who(e)],
            "dialogue": [f"{who(d.entity_id) or '?'}: {(d.text or '')[:160]}" for d in dialogue[sid]],
            "staging": [{**r, "who": who(r["who"])} for r in staging[sid]],
            "framing_draft": ((fs.prompt if fs else "") or "")[:400],
            "motion_draft": ((mo.motion_prompt_en if mo else "") or "")[:500],
        }.items() if v not in (None, "", [], {})})
    user = json.dumps({"scene": scene_info, "characters": chars, "shots": rows}, ensure_ascii=False)
    return user, shot_alias, char_alias


# ── 调模型、解析 ─────────────────────────────────────────────────────────────

_THINK = re.compile(r"<think>.*?</think>", re.S)


def parse_json(text: str) -> dict[str, Any]:
    """从模型输出里取 JSON 对象：去掉 <think> 段和代码围栏，取最外层的大括号。"""
    t = _THINK.sub("", text or "")
    t = re.sub(r"```(?:json)?", "", t)
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i:
        raise ReviewError("模型没有返回 JSON")
    try:
        data = json.loads(t[i:j + 1])
    except json.JSONDecodeError as exc:
        raise ReviewError(f"模型返回的 JSON 解析不了：{exc}") from exc
    if not isinstance(data, dict):
        raise ReviewError("模型返回的不是 JSON 对象")
    return data


def _chat(db: Session, system: str, user: str | list[dict[str, Any]], *, purpose: str = PURPOSE,
          max_tokens: int = MAX_TOKENS, temperature: float = 0.3) -> tuple[str, str]:
    """同步调一次 text.chat（按 purpose 走路由：默认本机 LM Studio）。返回 (文本, 模型名)。"""
    from app.capability.service import submit_task

    task = submit_task(
        db, Capability.text_chat,
        {"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
         "temperature": temperature, "max_tokens": max_tokens},
        purpose=purpose, sync=True, force=True, ref_kind=purpose,
    )
    if task.status != TaskStatus.succeeded:
        err = task.error_json or {}
        raise ReviewError(f"模型调用失败 [{err.get('code')}]: {err.get('message')}")
    return str((task.result_json or {}).get("text") or ""), str(task.model or "")


def apply_review(shots: Sequence[Shot], data: dict[str, Any], shot_alias: dict[str, str],
                 char_alias: dict[str, str], model: str) -> list[dict[str, Any]]:
    """把模型的审片结果按编号挂回镜头；对不上的编号丢掉。返回逐镜摘要。"""
    by_id = {s.id: s for s in shots}
    at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out = []
    from app.pipelines.base import as_items

    for row in as_items(data, "shots"):
        sid = shot_alias.get(str(row.get("shot") or ""))
        shot = by_id.get(sid or "")
        ff = str(row.get("first_frame") or "").strip()
        if shot is None or not ff:
            continue
        cast = [char_alias[c] for c in row.get("cast") or [] if c in char_alias][:3]
        focus = char_alias.get(str(row.get("focus") or ""))
        rv = {"cast": cast, "focus": focus if focus in cast else (cast[0] if cast else None),
              "first_frame": ff[:900], "last_frame": str(row.get("last_frame") or "").strip()[:900],
              "motion": str(row.get("motion") or "").strip()[:900],
              "issues": [str(x)[:200] for x in row.get("issues") or [] if x][:6], "model": model, "at": at}
        shot.camera_json = {**(shot.camera_json or {}), "review": rv}     # 换新 dict：JSONB 原地改看不见
        out.append({"shot_id": shot.id, "order_no": shot.order_no, "cast": cast, "issues": rv["issues"]})
    return out


def review_shots(db: Session, plan: ShotPlan, shots: Sequence[Shot], *, force: bool = False) -> dict[str, Any]:
    """审这几镜（按场次、每批最多 BATCH 镜）。已经审过的不重审，除非 force。返回 {reviewed, skipped, issues, continuity}。"""
    todo = [s for s in sorted(shots, key=lambda s: s.order_no) if force or review_of(s) is None]
    result: dict[str, Any] = {"reviewed": [], "skipped": len(shots) - len(todo), "continuity": [], "errors": []}
    by_scene: dict[str, list[Shot]] = {}
    for s in todo:
        by_scene.setdefault(s.scene_id or "", []).append(s)
    for group in by_scene.values():
        for i in range(0, len(group), BATCH):
            batch = group[i:i + BATCH]
            try:
                user, shot_alias, char_alias = build_context(db, plan, batch)
                text, model = _chat(db, SYSTEM, user)
                data = parse_json(text)
                result["reviewed"] += apply_review(batch, data, shot_alias, char_alias, model)
                result["continuity"] += [str(x)[:300] for x in data.get("continuity") or [] if x][:6]
                db.commit()
            except Exception as exc:                  # noqa: BLE001 —— 一批审不成不拖垮别的批；出图照旧用分镜原文
                db.rollback()
                log.warning("导演审片失败（镜 %s–%s）：%s", batch[0].order_no, batch[-1].order_no, exc)
                result["errors"].append(f"镜 {batch[0].order_no}–{batch[-1].order_no}：{exc}"[:300])
    return result
