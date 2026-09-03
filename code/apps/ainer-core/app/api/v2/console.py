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
    AssetSpec, AudioKind, AudioSpec, Chapter, CrewSheet, DocStatus, FrameRole,
    FrameSpec, Novel, ScriptBlock, ScriptDoc, Shot, ShotMotion, ShotPerformance,
    ShotPlan, TranslationBlock, VoiceCasting, WorldEntity, WorldLexicon,
    WorldTransform,
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
        .where(ScriptDoc.chapter_id.in_(ch_ids), ScriptDoc.status == DocStatus.active)
    ).scalar() or 0
    doc_ids = select(ScriptDoc.id).where(
        ScriptDoc.chapter_id.in_(ch_ids), ScriptDoc.status == DocStatus.active)
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
            db: Session = Depends(get_db)) -> dict:
    """首页。所有小说 + 各自做到哪了 + 下一步。"""
    novels = list(db.execute(
        select(Novel).order_by(Novel.created_at.desc()).limit(limit)).scalars())
    return {
        "novels": [_novel_card(db, n) for n in novels],
        "count": len(novels),
    }


# ── 章节级 ────────────────────────────────────────────────────────────────────

def chapter_stages(db: Session, chapter: Chapter) -> list[dict[str, Any]]:
    """一章从原文走到成品要经过的每一步。

    顺序不是随便排的，是**真实的依赖**：没有剧本就没有分镜，
    没有分镜就没有帧，没有首帧就派生不出尾帧，
    没有真实音频就定不下镜头长度。
    """
    doc = db.execute(
        select(ScriptDoc).where(ScriptDoc.chapter_id == chapter.id,
                                ScriptDoc.status == DocStatus.active)
    ).scalars().first()

    blocks = tr_done = 0
    if doc:
        blocks = _count(db, ScriptBlock, ScriptBlock.script_doc_id == doc.id)
        blk_ids = select(ScriptBlock.id).where(ScriptBlock.script_doc_id == doc.id)
        tr_done = db.execute(
            select(func.count(func.distinct(TranslationBlock.script_block_id)))
            .where(TranslationBlock.script_block_id.in_(blk_ids),
                   TranslationBlock.translated_text.isnot(None))
        ).scalar() or 0

    plan = db.execute(
        select(ShotPlan).where(ShotPlan.script_doc_id == (doc.id if doc else ""))
        .order_by(ShotPlan.version.desc())
    ).scalars().first() if doc else None

    shots = perf = crew = motion = 0
    first_n = last_n = 0
    au_total = au_done = 0
    if plan:
        shot_rows = list(db.execute(
            select(Shot.id).where(Shot.shot_plan_id == plan.id)).scalars())
        shots = len(shot_rows)
        if shot_rows:
            perf = db.execute(
                select(func.count(func.distinct(ShotPerformance.shot_id)))
                .where(ShotPerformance.shot_id.in_(shot_rows))).scalar() or 0
            crew = db.execute(
                select(func.count(func.distinct(CrewSheet.shot_id)))
                .where(CrewSheet.shot_id.in_(shot_rows))).scalar() or 0
            motion = _count(db, ShotMotion, ShotMotion.shot_id.in_(shot_rows))
            first_n = _count(db, FrameSpec, FrameSpec.shot_id.in_(shot_rows),
                             FrameSpec.role == FrameRole.first,
                             FrameSpec.asset_id.isnot(None))
            last_n = _count(db, FrameSpec, FrameSpec.shot_id.in_(shot_rows),
                            FrameSpec.role == FrameRole.last,
                            FrameSpec.asset_id.isnot(None))
            au_total = _count(db, AudioSpec, AudioSpec.shot_id.in_(shot_rows),
                              AudioSpec.kind.in_([AudioKind.dialogue,
                                                  AudioKind.narration]))
            au_done = _count(db, AudioSpec, AudioSpec.shot_id.in_(shot_rows),
                             AudioSpec.kind.in_([AudioKind.dialogue,
                                                 AudioKind.narration]),
                             AudioSpec.asset_id.isnot(None))

    no_doc = "还没有剧本" if doc is None else None
    no_plan = "还没有分镜" if plan is None else None
    no_first = ("首帧还没出" if plan is not None and first_n < shots else None)

    return [
        _stage("script", "剧本转换", 1 if doc else 0, 1, page="script",
               hint="分场 · 时间 · 天气 · 氛围 · 对白"),
        _stage("prose", "译本", tr_done, blocks, page="prose",
               hint="分块 → 装置 → 翻译 → 审核 → 回译 → 锁定",
               blocked_by=no_doc),
        _stage("shots", "分镜", shots, max(shots, 1), page="script",
               hint="把场拆成镜，定景别与时长", blocked_by=no_doc),
        _stage("staging", "调度与表演", perf, shots, page="staging",
               hint="站位 · 朝向 · 视线 · 表情 · 动作", blocked_by=no_plan),
        _stage("crew", "八工种制作单", crew, shots, page="crew",
               hint="摄影 灯光 美术 服化 视效 调色 剪辑 声音",
               blocked_by=no_plan),
        _stage("motion", "运动描述", motion, shots, page="crew",
               hint="首尾之间变了什么 —— 尾帧与视频都读它", blocked_by=no_plan),
        _stage("first_frame", "首帧", first_n, shots, page="prompts",
               hint="带身份锚的走编辑模型，锚当底图，脸才保得住",
               blocked_by=no_plan),
        _stage("last_frame", "尾帧", last_n, shots, page="prompts",
               hint="从首帧派生，只改「变了什么」", blocked_by=no_plan or no_first),
        _stage("audio", "配音", au_done, au_total, page="audio",
               hint="真实时长决定镜头长度，不要按字数估", blocked_by=no_plan),
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
