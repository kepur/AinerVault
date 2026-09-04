"""控制台 —— 把十七个能力页串成一条走得下去的路。

后台原来是**能力的平铺**：十七个页面并列在侧栏，每个都完整、每个都要你
先在别处选好小说和章节，进去只说一句「先在书架选一个章节」。
知道流程的人用得动，第一次打开的人看到的是一排图标。

本模块换成**对象的下钻**：小说 → 章节 → 工作台。
能力不再是并列的目的地，而是某个对象在某个阶段该做的那件事。

三条设计约束：

**每个对象都要算出自己的下一步。** 「这本书做到哪了」不能靠人对着七个页面
自己拼。阶段是有序的、可判定的 —— 第一个没做完的就是下一步。

**做没做完要给分子分母，不给百分比。** 「译本 62%」看不出是「还差三章」
还是「还差三百章」，而这两件事的处置完全不同。

**阻塞要说清是谁挡着。** 「尾帧 0/30」本身不是问题，它前面还有「首帧 0/30」；
把两条并列展示，人会去点尾帧然后发现点不动。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import (
    TRANSLATABLE_TYPES, AssetSpec, AudioKind, AudioSpec, Chapter, CrewSheet,
    DocMode, DocStatus, FrameRole, FrameSpec, Novel, ScriptBlock, ScriptDoc,
    Shot, ShotMotion, ShotPerformance, ShotPlan, TranslationBlock, VoiceCasting,
    WorldEntity, WorldLexicon, WorldTransform,
)

router = APIRouter(prefix="/api/v2", tags=["console"])


def _stage(key: str, name: str, done: int, total: int, *, page: str,
           hint: str = "", blocked_by: str | None = None,
           countable: bool = True) -> dict[str, Any]:
    """一个阶段。

    total=0 有两种含义，必须分开：**「这一步不适用」**（比如没有分镜时
    谈不上首帧）和**「一件都还没做」**。前者 blocked_by 有值，
    界面上置灰；后者是待办，界面上高亮。混在一起的话，
    人会去点一个点不动的按钮，然后以为是坏了。

    countable=False 是第三种：**这不是一件要做完的事，是一个出口。**
    交付与手动模式永远「可以打开」，没有做完不做完之说 ——
    给它算个 0/0 的完成度，界面上就成了一件永远做不完的待办。
    """
    if not countable:
        state = "blocked" if blocked_by else "open"
    else:
        state = ("blocked" if blocked_by else
                 "done" if total and done >= total else
                 "partial" if done else "todo")
    return {
        "key": key, "name": name, "done": done, "total": total,
        "page": page, "hint": hint, "blocked_by": blocked_by,
        "countable": countable, "state": state,
    }


def _next_step(stages: list[dict[str, Any]]) -> dict[str, Any] | None:
    """第一个没做完、又没被挡住的阶段。

    被挡住的不算下一步 —— 指向一个点不动的地方，比不指还糟。
    """
    for s in stages:
        if not s.get("countable", True):
            continue
        if s["state"] in ("todo", "partial") and not s["blocked_by"]:
            return {"key": s["key"], "name": s["name"], "page": s["page"],
                    "done": s["done"], "total": s["total"]}
    return None


def _count(db: Session, model: Any, *where: Any) -> int:
    return db.execute(
        select(func.count()).select_from(model).where(*where)).scalar() or 0


# ── 小说级 ────────────────────────────────────────────────────────────────────

def novel_stages(db: Session, novel_id: str) -> list[dict[str, Any]]:
    """一本书在开工前要备齐的东西，按依赖顺序。

    这些是**整本共享**的：人物长什么样、名物怎么译、谁是什么嗓子。
    放在章节里做会导致每章各定一套，第二十章的人和第一章不是同一个人。
    """
    chapters = _count(db, Chapter, Chapter.novel_id == novel_id)
    entities = _count(db, WorldEntity, WorldEntity.novel_id == novel_id)
    transforms = list(db.execute(
        select(WorldTransform).where(WorldTransform.novel_id == novel_id)).scalars())
    tf_ids = [t.id for t in transforms]

    lex_total = lex_done = 0
    if tf_ids:
        lex_total = _count(db, WorldLexicon, WorldLexicon.transform_id.in_(tf_ids))
        lex_done = _count(db, WorldLexicon, WorldLexicon.transform_id.in_(tf_ids),
                          WorldLexicon.target_term.isnot(None))

    # 素材库：抽出来的刀剑、宗门、场景。**每件都要有参考图** ——
    # 没有参考图的素材等于没抽：下一次画同一把刀，模型还是照着
    # 文字重新捏一把，两镜之间对不上。
    specs = _count(db, AssetSpec, AssetSpec.novel_id == novel_id)
    with_ref = 0
    if specs:
        from app.models import AssetVariant

        spec_ids = select(AssetSpec.id).where(AssetSpec.novel_id == novel_id)
        with_ref = db.execute(
            select(func.count(func.distinct(AssetVariant.asset_spec_id)))
            .where(AssetVariant.asset_spec_id.in_(spec_ids),
                   AssetVariant.ref_asset_ids.isnot(None))
        ).scalar() or 0

    anchors = 0
    castings = 0
    if entities:
        ent_ids = select(WorldEntity.id).where(WorldEntity.novel_id == novel_id)
        from app.models import AssetEpoch

        anchors = db.execute(
            select(func.count(func.distinct(AssetEpoch.entity_id)))
            .where(AssetEpoch.entity_id.in_(ent_ids),
                   AssetEpoch.identity_ref_asset_id.isnot(None))
        ).scalar() or 0
        castings = db.execute(
            select(func.count(func.distinct(VoiceCasting.cast_key)))
            .where(VoiceCasting.entity_id.in_(ent_ids))
        ).scalar() or 0
        # 旁白没有实体，但它是全片出现最多的那把嗓子，必须算进去
        castings += _count(db, VoiceCasting, VoiceCasting.entity_id.is_(None))

    no_ch = "还没有章节" if not chapters else None
    no_ent = "还没有世界模型" if not entities else None
    no_tf = "还没有映射" if not transforms else None

    return [
        _stage("chapters", "章节", chapters, max(chapters, 1), page="library",
               hint="整本 txt 拖进来，或粘贴，或走 API"),
        _stage("entities", "世界模型", entities, max(entities, 1), page="model",
               hint="人物 · 场景 · 道具 · 风格，整本共享", blocked_by=no_ch),
        _stage("transform", "映射与圈层", len(transforms), max(len(transforms), 1),
               page="world", hint="源圈层 → 目标圈层，决定译法与画风",
               blocked_by=no_ch),
        _stage("lexicon", "名物词表", lex_done, lex_total, page="world",
               hint="直译会破坏世界观真实感的词，在这里定译法",
               blocked_by=no_tf),
        _stage("assets", "素材库 · 参考图", with_ref, specs, page="prompts",
               hint="刀剑 宗门 服装 场景 —— 抽一次，全书复用。"
                    "有参考图的才叫备好：没有的话下一镜还是重新捏一把",
               blocked_by=no_ch),
        _stage("epochs", "人物时期与身份锚", anchors, entities, page="epochs",
               hint="脸跨期不变，衣着兵器随期变；锚是保脸的底图",
               blocked_by=no_ent),
        _stage("casting", "配音表", castings, entities + 1, page="casting",
               hint="整本一起配，撞声才检得出来", blocked_by=no_ent),
    ]


def _default_transform(db: Session, novel_id: str) -> str | None:
    """这本书默认用哪个映射。

    多数页面（提示词台账、力度与导读、素材包）都要 transform_id 才工作，
    而它一直得靠人先去「映射与词表」点一下 —— 跳过来的人不知道还有这一步，
    只会看到「先在映射与词表选一个世界观映射」。
    只有一个映射时不该问，有多个时取最新的那个当默认。
    """
    return db.execute(
        select(WorldTransform.id).where(WorldTransform.novel_id == novel_id)
        .order_by(WorldTransform.created_at.desc()).limit(1)).scalars().first()


def _novel_card(db: Session, novel: Novel) -> dict[str, Any]:
    stages = novel_stages(db, novel.id)
    ch_ids = select(Chapter.id).where(Chapter.novel_id == novel.id)
    scripted = db.execute(
        select(func.count(func.distinct(ScriptDoc.chapter_id)))
        .where(ScriptDoc.chapter_id.in_(ch_ids),
               ScriptDoc.doc_mode == DocMode.screenplay,
               ScriptDoc.status == DocStatus.active)
    ).scalar() or 0
    doc_ids = select(ScriptDoc.id).where(
        ScriptDoc.chapter_id.in_(ch_ids), ScriptDoc.doc_mode == DocMode.screenplay,
        ScriptDoc.status == DocStatus.active)
    planned = db.execute(
        select(func.count(func.distinct(ShotPlan.script_doc_id)))
        .where(ShotPlan.script_doc_id.in_(doc_ids))
    ).scalar() or 0
    chapters = stages[0]["done"]
    return {
        "id": novel.id, "title": novel.title,
        "author": getattr(novel, "author", None),
        "transform_id": _default_transform(db, novel.id),
        "chapters": chapters,
        "scripted": scripted, "shot_planned": planned,
        "stages": stages,
        "next": _next_step(stages),
        "ready": sum(1 for s in stages if s["state"] == "done"),
        "total_stages": sum(1 for s in stages if s["countable"]),
    }


@router.get("/console")
def console(limit: int = Query(50, ge=1, le=200),
            chapters: int = Query(8, ge=0, le=50),
            db: Session = Depends(get_db)) -> dict:
    """首页。所有小说 + 各自做到哪了 + 下一步 + **前几章直接列出来**。

    章节原来要「打开工作台 → 章节表 → 进入」三步才看得到，
    而人打开后台想干的第一件事往往就是「看看第三章做成什么样了」。
    把前几章带在卡片上，那一步就从三次点击变成零次。
    """
    novels = list(db.execute(
        select(Novel).order_by(Novel.created_at.desc()).limit(limit)).scalars())
    out = []
    for n in novels:
        card = _novel_card(db, n)
        if chapters:
            rows = list(db.execute(
                select(Chapter).where(Chapter.novel_id == n.id)
                .order_by(Chapter.order_no).limit(chapters)).scalars())
            card["chapter_rows"] = [_chapter_row(db, c) for c in rows]
            card["chapter_total"] = _count(db, Chapter, Chapter.novel_id == n.id)
        out.append(card)
    return {"novels": out, "count": len(novels)}


# ── 章节级 ────────────────────────────────────────────────────────────────────

def chapter_stages(db: Session, chapter: Chapter) -> list[dict[str, Any]]:
    """一章的真实生产依赖链。

    这里刻意不允许「先画几张再说」：首帧若早于调度、制作单与
    物理运动，出图模型就只能自己猜站位、灯光、衣着与落幅；后面再补
    提示词也已经晚了。
    """
    prose_doc = db.execute(
        select(ScriptDoc).where(
            ScriptDoc.chapter_id == chapter.id,
            ScriptDoc.doc_mode == DocMode.prose,
            ScriptDoc.status == DocStatus.active,
        )
    ).scalars().first()
    doc = db.execute(
        select(ScriptDoc).where(
            ScriptDoc.chapter_id == chapter.id,
            ScriptDoc.doc_mode == DocMode.screenplay,
            ScriptDoc.status == DocStatus.active,
        )
    ).scalars().first()

    tr_total = tr_done = 0
    transform_id = _default_transform(db, chapter.novel_id)
    if prose_doc:
        tr_total = _count(
            db, ScriptBlock,
            ScriptBlock.script_doc_id == prose_doc.id,
            ScriptBlock.block_type.in_(list(TRANSLATABLE_TYPES)),
        )
        block_ids = select(ScriptBlock.id).where(
            ScriptBlock.script_doc_id == prose_doc.id,
            ScriptBlock.block_type.in_(list(TRANSLATABLE_TYPES)),
        )
        if transform_id:
            tr_done = db.execute(
                select(func.count(func.distinct(TranslationBlock.script_block_id)))
                .where(
                    TranslationBlock.script_block_id.in_(block_ids),
                    TranslationBlock.transform_id == transform_id,
                    TranslationBlock.translated_text.isnot(None),
                    TranslationBlock.locked.is_(True),
                )
            ).scalar() or 0

    wrong_projection = bool(
        doc is not None and transform_id
        and (doc.generator_meta or {}).get("transform_id") != transform_id
    )
    production_doc = None if wrong_projection else doc

    plan = db.execute(
        select(ShotPlan).where(
            ShotPlan.script_doc_id == (production_doc.id if production_doc else "")
        )
        .order_by(ShotPlan.version.desc())
    ).scalars().first() if production_doc else None

    shots = perf = crew = motion = videos = 0
    first_n = last_n = 0
    au_total = au_done = 0
    if plan:
        shot_rows = list(db.execute(
            select(Shot.id).where(Shot.shot_plan_id == plan.id)).scalars())
        shots = len(shot_rows)
        if shot_rows:
            staged_ids = set(db.execute(
                select(ShotPerformance.shot_id)
                .where(ShotPerformance.shot_id.in_(shot_rows)).distinct()
            ).scalars())
            character_shots = {
                frame.shot_id for frame in db.execute(
                    select(FrameSpec).where(
                        FrameSpec.shot_id.in_(shot_rows),
                        FrameSpec.role == FrameRole.first,
                    )
                ).scalars()
                if frame.entity_ids_json
            }
            # 纯环境空镜没有人物站位可抽，不应因此永远卡在调度阶段。
            perf = sum(1 for sid in shot_rows
                       if sid not in character_shots or sid in staged_ids)
            from app.worldview.crew import CREW

            required_roles = {c.role for c in CREW}
            by_shot: dict[str, set[str]] = {}
            for sheet in db.execute(
                select(CrewSheet).where(CrewSheet.shot_id.in_(shot_rows))
            ).scalars():
                if (sheet.role in required_roles and sheet.prompt_en
                        and not sheet.missing_json and not sheet.rejected_json):
                    by_shot.setdefault(sheet.shot_id, set()).add(sheet.role)
            crew = sum(1 for sid in shot_rows
                       if by_shot.get(sid, set()) >= required_roles)

            motions = list(db.execute(
                select(ShotMotion).where(ShotMotion.shot_id.in_(shot_rows))
            ).scalars())
            motion = sum(1 for m in motions
                         if m.motion_prompt_en and len(m.deltas_en_json or []) >= 2
                         and m.start_frame and m.end_frame
                         and m.start_frame.strip() != m.end_frame.strip())
            first_n = _count(db, FrameSpec, FrameSpec.shot_id.in_(shot_rows),
                             FrameSpec.role == FrameRole.first,
                             FrameSpec.asset_id.isnot(None))
            last_n = _count(db, FrameSpec, FrameSpec.shot_id.in_(shot_rows),
                            FrameSpec.role == FrameRole.last,
                            FrameSpec.asset_id.isnot(None))
            au_total = _count(db, AudioSpec, AudioSpec.shot_id.in_(shot_rows),
                              AudioSpec.kind == AudioKind.dialogue)
            au_done = _count(db, AudioSpec, AudioSpec.shot_id.in_(shot_rows),
                             AudioSpec.kind == AudioKind.dialogue,
                             AudioSpec.asset_id.isnot(None))
            videos = _count(db, Shot, Shot.id.in_(shot_rows),
                            Shot.video_asset_id.isnot(None))

    no_prose = "还没有译本分块" if prose_doc is None else None
    no_locked_translation = (
        f"译本还没锁定完（{tr_done}/{tr_total}）"
        if transform_id and prose_doc is not None and tr_done < tr_total else None
    )
    no_doc = (
        "当前是原文或其他映射的旧剧本，需从当前已锁定译本重生成"
        if wrong_projection else "还没有目标世界剧本" if doc is None else None
    )
    no_plan = "还没有分镜" if plan is None else None
    no_staging = (f"调度与表演还没完成（{perf}/{shots}）"
                  if plan is not None and perf < shots else None)
    no_crew = (f"八工种制作单还没逐镜齐全（{crew}/{shots}）"
               if plan is not None and crew < shots else None)
    no_motion = (f"可执行的物理运动还没齐（{motion}/{shots}）"
                 if plan is not None and motion < shots else None)
    no_first = ("首帧还没出" if plan is not None and first_n < shots else None)
    no_last = ("尾帧还没出" if plan is not None and last_n < shots else None)

    return [
        _stage("prose", "译本锁定", tr_done, max(tr_total, 1), page="prose",
               hint="原著 → 世界观 → 翻译 → 审核 → 回译 → 锁定"),
        _stage("script", "目标世界剧本", 1 if production_doc else 0, 1, page="script",
               hint="只从已锁定译本分场：时间 · 地点 · 对白 · 动作",
               blocked_by=no_prose or no_locked_translation),
        _stage("shots", "分镜", shots, max(shots, 1), page="script",
               hint="把场拆成镜，定景别与时长", blocked_by=no_doc),
        _stage("staging", "调度与表演", perf, shots, page="staging",
               hint="站位 · 朝向 · 视线 · 表情 · 动作", blocked_by=no_plan),
        _stage("crew", "八工种制作单", crew, shots, page="crew",
               hint="摄影 灯光 美术 服化 视效 调色 剪辑 声音",
               blocked_by=no_plan or no_staging),
        _stage("motion", "运动与物理连续", motion, shots, page="crew",
               hint="因果动作 · 重心接触 · 惯性 · 光影 · 微表情 · 落幅",
               blocked_by=no_plan or no_staging or no_crew),
        _stage("first_frame", "首帧", first_n, shots, page="prompts",
               hint="带身份锚的走编辑模型，锚当底图，脸才保得住",
               blocked_by=no_plan or no_staging or no_crew or no_motion),
        _stage("last_frame", "尾帧", last_n, shots, page="prompts",
               hint="从首帧派生，只改可见物理变化",
               blocked_by=no_plan or no_motion or no_first),
        _stage("audio", "对白配音", (au_done if au_total else (1 if plan else 0)),
               max(au_total, 1), page="audio",
               hint="电影只配对白；完整旁白只在有声书。TTS 真实时长决定对白镜头",
               blocked_by=no_plan),
        _stage("video", "动态镜头", videos, shots, page="cut",
               hint="每镜都读首帧、尾帧与英文物理运动；缺一项就不花额度",
               blocked_by=no_plan or no_motion or no_last),
        _stage("handoff", "成片交付 / 手动模式", 0, 0, page="handoff",
               hint="轨道时间轴 · 中英双份提示词 · 字幕与剪辑标记表",
               blocked_by=no_plan, countable=False),
    ]


def _chapter_row(db: Session, chapter: Chapter) -> dict[str, Any]:
    stages = chapter_stages(db, chapter)
    # 分母只数「要做完的」那些 —— 出口不算进度，
    # 否则一章永远差最后那一步，而那一步根本不是一件事
    countable = [s for s in stages if s["countable"]]
    return {
        "id": chapter.id, "order_no": chapter.order_no,
        "title": chapter.title, "words": chapter.word_count,
        "stages": stages,
        "next": _next_step(stages),
        "done_stages": sum(1 for s in countable if s["state"] == "done"),
        "total_stages": len(countable),
    }


@router.get("/novels/{novel_id}/desk")
def novel_desk(novel_id: str, offset: int = Query(0, ge=0),
               limit: int = Query(30, ge=1, le=200),
               db: Session = Depends(get_db)) -> dict:
    """一本书的工作台：整本共享的素材 + 章节列表（每章带自己的下一步）。

    章节分页 —— 几千章的书一次全算会把这个接口拖垮，
    而人一次也只看得过来一屏。
    """
    novel = db.get(Novel, novel_id)
    if novel is None:
        raise HTTPException(status_code=404, detail="novel not found")

    total = _count(db, Chapter, Chapter.novel_id == novel_id)
    chapters = list(db.execute(
        select(Chapter).where(Chapter.novel_id == novel_id)
        .order_by(Chapter.order_no).offset(offset).limit(limit)).scalars())

    transforms = [
        {"id": t.id, "target_language_code": t.target_language_code,
         "status": getattr(t.status, "value", str(t.status or ""))}
        for t in db.execute(
            select(WorldTransform).where(WorldTransform.novel_id == novel_id)).scalars()
    ]
    ent_by_kind: dict[str, int] = {}
    for kind, cnt in db.execute(
        select(WorldEntity.kind, func.count())
        .where(WorldEntity.novel_id == novel_id).group_by(WorldEntity.kind)
    ).all():
        ent_by_kind[getattr(kind, "value", str(kind))] = cnt

    stages = novel_stages(db, novel_id)
    return {
        "novel": {"id": novel.id, "title": novel.title,
                  "author": getattr(novel, "author", None),
                  "transform_id": _default_transform(db, novel_id)},
        "stages": stages,
        "next": _next_step(stages),
        "entities_by_kind": ent_by_kind,
        "asset_specs": _count(db, AssetSpec, AssetSpec.novel_id == novel_id),
        "transforms": transforms,
        "chapters": {
            "total": total, "offset": offset, "limit": limit,
            "items": [_chapter_row(db, c) for c in chapters],
        },
    }


@router.get("/chapters/{chapter_id}/desk")
def chapter_desk(chapter_id: str, db: Session = Depends(get_db)) -> dict:
    """一章的工作台：十个阶段各自做到哪，以及现在该点哪里。"""
    chapter = db.get(Chapter, chapter_id)
    if chapter is None:
        raise HTTPException(status_code=404, detail="chapter not found")
    novel = db.get(Novel, chapter.novel_id)
    row = _chapter_row(db, chapter)
    row["novel"] = {"id": novel.id, "title": novel.title,
                    "transform_id": _default_transform(db, novel.id)} if novel else None
    return row


@router.get("/chapters/{chapter_id}/products")
def chapter_products(chapter_id: str, db: Session = Depends(get_db)) -> dict:
    """该章节可直接试听／试看的成品与当前品质等级。"""
    from app.models import Asset, AssetKind
    from app.pipelines import audiobook, cut
    from app.pipelines.base import PipelineError

    chapter = db.get(Chapter, chapter_id)
    if chapter is None:
        raise HTTPException(status_code=404, detail="chapter not found")

    audiobook_data: dict[str, Any] = {
        "segments": 0, "generated": 0, "duration_ms": 0, "output": None,
    }
    try:
        timeline = audiobook.build_timeline(db, chapter)
        audiobook_data.update({
            "segments": timeline["stats"]["segments"],
            "generated": timeline["stats"]["generated"],
            "duration_ms": timeline["total_duration_ms"],
            "output": timeline.get("final_output"),
        })
    except PipelineError:
        pass

    doc = db.execute(
        select(ScriptDoc).where(
            ScriptDoc.chapter_id == chapter.id,
            ScriptDoc.doc_mode == DocMode.screenplay,
            ScriptDoc.status == DocStatus.active,
        )
    ).scalars().first()
    plan = db.execute(
        select(ShotPlan).where(
            ShotPlan.script_doc_id == (doc.id if doc else ""),
            ShotPlan.status == DocStatus.active,
        ).order_by(ShotPlan.version.desc())
    ).scalars().first() if doc else None

    film_data: dict[str, Any] = {
        "shot_plan_id": plan.id if plan else None,
        "quality": None, "output": None,
    }
    if plan:
        film_data["quality"] = cut.build_timeline(db, plan).get("quality")

    # 成品是内容寻址的 Asset；取这一章最近导出的一份。
    for asset in db.execute(
        select(Asset).where(
            Asset.novel_id == chapter.novel_id,
            Asset.kind.in_([AssetKind.audio, AssetKind.video]),
        ).order_by(Asset.created_at.desc())
    ).scalars():
        meta = asset.meta_json or {}
        if meta.get("chapter_id") != chapter.id:
            continue
        purpose = meta.get("purpose")
        item = {
            "asset_id": asset.id, "url": asset.url, "bytes": asset.bytes,
            "duration_ms": meta.get("duration_ms"),
            "grade": meta.get("grade"),
            "created_at": asset.created_at.isoformat() if asset.created_at else None,
        }
        if purpose == "audiobook_final" and not audiobook_data["output"]:
            audiobook_data["output"] = item
        elif purpose == "final_cut" and not film_data["output"]:
            film_data["output"] = item
        if audiobook_data["output"] and film_data["output"]:
            break

    return {
        "chapter": {"id": chapter.id, "title": chapter.title,
                    "order_no": chapter.order_no},
        "audiobook": audiobook_data,
        "film": film_data,
    }


# ── 资源库 ────────────────────────────────────────────────────────────────────
#
# 一本小说跑下来会攒下几百个文件：身份锚、素材参考图、每镜的首尾帧、
# 每句对白的音频、成片。它们原来散在五个页面里 ——
# 人物时期看锚、提示词台账看素材、分镜看帧、有声书看音频 ——
# **没有任何一处能回答「这本书一共有哪些文件」**。
#
# 更要紧的是「用在哪」。一屏缩略图不解决问题：三十张灰蒙蒙的夜戏截图摆在
# 一起，人分不出哪张是镜 7 的尾帧。所以每个文件都要带着它的用途、
# 归属对象、所在镜号一起出现 —— 那才是人脑用来定位的东西。

#: 用途 → 中文与排序。顺序照「从整本到单镜」排 ——
#: 找东西时人先想「是哪本书的什么」，再想「第几镜」
_USE_ORDER: tuple[tuple[str, str], ...] = (
    ("audiobook_final", "有声书成品"),
    ("final_cut", "章节成片／审片"),
    ("identity", "身份锚"),
    ("asset_ref", "素材参考图"),
    ("first_frame", "首帧"),
    ("last_frame", "尾帧"),
    ("video", "镜头视频"),
    ("dialogue", "对白"),
    ("narration", "旁白"),
    ("sfx", "音效"),
    ("bgm", "配乐"),
    ("ambience", "环境声"),
    ("scene_bg", "场景背景"),
    ("orphan", "未被引用"),
)
_USE_CN = dict(_USE_ORDER)


def _media_index(db: Session, novel_id: str) -> dict[str, dict[str, Any]]:
    """资产 id → 它被谁引用。

    **反查而不是正查。** 资产表本身只记「哪个任务生成了它」，
    而任务的 purpose 不足以定位（三十条 first_frame 长得一模一样）。
    要定位得知道它挂在哪个镜头、哪个角色、哪句台词上 ——
    那些信息只在引用方那里。
    """
    from app.models import (
        Asset, AssetEpoch, AssetVariant, AudioSpec, EntityWorldVisual,
        FrameSpec, Scene, Shot, WorldEntity,
    )

    idx: dict[str, dict[str, Any]] = {}

    def mark(aid: str | None, use: str, label: str, **extra: Any) -> None:
        if not aid:
            return
        idx.setdefault(aid, {"use": use, "label": label, **extra})

    # 整章成品不挂在某个镜头上，它的引用关系在 Asset.meta_json。
    # 不先标记的话，真正的成片反而会掉进「未被引用」桶里。
    for asset in db.execute(
        select(Asset).where(Asset.novel_id == novel_id)
    ).scalars():
        meta = asset.meta_json or {}
        purpose = str(meta.get("purpose") or "")
        if purpose == "audiobook_final":
            mark(asset.id, purpose, "章节有声书成品",
                 chapter_id=meta.get("chapter_id"))
        elif purpose == "final_cut":
            grade = "最终成片" if meta.get("grade") == "final" else "审片预览"
            mark(asset.id, purpose, f"章节{grade}",
                 chapter_id=meta.get("chapter_id"), grade=meta.get("grade"))

    ent_names = {
        e.id: e.display_name
        for e in db.execute(
            select(WorldEntity).where(WorldEntity.novel_id == novel_id)).scalars()
    }

    # 身份锚：跨期共用的那张脸
    for ep in db.execute(
        select(AssetEpoch).where(AssetEpoch.entity_id.in_(list(ent_names) or [""]))
    ).scalars():
        mark(ep.identity_ref_asset_id, "identity",
             f"{ent_names.get(ep.entity_id or '', '?')} · 身份锚",
             entity=ent_names.get(ep.entity_id or ""))

    # 素材参考图：刀剑宗门场景，抽一次全书复用
    spec_names = {
        s.id: s.display_name
        for s in db.execute(
            select(AssetSpec).where(AssetSpec.novel_id == novel_id)).scalars()
    }
    for var in db.execute(
        select(AssetVariant).where(
            AssetVariant.asset_spec_id.in_(list(spec_names) or [""]))
    ).scalars():
        for aid in var.ref_asset_ids or []:
            mark(aid, "asset_ref",
                 f"{spec_names.get(var.asset_spec_id, '?')} · 参考图",
                 asset_name=spec_names.get(var.asset_spec_id))

    # 每镜的帧、视频、音频
    ch_ids = [c.id for c in db.execute(
        select(Chapter).where(Chapter.novel_id == novel_id)).scalars()]
    doc_ids = [d.id for d in db.execute(
        select(ScriptDoc).where(ScriptDoc.chapter_id.in_(ch_ids or [""]))).scalars()]
    plan_ids = [p.id for p in db.execute(
        select(ShotPlan).where(ShotPlan.script_doc_id.in_(doc_ids or [""]))).scalars()]
    shots = {
        s.id: s for s in db.execute(
            select(Shot).where(Shot.shot_plan_id.in_(plan_ids or [""]))).scalars()
    }
    for shot in shots.values():
        mark(shot.video_asset_id, "video", f"镜 {shot.order_no} · 视频",
             shot=shot.order_no)
    for f in db.execute(
        select(FrameSpec).where(FrameSpec.shot_id.in_(list(shots) or [""]))
    ).scalars():
        shot = shots.get(f.shot_id)
        role = "first_frame" if f.role == FrameRole.first else "last_frame"
        mark(f.asset_id, role,
             f"镜 {shot.order_no if shot else '?'} · {_USE_CN[role]}",
             shot=shot.order_no if shot else None)
    for a in db.execute(
        select(AudioSpec).where(AudioSpec.shot_id.in_(list(shots) or [""]))
    ).scalars():
        shot = shots.get(a.shot_id or "")
        who = ent_names.get(a.entity_id or "")
        text = (a.text or "").strip().replace("\n", " ")
        mark(a.asset_id, a.kind.value,
             f"镜 {shot.order_no if shot else '?'} · {who or _USE_CN.get(a.kind.value, '')}"
             + (f"「{text[:16]}」" if text else ""),
             shot=shot.order_no if shot else None, speaker=who or None)

    for sc in db.execute(
        select(Scene).where(Scene.script_doc_id.in_(doc_ids or [""]))
    ).scalars():
        mark(sc.bg_asset_id, "scene_bg", f"{sc.title or '场景'} · 背景")
        mark(sc.bgm_asset_id, "bgm", f"{sc.title or '场景'} · 配乐")
        mark(sc.ambience_asset_id, "ambience", f"{sc.title or '场景'} · 环境声")
    return idx


@router.get("/novels/{novel_id}/media")
def novel_media(novel_id: str, use: str | None = Query(None),
                kind: str | None = Query(None),
                offset: int = Query(0, ge=0),
                limit: int = Query(120, ge=1, le=500),
                db: Session = Depends(get_db)) -> dict:
    """这本小说的全部素材文件，按用途分组，每个都带着「用在哪」。"""
    from app.models import Asset

    novel = db.get(Novel, novel_id)
    if novel is None:
        raise HTTPException(status_code=404, detail="novel not found")

    idx = _media_index(db, novel_id)
    rows = list(db.execute(
        select(Asset).where(Asset.novel_id == novel_id)
        .order_by(Asset.created_at.desc())).scalars())

    items: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    bytes_by_use: dict[str, int] = {}
    for a in rows:
        meta = idx.get(a.id) or {}
        # **未被引用的要单列出来，不能混进正常分组。**
        # 它们多半是重出时被替换掉的旧产物 —— 占着磁盘、
        # 混在缩略图里让人以为「这一镜有两张图」
        u = str(meta.get("use") or "orphan")
        counts[u] = counts.get(u, 0) + 1
        bytes_by_use[u] = bytes_by_use.get(u, 0) + int(a.bytes or 0)
        if (use and u != use) or (kind and a.kind.value != kind):
            continue
        items.append({
            "id": a.id, "url": a.url, "kind": a.kind.value, "mime": a.mime,
            "bytes": a.bytes, "created_at": a.created_at.isoformat() if a.created_at else None,
            "use": u, "use_cn": _USE_CN.get(u, u),
            "label": meta.get("label") or "（未被任何地方引用）",
            "shot": meta.get("shot"), "speaker": meta.get("speaker"),
            "entity": meta.get("entity"), "asset_name": meta.get("asset_name"),
        })

    total = len(items)
    page = items[offset:offset + limit]
    return {
        "novel": {"id": novel.id, "title": novel.title},
        "groups": [
            {"use": u, "name": cn, "count": counts.get(u, 0),
             "bytes": bytes_by_use.get(u, 0)}
            for u, cn in _USE_ORDER if counts.get(u)
        ],
        "total": total, "offset": offset, "limit": limit,
        "total_bytes": sum(bytes_by_use.values()),
        "items": page,
    }
