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

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.director import jobs, planner, store
from app.models import AudioKind, AudioSpec, FrameRole, FrameSpec, SceneProject, Shot, ShotMotion, ShotPlan
from app.models.base import utcnow
from app.pipelines.base import as_items

log = logging.getLogger(__name__)

#: 3D 预演一镜的时长上下限（秒）：短于 1.5 秒动作放不开；长于 8 秒先拆镜（Blender 145 帧 6 秒约 45 秒）
MIN_SEC, MAX_SEC = 1.5, 8.0
#: 出片档位：Blender 预演、身份首帧、LTX 成片三者同一尺寸（宽高比一致，控制素材不用拉伸）。
#: fast = 最快那档（LTX 2.5 两阶段管线要求 64 的倍数，480p 档就是 768×448）；hd = 1024×576
PROFILES: dict[str, tuple[int, int]] = {"fast": (768, 448), "hd": (1024, 576)}
#: 声音：auto = 这一镜台词都按角色音色配好了就用台词轨驱动口型（a2v），否则现场生成；generate；none
AUDIO_MODES = ("auto", "generate", "none")
_SIZE_ZH = {"ecu": "大特写", "cu": "特写", "ms": "中景", "fs": "全景", "ws": "远景", "els": "大远景"}


def _duration_sec(shot: Shot, motion: ShotMotion | None, voiced: list[AudioSpec]) -> float:
    from app.pipelines.cut import _beat_ms, dialogue_padding

    if voiced:
        ms = sum(int(a.duration_ms or 0) for a in voiced) + sum(dialogue_padding(shot))
    else:
        ms = _beat_ms(shot, motion)
    return max(MIN_SEC, min(MAX_SEC, ms / 1000.0))


def _staged_positions(db: Session, first: FrameSpec | None) -> list[str]:
    """导演台（source=stage）摆过的站位 → 「某某：画面左侧、前景」。自动摆位的不写，交给 LLM 按剧情摆。"""
    from app.models import WorldEntity

    reg = ((first.params_json or {}).get("regional") or {}) if first is not None else {}
    if reg.get("source") != "stage":
        return []
    out = []
    for f in as_items(reg, "figures"):
        x, bottom = float(f.get("x") or 0.5), float(f.get("bottom") or 0.9)
        side = "左侧" if x < 0.38 else "右侧" if x > 0.62 else "中间"
        depth = "前景" if bottom > 0.97 else "后景" if bottom < 0.75 else "中景"
        ent = db.get(WorldEntity, f.get("entity_id")) if f.get("entity_id") else None
        out.append(f"{getattr(ent, 'display_name', None) or '人物'}：画面{side}、{depth}")
    return out


def shot_location(db: Session, shot: Shot, plan: ShotPlan, first: FrameSpec | None,
                  novel_id: str | None, profile_id: str | None) -> dict[str, str]:
    """这一镜的场景参考（资产库里的 location 素材）：{key, prompt（英文描述）, url（场景图）}。

    分镜首帧自己的 asset_keys 里没有，就取同一场戏其它镜头绑的（同场景共用一张场景图）。
    """
    from app.models import AssetKindSpec
    from app.pipelines.frame_compose import _asset_urls, _variant_index

    if not novel_id or not profile_id:
        return {}
    by_key, _ = _variant_index(db, novel_id, profile_id)

    def loc_keys(fs: FrameSpec | None) -> list[str]:
        return [k for k in ((fs.params_json or {}).get("asset_keys") or []) if isinstance(k, str)
                and k in by_key and by_key[k][0].kind == AssetKindSpec.location]

    keys = loc_keys(first)
    if not keys and shot.scene_id:
        for fs in db.execute(select(FrameSpec).join(Shot, Shot.id == FrameSpec.shot_id)
                             .where(Shot.shot_plan_id == plan.id, Shot.scene_id == shot.scene_id)).scalars():
            keys = loc_keys(fs)
            if keys:
                break
    if not keys:
        return {}
    spec, var = by_key[keys[0]]
    urls = _asset_urls(db, var.ref_asset_ids or [])
    return {"key": spec.canonical_key, "prompt": (var.visual_prompt or "").strip(), "url": urls[0] if urls else ""}


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

    loc = shot_location(db, shot, plan, first, getattr(chapter, "novel_id", None), profile_id)
    lines = [f"分镜第 {shot.order_no} 镜，{dur:.1f} 秒。"]
    if scene is not None:
        where = "，".join(x for x in (scene.location_text, scene.time_of_day, scene.weather) if x)
        if where:
            lines.append(f"地点：{where}。按地点搭景（墙、门、储物柜、桌椅这类要有），人物周围留出能动的空间。")
    if loc.get("prompt"):
        # 场景图是资产库里定好的样子；白模要按它搭出纵深和主要陈设（走廊要有两侧墙和尽头，不能只是一面墙），
        # 否则成片的深度/边缘控制会把背景压成一面平墙（实跑镜 1）
        lines.append(f"场景参考图的样子（白模照这个搭：空间纵深、两侧与尽头、主要陈设的位置）：{loc['prompt'][:500]}")
    if cast:
        lines.append("出场人物（按顺序，每人一个演员，站位别重叠；演员 id 依次用 p1、p2、p3…，和下面的顺序一一对应）：")
        for i, eid in enumerate(cast, 1):
            ent = db.get(WorldEntity, eid)
            speaks = any(a.entity_id == eid for a in voiced)
            lines.append(f"  {i}. {ent.display_name if ent else '人物'}"
                         f"{'（这一镜说台词，脸朝镜头）' if speaks else ''}：{looks[eid][:160]}")
    staged = _staged_positions(db, first)
    if staged:
        lines.append("站位（导演在导演台上手摆的，照这个摆）：" + "；".join(staged))
    if shot.description:
        lines.append(f"画面内容：{shot.description.strip()}")
    if motion is not None and (motion.motion_prompt_en or "").strip():
        lines.append(f"动作与运镜（照这个排动作和机位）：{motion.motion_prompt_en.strip()[:700]}")
    size_zh = _SIZE_ZH.get(shot.shot_size or "")
    focus = next((a.entity_id for a in voiced if a.entity_id in cast), cast[0] if cast else None)
    if size_zh and focus and shot.shot_size in ("ecu", "cu"):
        ent = db.get(WorldEntity, focus)
        lines.append(f"景别：{size_zh}。镜头对着「{ent.display_name if ent else '主角'}」取景，其余人可以不入画。")
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
            "shot_size": shot.shot_size, "focus": focus, "location": loc,
            "looks": [looks[e] for e in cast], "chapter_order": order, "profile_id": profile_id,
            "background": " ".join(x for x in (L.style_line(plan), L.scene_header(db, scene, chapter) if scene is not None
                                                else "") if x),
            "novel_id": getattr(chapter, "novel_id", None)}


#: 预演机位焦距：控制素材只管构图，用中焦把人拍全；运动单里的 135mm 长焦会让三个人挤不进画面
PROBE_LENS_MM = 40.0
#: 每个出场的人至少要露出这么多画面（0.3%）才算「拍到了」
MIN_COVERAGE = 0.003
_CAMERA_OPS = ("camera.move", "camera.frame", "camera.follow", "camera.keys")


def auto_frame(db: Session, scene: Any, duration: float, *, shot_size: str | None = None,
               focus_entity: str | None = None) -> dict[str, Any]:
    """LLM 摆的机位先试一遍：有人没露出来（被墙、楼、柜子挡住，或在画面外）就换成试出来的最佳机位。

    试机位是 Blender 渲小色块图数每个人露出的像素（能算遮挡），约 5 秒。
    """
    import json as _json

    from app.director import blender_adapter, config
    from app.scene3d.runner import bake_scene

    doc = store.scene_doc(db, scene)
    baked = bake_scene(doc, fps=24, camera=None)
    d = config.storage_dir() / "probe" / scene.id
    d.mkdir(parents=True, exist_ok=True)
    (d / "scene_resolved.json").write_text(_json.dumps(baked, ensure_ascii=False), encoding="utf-8")
    w, h = (config.load("blender").get("resolution") or [1024, 576])
    focus = dict(_bound(scene.protocol_json or {})).get(focus_entity or "")
    # 景别与焦点人物检查：
    # 1. 如果明确指定了焦点人物（focus），优先保证焦点人物的构图与可见性，而不是因背景/次要人物未入画而强行切机位
    # 2. 特写/中景等景别有各自的画面占比区间，不能以全员露出替代导演构图
    sized = shot_size in ("ecu", "cu", "mcu", "ms") and bool(focus)
    target_coverage = {
        "ecu": (0.18, 0.50),  # 大特写
        "cu": (0.10, 0.40),   # 特写
        "mcu": (0.05, 0.28),  # 中特写
        "ms": (0.02, 0.22),   # 中景
    }
    res = blender_adapter.probe(baked_path=str(d / "scene_resolved.json"), out_dir=str(d),
                                resolution=(int(w), int(h)), lens_mm=PROBE_LENS_MM,
                                shot_size=shot_size if sized else None, focus=focus if sized else None)
    planner_cov = (res.get("planner") or {}).get("coverage") or {}
    best = res.get("best") or {}
    if sized and focus in planner_cov:
        cov = planner_cov.get(focus, 0.0)
        min_cov, max_cov = target_coverage.get(shot_size, (MIN_COVERAGE, 1.0))
        if min_cov <= cov <= max_cov:
            return {"camera": "planner", "coverage": planner_cov, "shot_size": shot_size, "focus": focus}
    elif not focus and planner_cov and min(planner_cov.values()) >= MIN_COVERAGE:
        return {"camera": "planner", "coverage": planner_cov}
    if "position" not in best:
        return {"camera": "planner", "coverage": planner_cov, "note": "没有更好的候选"}
    proto = scene.protocol_json or {}
    cams = proto.get("cameras") or []
    if not cams:
        return {"camera": "planner", "coverage": planner_cov, "note": "场景里没有机位"}
    cid = cams[0].get("id")

    # 检查是否存在意图运镜（timeline 中的 camera.move / camera.follow 或已有 keys 的运动位移）
    timeline = proto.get("timeline") or []
    cam_moves = [o for o in timeline if o.get("op") in ("camera.move", "camera.follow") and o.get("camera") in (cid, None)]
    orig_keys = cams[0].get("keys") or []

    # 计算终点位姿，保留运镜意图，禁止切成首尾完全相同的静止机位
    start_pos = best["position"]
    start_look = best["look_at"]
    end_pos = list(start_pos)
    end_look = list(start_look)

    has_motion = False
    if len(orig_keys) >= 2:
        # 如果原机位自带关键帧运动轨迹，保留位移增量
        p0 = orig_keys[0].get("position")
        p1 = orig_keys[-1].get("position")
        l0 = orig_keys[0].get("look_at")
        l1 = orig_keys[-1].get("look_at")
        if p0 and p1 and any(abs(a - b) > 1e-4 for a, b in zip(p0, p1)):
            delta_p = [b - a for a, b in zip(p0, p1)]
            end_pos = [sp + dp for sp, dp in zip(start_pos, delta_p)]
            has_motion = True
        if l0 and l1 and any(abs(a - b) > 1e-4 for a, b in zip(l0, l1)):
            delta_l = [b - a for a, b in zip(l0, l1)]
            end_look = [sl + dl for sl, dl in zip(start_look, delta_l)]
            has_motion = True

    if not has_motion and cam_moves:
        # 如果 timeline 里指定了运镜预设（如 push_in / pull_out / pan / follow），按预设推算终点位姿
        move_op = cam_moves[0]
        preset = str(move_op.get("preset", ""))
        vec = [el - ep for ep, el in zip(start_pos, start_look)]
        dist = (sum(v**2 for v in vec)) ** 0.5
        if "push_in" in preset or "dolly_in" in preset:
            # 向视线目标前推 18%
            if dist > 0.1:
                end_pos = [sp + 0.18 * v for sp, v in zip(start_pos, vec)]
                has_motion = True
        elif "pull_out" in preset or "dolly_out" in preset:
            # 远离视线目标后拉 20%
            if dist > 0.1:
                end_pos = [sp - 0.20 * v for sp, v in zip(start_pos, vec)]
                end_look = [start_look[0], start_look[1] + 0.1, start_look[2]]
                has_motion = True
        elif "pan" in preset:
            # 平移摇镜
            pan_offset = 0.8 if "right" in preset else -0.8
            end_look = [start_look[0] + pan_offset, start_look[1], start_look[2]]
            has_motion = True
        elif "follow" in preset or move_op.get("op") == "camera.follow":
            # 跟随移动
            end_pos = [start_pos[0], start_pos[1], start_pos[2] + 0.5]
            end_look = [start_look[0], start_look[1], start_look[2] + 0.5]
            has_motion = True

    key_start = {"position": start_pos, "look_at": start_look, "lens_mm": best["lens_mm"]}
    key_end = {"position": end_pos, "look_at": end_look, "lens_mm": best["lens_mm"]}

    ops: list[dict[str, Any]] = [
        {"op": "replace", "path": "/cameras/0/keys", "value": [{"t": 0, **key_start}, {"t": round(duration, 2), **key_end}]},
        {"op": "replace", "path": "/cameras/0/lens_mm", "value": best["lens_mm"]},
    ]
    # 仅移除旧的冗余 camera.keys，保留 camera.move / camera.follow 等运镜标记用于元数据与审查
    for i in sorted((i for i, o in enumerate(proto.get("timeline") or [])
                     if o.get("op") == "camera.keys" and o.get("camera") in (cid, None)), reverse=True):
        ops.append({"op": "remove", "path": f"/timeline/{i}"})
    store.patch_scene(db, scene, ops, by="auto_frame")
    return {"camera": best.get("name"), "coverage": best.get("coverage"), "planner_coverage": planner_cov,
            "motion_preserved": has_motion,
            **({"shot_size": shot_size, "focus": focus} if sized else {})}


def _bound(protocol: dict[str, Any]) -> list[tuple[str, str]]:
    """[(实体 id, 演员 id)]：协议里已绑定角色库角色（character_ref=e:<实体 id>）的演员。"""
    out = []
    for a in as_items(protocol, "actors"):
        ref = str(a.get("character_ref") or "")
        if ref.startswith("e:") and a.get("id"):
            out.append((ref[2:], a["id"]))
    return out


def bind_cast(db: Session, protocol: dict[str, Any], cast: list[str]) -> None:
    """把这一镜出场的角色库角色钉到协议演员上：character_ref=e:<实体 id>，名字用角色名。

    LLM 被要求「演员 id 依次用 p1、p2…」，但那只是请求；这里按 id、没有再按协议顺序落实成硬绑定，
    之后身份首帧、3D-BOX 里的立绘、成片都认这个 id，不再认顺序。
    """
    from app.models import WorldEntity

    actors = [a for a in as_items(protocol, "actors") if a.get("type", "human") == "human"]
    by_id = {a.get("id"): a for a in actors}
    used: set[int] = set()
    for i, eid in enumerate(cast, 1):
        a = by_id.get(f"p{i}")
        if a is None:
            a = next((x for x in actors if id(x) not in used), None)
        if a is None:
            continue
        used.add(id(a))
        ent = db.get(WorldEntity, eid)
        a["character_ref"] = f"e:{eid}"
        if ent is not None:
            a["name"] = ent.display_name


def dialogue_track(db: Session, shot: Shot) -> tuple[str, int] | None:
    """这一镜的台词驱动轨（按角色音色配好的对白顺排，排法同 cut.build_timeline）。
    没有台词、或有一句还没配音 → None（这时只能现场生成声音，音色就不是角色库定的那个了）。"""
    from app.models import Asset
    from app.pipelines.ltx25_shots import drive_track

    voiced = sorted((a for a in db.execute(select(AudioSpec).where(AudioSpec.shot_id == shot.id)).scalars()
                     if a.kind == AudioKind.dialogue), key=lambda a: a.id)
    if not voiced or not all(a.asset_id for a in voiced):
        return None
    assets = {a.id: a for a in db.execute(select(Asset).where(Asset.id.in_([a.asset_id for a in voiced]))).scalars()}
    return drive_track(shot, voiced, assets)


def stage_scene_key(plan: ShotPlan, shot: Shot) -> str:
    """共享舞台键：同一分镜计划 × 同一剧本场次。没有场次的镜头退回自己（不和别人共用）。"""
    return f"{plan.id}:{shot.scene_id or ('shot:' + shot.id)}"


def staged_scene(db: Session, plan: ShotPlan, shot: Shot, plan_once) -> tuple[Any, list, bool]:
    """取这场戏已经搭好的导演场景；没有才调用 plan_once() 搭一次。返回 (场景, 修补记录, 是否复用)。

    World DB 里该场次已有整场表演（world_performances.scene_key）时，在场景 notes 里记下 performance id，
    Blender 侧按表演 + 本镜时间窗出控制素材（docs/studio/world_greybox_pipeline.md）。
    """
    from app.models import DirectorScene
    from app.worldmodel import service as world

    key = stage_scene_key(plan, shot)
    found = db.scalars(select(DirectorScene).where(DirectorScene.notes_json["stage_scene_key"].astext == key)
                       .order_by(DirectorScene.created_at)).first()
    reused = found is not None
    if found is None:
        found, repairs = plan_once()
    else:
        repairs = []
    perf = world.performance_for_scene(db, shot.scene_id) if shot.scene_id else None
    if perf is not None and (found.notes_json or {}).get("world_performance_id") != perf.id:
        found.notes_json = {**(found.notes_json or {}), "world_performance_id": perf.id,
                            "world_version": perf.world_version}
    return found, repairs, reused


def render_shot(db: Session, shot_id: str, *, seed: int | None = None, control_type: str = "union",
                scene_id: str | None = None, frames_only: bool = False,
                profile: str | None = None, audio: str = "generate") -> dict[str, Any]:
    """这一镜走 3D 导演出片：搭景 → Blender → 身份首帧 → LTX 2.5 → 挂回镜头。返回场景和 Blender 任务。

    scene_id：按这一镜已有的导演场景重出（用户在 3D-BOX 里调过站位、动作、机位）——不再让 LLM 重新搭，
    也不自动换机位（用户定的机位优先）。
    profile：出片档位（PROFILES），不给就按 blender.yaml / ltx25.yaml 的默认尺寸。
    audio：auto / generate / none（AUDIO_MODES）。auto 下台词都配好了就走 a2v：画面由身份首帧（按白模预演画的）起，
    口型和表演跟着角色配音走 —— 网关的 a2v 不吃白模控制视频，这是「音色一致」和「动作跟白模」之间的取舍。
    """
    if profile is not None and profile not in PROFILES:
        raise ValueError(f"出片档位只有 {', '.join(PROFILES)}")
    if audio not in AUDIO_MODES:
        raise ValueError(f"声音只能是 {', '.join(AUDIO_MODES)}")
    shot = db.get(Shot, shot_id)
    if shot is None:
        raise ValueError("镜头不存在")
    plan = db.get(ShotPlan, shot.shot_plan_id)
    b = director_brief(db, shot, plan)
    if scene_id:
        scene = store.get_scene(db, scene_id)
        if (scene.notes_json or {}).get("shot_id") not in (None, shot.id):
            raise ValueError("这个场景不是这一镜的")
        if scene.box_project_id:
            scene = store.export_box(db, scene.box_project_id)     # 带上 3D-BOX 里的改动
        repairs, framing = [], {"camera": "user"}
    else:
        # 一场戏只演一次：同一分镜计划、同一剧本场次已经搭过的导演场景直接复用，不再让 LLM 每镜重新搭景
        # （以前每镜各一套站位/朝向，镜头之间对不上）。本镜只换机位（auto_frame 按景别/焦点试机位）。
        def _plan_once() -> tuple[Any, list]:
            protocol, rep = planner.generate_protocol(db, b["brief"], duration=b["duration"])
            protocol.setdefault("meta", {})["title"] = f"场 {shot.scene_id or shot.id}：{(shot.description or '').strip()[:24]}"
            bind_cast(db, protocol, b["cast"])
            sc = store.create_from_protocol(db, protocol, source="shot", prompt=b["brief"],
                                            notes={"shot_id": shot.id, "plan_id": plan.id, "repairs": rep,
                                                   "stage_scene_key": stage_scene_key(plan, shot)})
            return sc, rep

        scene, repairs, reused = staged_scene(db, plan, shot, _plan_once)
        framing = auto_frame(db, scene, b["duration"], shot_size=b["shot_size"], focus_entity=b["focus"])
        framing["shared_scene"] = reused
    # 演员和人物的对应：协议里 character_ref=e:<实体 id> 是唯一依据（3D-BOX 里改的也认）；
    # 没绑的（用户新加的演员、旧场景）才退回按 p1、p2… 或协议顺序
    bound = dict(_bound(scene.protocol_json or {}))
    ids = [a.get("id") for a in (scene.protocol_json or {}).get("actors") or []]
    actors = [bound.get(e) for e in b["cast"]]
    if not all(actors):
        actors = [f"p{i}" for i in range(1, len(b["cast"]) + 1)]
        if not set(actors) <= set(ids):
            actors = ids[: len(b["cast"])]
    size = PROFILES.get(profile or "")
    final: dict[str, Any] = {"renderer": "ltx_25", "control_type": control_type, "prompt": b["prompt"],
                             "use_llm_prompt": False, "seed": seed}
    if size:
        final["resolution"] = list(size)
    track = dialogue_track(db, shot) if audio == "auto" and not frames_only else None
    if track:
        final.update(audio_mode="drive", audio_track=track[0], duration_sec=round(min(20.0, max(MIN_SEC, track[1] / 1000)), 2))
    elif audio == "none":
        final["audio_mode"] = "none"
    job = jobs.submit_blender(db, scene, render_plan={"output_resolution": size} if size else None, chain={
        "shot_id": shot.id,
        "identity": {"shot_id": shot.id, "shot_size": b["shot_size"], "focus": b["focus"], "location": b["location"], "cast": b["cast"], "looks": b["looks"], "actors": actors,
                     "prompt": b["background"],
                     "chapter_order": b["chapter_order"], "profile_id": b["profile_id"], "seed": seed},
        **({} if frames_only else {"final": final}),
    })
    # 画布刷新或换页后还找得到这一镜正在跑的导演任务（成片挂回时另记 camera_json.director）
    shot.camera_json = {**(shot.camera_json or {}),
                        "director_run": {"scene_id": scene.id, "box_project_id": scene.box_project_id,
                                         "blender_job_id": job.id, "started_at": utcnow().isoformat()}}
    db.commit()
    return {"shot": shot.order_no, "scene_id": scene.id, "blender_job_id": job.id, "duration": b["duration"],
            "profile": profile, "resolution": list(size) if size else None,
            "audio": "drive" if track else ("none" if audio == "none" else "generate"),
            "cast": len(b["cast"]), "brief": b["brief"], "prompt": b["prompt"], "repairs": repairs,
            "framing": framing}


def plan_shot_scene(db: Session, shot_id: str, *, instruction: str | None = None,
                    model: str | None = None) -> dict[str, Any]:
    """分镜 → LLM 规划并生成 3D 白模场景（不提交渲染任务），同步回 3D-BOX 项目。

    若镜头已有关联的 3D-BOX 项目，直接将新生成的场景脚本写入该项目并重新编译，
    保持画布上的节点 ID 与连线关系不变。
    """
    shot = db.get(Shot, shot_id)
    if shot is None:
        raise ValueError("镜头不存在")
    plan = db.get(ShotPlan, shot.shot_plan_id)
    b = director_brief(db, shot, plan)
    brief = b["brief"]
    if instruction and instruction.strip():
        brief += f"\n补充修改要求：{instruction.strip()}"
    brief += "\n【重要演出要求】：场景必须有连贯生动的人物动作表演与明确的机位取景。即便镜头要求为固定机位，也必须通过 camera.frame 或 static 运镜明确对准主体角色构图，严禁人物静止站立或机位缺乏取景。"

    protocol, repairs = planner.generate_protocol(db, brief, duration=b["duration"], model=model)
    protocol.setdefault("meta", {})["title"] = f"镜 {shot.order_no}：{(shot.description or '').strip()[:24]}"
    bind_cast(db, protocol, b["cast"])

    existing_run = (shot.camera_json or {}).get("director_run") or {}
    existing_box_id = existing_run.get("box_project_id") if isinstance(existing_run, dict) else None

    scene = store.create_from_protocol(db, protocol, source="shot", prompt=brief,
                                       notes={"shot_id": shot.id, "plan_id": plan.id, "repairs": repairs})
    if existing_box_id:
        p = db.get(SceneProject, existing_box_id)
        if p is not None:
            old_pid = scene.box_project_id
            scene.box_project_id = existing_box_id
            sp = store.SceneProtocol.model_validate(scene.protocol_json)
            store._sync_box(db, scene, sp, f"重新生成（镜 {shot.order_no}）")
            if old_pid and old_pid != existing_box_id:
                temp_p = db.get(SceneProject, old_pid)
                if temp_p:
                    db.delete(temp_p)

    framing = {"camera": "planner"}
    try:
        framing = auto_frame(db, scene, b["duration"], shot_size=b["shot_size"], focus_entity=b["focus"])
    except Exception as exc:
        log.warning("auto_frame 失败或跳过（保留 planner 机位）：%s", exc)

    shot.camera_json = {
        **(shot.camera_json or {}),
        "director_run": {
            **(existing_run if isinstance(existing_run, dict) else {}),
            "scene_id": scene.id,
            "box_project_id": scene.box_project_id,
            "updated_at": utcnow().isoformat(),
        }
    }
    db.commit()
    return {
        "shot_id": shot.id,
        "order_no": shot.order_no,
        "scene_id": scene.id,
        "box_project_id": scene.box_project_id,
        "duration": b["duration"],
        "brief": brief,
        "repairs": len(repairs),
        "framing": framing,
    }


def run_status(db: Session, shot: Shot) -> dict[str, Any] | None:
    """这一镜最近一次导演出片走到哪一步：预演 → 身份首帧 → 成片 → 挂回。没跑过返回 None。"""
    from app.models import DirectorJob

    run = (shot.camera_json or {}).get("director_run") or {}
    bj = db.get(DirectorJob, run.get("blender_job_id")) if run.get("blender_job_id") else None
    if bj is None:
        return None
    nxt = (bj.progress_json or {}).get("next") or {}
    fj = db.get(DirectorJob, nxt["job_id"]) if nxt.get("job_id") else None
    if bj.status in ("queued", "running"):
        step, status, error = "previs", bj.status, None
    elif bj.status != "succeeded":
        step, status, error = "previs", bj.status, bj.error
    elif fj is not None:
        step, status, error = "final", fj.status, fj.error
    else:
        step, status, error = nxt.get("step") or "identity", nxt.get("status") or "queued", nxt.get("error")
    bound = ((shot.camera_json or {}).get("director") or {}).get("blender_job_id") == bj.id
    chain = (getattr(bj, "input_json", None) or {}).get("chain") or {}
    frames_only = bool(chain) and not chain.get("final")
    return {"blender_job_id": bj.id, "final_job_id": fj.id if fj else None, "step": step, "status": status,
            "error": error, "frames_only": frames_only,
            "done": (step == "identity" and status == "succeeded") if frames_only
            else bool(bound and fj is not None and fj.status == "succeeded"),
            "percent": ((fj.progress_json if fj else bj.progress_json) or {}).get("percent"),
            "first_frame_url": nxt.get("first_frame_url"), "started_at": run.get("started_at"),
            "can_continue": bj.status == "succeeded" and (step == "identity" and status == "failed"
                                                         or (fj is not None and fj.status in ("failed", "cancelled")))}
