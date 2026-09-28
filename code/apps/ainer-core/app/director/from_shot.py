"""分镜 → 3D 导演出片。

用户要的是「LLM 先把这一镜在 3D-BOX 里搭出来、导演台定好运镜，再按预演出片」，而不是纯文字出片：
纯文字时站位、机位全靠模型自己猜，同一场戏镜头之间对不上。

一镜的流水：
  1. 导演要求：分镜里现成的地点、出场人物（外貌）、画面内容、运动单（动作＋运镜）、导演台机位、时长
  2. LLM Planner（planner.generate_protocol）→ Scene Protocol：人物、站位、动作、机位
  3. Blender 无头渲控制素材（预演／白模／深度／骨架／边缘）
  4. LTX 2.5 按控制素材出片（2.3 Union Control：深度＋骨架＋边缘同时喂），提示词用分镜那套结构化写法
     （画风锚 → 场景头 → 人物外貌 → 构图 → 动作 → 声音），片子自带同步音效
  5. 出完挂回这一镜（jobs._chain）

2、3、4 是 Director 任务队列里一个接一个跑的（chain），接口只负责把第 1、2 步做完、交出 Blender 任务。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.director import jobs, planner, store
from app.models import AudioKind, AudioSpec, FrameRole, FrameSpec, Shot, ShotMotion, ShotPlan

#: 3D 预演一镜的时长上下限（秒）：短于 1.5 秒动作放不开；长于 8 秒先拆镜（Blender 145 帧 6 秒约 45 秒）
MIN_SEC, MAX_SEC = 1.5, 8.0


def _duration_sec(shot: Shot, motion: ShotMotion | None, voiced: list[AudioSpec]) -> float:
    from app.pipelines.cut import _beat_ms, dialogue_padding

    if voiced:
        ms = sum(int(a.duration_ms or 0) for a in voiced) + sum(dialogue_padding(shot))
    else:
        ms = _beat_ms(shot, motion)
    return max(MIN_SEC, min(MAX_SEC, ms / 1000.0))


def director_brief(db: Session, shot: Shot, plan: ShotPlan) -> dict[str, Any]:
    """给 Planner 的导演要求，外加成片要用的结构化提示词。都从分镜现成的数据里拼，不另外问模型。"""
    from app.models import Chapter, Scene, ScriptDoc, WorldEntity, WorldTransform
    from app.pipelines import ltx25_shots as L

    doc = db.get(ScriptDoc, plan.script_doc_id)
    chapter = db.get(Chapter, doc.chapter_id) if doc else None
    order = getattr(chapter, "order_no", None)
    transform = db.get(WorldTransform, plan.transform_id) if plan.transform_id else None
    profile_id = transform.target_profile_id if transform else None
    first = db.execute(select(FrameSpec).where(FrameSpec.shot_id == shot.id,
                                               FrameSpec.role == FrameRole.first)).scalars().first()
    motion = db.execute(select(ShotMotion).where(ShotMotion.shot_id == shot.id)).scalars().first()
    specs = list(db.execute(select(AudioSpec).where(AudioSpec.shot_id == shot.id)).scalars())
    voiced = [a for a in specs if a.kind == AudioKind.dialogue]
    sfx = [a for a in specs if a.kind == AudioKind.sfx]
    who = list(dict.fromkeys([*((first.entity_ids_json or []) if first else []),
                              *[a.entity_id for a in voiced if a.entity_id]]))
    looks = {eid: L.appearance(db, eid, order, profile_id) for eid in who}
    cast = [eid for eid in who if looks.get(eid)]
    scene = db.get(Scene, shot.scene_id) if shot.scene_id else None
    dur = _duration_sec(shot, motion, voiced)

    lines = [f"分镜第 {shot.order_no} 镜，{dur:.1f} 秒。"]
    if scene is not None:
        where = "，".join(x for x in (scene.location_text, scene.time_of_day, scene.weather) if x)
        if where:
            lines.append(f"地点：{where}。按地点搭景（墙、门、储物柜、桌椅这类要有），人物周围留出能动的空间。")
    if cast:
        lines.append("出场人物（按顺序，每人一个演员，站位别重叠）：")
        for i, eid in enumerate(cast, 1):
            ent = db.get(WorldEntity, eid)
            speaks = any(a.entity_id == eid for a in voiced)
            lines.append(f"  {i}. {ent.display_name if ent else '人物'}"
                         f"{'（这一镜说台词，脸朝镜头）' if speaks else ''}：{looks[eid][:160]}")
    if shot.description:
        lines.append(f"画面内容：{shot.description.strip()}")
    if motion is not None and (motion.motion_prompt_en or "").strip():
        lines.append(f"动作与运镜（照这个排动作和机位）：{motion.motion_prompt_en.strip()[:700]}")
    rig = (shot.camera_json or {}).get("rig") or {}
    if rig.get("description_en"):
        lines.append(f"导演台定的机位：{rig['description_en']}")
    elif motion is not None and motion.camera_move:
        lines.append(f"机位：{motion.camera_move}")

    speakers = list(dict.fromkeys(f"character ({cast.index(a.entity_id) + 1})" if a.entity_id in cast
                                  else "the character" for a in voiced))
    prompt = L.shot_prompt(first, motion, sfx, speakers, shot.description or "",
                           scene=L.scene_header(db, scene, chapter) if scene is not None else "",
                           characters=[looks[e] for e in cast], style=L.style_line(plan))
    return {"brief": "\n".join(lines), "duration": dur, "prompt": prompt, "cast": cast,
            "novel_id": getattr(chapter, "novel_id", None)}


def render_shot(db: Session, shot_id: str, *, seed: int | None = None, control_type: str = "union") -> dict[str, Any]:
    """这一镜走 3D 导演出片：搭景 → Blender → LTX 2.5 → 挂回镜头。返回场景和 Blender 任务。"""
    shot = db.get(Shot, shot_id)
    if shot is None:
        raise ValueError("镜头不存在")
    plan = db.get(ShotPlan, shot.shot_plan_id)
    b = director_brief(db, shot, plan)
    protocol, repairs = planner.generate_protocol(db, b["brief"], duration=b["duration"])
    protocol.setdefault("meta", {})["title"] = f"镜 {shot.order_no}：{(shot.description or '').strip()[:24]}"
    scene = store.create_from_protocol(db, protocol, source="shot", prompt=b["brief"],
                                       notes={"shot_id": shot.id, "plan_id": plan.id, "repairs": repairs})
    job = jobs.submit_blender(db, scene, chain={
        "shot_id": shot.id,
        "final": {"renderer": "ltx_25", "control_type": control_type, "prompt": b["prompt"],
                  "use_llm_prompt": False, "seed": seed},
    })
    return {"shot": shot.order_no, "scene_id": scene.id, "blender_job_id": job.id, "duration": b["duration"],
            "cast": len(b["cast"]), "brief": b["brief"], "prompt": b["prompt"], "repairs": repairs}
