"""电影剧本生成：锁定译本 → ScriptDoc(Scene → Block)。

三条约束写死在这里：
1. prose 与 screenplay 独立留档；目标世界剧本只能读取完整、锁定的译本。
2. 原语言制作可以读原文，但不能在目标剧本里逐段回退原文。
3. 重新生成时只继承同一世界投影的人工编辑，绝不交叉污染。
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ids import new_id
from app.models import (
    BlockType, Chapter, DocMode, DocStatus, Scene, ScriptBlock, ScriptDoc,
    TranslationBlock, WorldTransform, utcnow,
)
from app.pipelines.base import PipelineError, chat_json, fingerprint, as_text, as_items
from app.pipelines.entity_surfaces import load_entity_surfaces

log = logging.getLogger(__name__)

SCRIPT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["scenes"],
    "properties": {
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["order", "blocks"],
                "properties": {
                    "order": {"type": "integer"},
                    "title": {"type": "string"},
                    "time_of_day": {"type": "string"},
                    "location_text": {"type": "string"},
                    "weather": {"type": "string"},
                    "mood": {"type": "string"},
                    "summary": {"type": "string"},
                    "blocks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["type", "text"],
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "enum": [t.value for t in BlockType],
                                },
                                "text": {"type": "string"},
                                "speaker": {"type": "string"},
                            },
                        },
                    },
                },
            },
        }
    },
}

SYSTEM_PROMPT = """你是专业的影视改编编剧，把小说章节拆解为结构化剧本。

这是无旁白的电影小说，不是有声书，也不是“图片配朗读”。输入中的叙述不能
交给旁白念，必须尽可能改写成观众能看见的动作、人物反应、环境变化、空镜或
视觉转场。只能补足把已知起点连接到已知结果所必需的最小物理过程，不能改情节。

拆解规则：
1. 先按【场景】切分 —— 场景的边界是时间、地点或视角的改变，不是段落。
   每个场景标注：时间(晨/日/黄昏/夜)、地点、天气、情绪基调、一句话梗概。
2. 场景内按【块】切分，每块标注类型：
   - narration    仅限暂时无法直接可视化的语义备注；不会配音，且相邻必须有
                  action／场景信息把它落实为画面
   - dialogue     角色说的话（必须标 speaker，用原文中的称呼）
   - action       动作与动作描写 —— 供画面生成使用
   - inner_monolog 内心独白
   - signage      画面中出现的文字（招牌/信件/告示）
   - heading      标题
   - scene_break  分场分隔
3. dialogue 的 text 只放话语本身，不要包含「他说」「李白道」这类引导语；
   引导语若含动作信息，另起一个 action 块。
4. 保持输入的锁定版本顺序，不增删情节，不改写措辞。text 使用输入原句。
5. speaker 使用输入文本中出现的称呼原样填写，不要改回另一个语言或世界观的名字。
6. 只可以补出把小说叙述改成可拍摄动作所必需的最小过程；不得新增人物、动机、
   胜负、伤亡、线索或任何会改变情节因果的内容。
7. 每场的时间、地点、天气、氛围必须具体；动作写清主体、起始状态、位移／接触、
   结果状态。心理活动用视线、呼吸、手部动作、面部反应或环境对应物表现，不让旁白解释。
8. 对白保持输入原句，但长对白前后要留下听者反应、手部细节或环境变化的 action，
   供分镜切换机位；不要让一个人物对着静止画面连续说十几秒。"""


def _user_prompt(chapter: Chapter, granularity: str, content: str) -> str:
    hint = {
        "coarse": "场景切得粗一些，一个场景可以包含较长的连续叙述。",
        "medium": "场景粒度适中。",
        "fine": "场景切得细一些，时间或地点稍有变化就分场。",
    }.get(granularity, "场景粒度适中。")
    title = chapter.title or f"第 {chapter.order_no} 章"
    return f"{hint}\n\n【章节】{title}\n\n【正文】\n{content}"


def _active_doc(db: Session, chapter_id: str) -> ScriptDoc | None:
    return db.execute(
        select(ScriptDoc)
        .where(
            ScriptDoc.chapter_id == chapter_id,
            ScriptDoc.doc_mode == DocMode.screenplay,
            ScriptDoc.status == DocStatus.active,
        )
    ).scalars().first()


def _production_text(
    db: Session, chapter: Chapter, transform: WorldTransform | None,
) -> tuple[str, dict[str, Any]]:
    """Resolve the exact text that the screenplay adapter is allowed to read.

    A target-world screenplay must be derived from the reviewed prose translation,
    not from ``chapter.content``.  Falling back block by block would be especially
    dangerous: the result looks complete while names, registers and world rules jump
    between the source and target cultures within one scene.
    """
    if transform is None:
        return (chapter.content or "").strip(), {
            "production_source": "original",
            "transform_id": None,
        }

    prose_doc = db.execute(
        select(ScriptDoc).where(
            ScriptDoc.chapter_id == chapter.id,
            ScriptDoc.doc_mode == DocMode.prose,
            ScriptDoc.status == DocStatus.active,
        )
    ).scalars().first()
    if prose_doc is None:
        raise PipelineError(
            "这一章还没有译本分块：先走「译本 → 分块」，"
            "再从审核锁定的译本转电影剧本"
        )

    blocks = list(db.execute(
        select(ScriptBlock).where(ScriptBlock.script_doc_id == prose_doc.id)
        .order_by(ScriptBlock.seq_no)
    ).scalars())
    translations = {
        t.script_block_id: t
        for t in db.execute(
            select(TranslationBlock).where(
                TranslationBlock.script_block_id.in_([b.id for b in blocks] or [""]),
                TranslationBlock.transform_id == transform.id,
            )
        ).scalars()
    }
    required = [b for b in blocks if b.translatable]
    missing = [b.seq_no for b in required
               if not (translations.get(b.id)
                       and (translations[b.id].translated_text or "").strip())]
    unlocked = [b.seq_no for b in required
                if translations.get(b.id) and not translations[b.id].locked]
    if missing or unlocked:
        pieces = []
        if missing:
            pieces.append(f"缺译文 {len(missing)} 段（如 #{missing[0]}）")
        if unlocked:
            pieces.append(f"未锁定 {len(unlocked)} 段（如 #{unlocked[0]}）")
        raise PipelineError(
            "目标世界剧本只能从完整、已锁定的译本生成：" + "；".join(pieces)
        )

    paragraphs: list[str] = []
    for block in blocks:
        text = ((translations[block.id].translated_text or "").strip()
                if block.translatable else (block.source_text or "").strip())
        if text:
            paragraphs.append(text)
    content = "\n\n".join(paragraphs)
    return content, {
        "production_source": "locked_translation",
        "transform_id": transform.id,
        "prose_doc_id": prose_doc.id,
        "target_language": transform.target_language_code,
        "translation_blocks": len(required),
    }


def _next_version(db: Session, chapter_id: str) -> int:
    versions = db.execute(
        select(ScriptDoc.version).where(ScriptDoc.chapter_id == chapter_id)
    ).scalars().all()
    return (max(versions) + 1) if versions else 1


def _human_edits(db: Session, doc: ScriptDoc) -> tuple[dict[int, Scene], dict[int, ScriptBlock]]:
    """按序号索引上一版中被人改过的场景与块。"""
    scenes = {
        s.order_no: s
        for s in db.execute(
            select(Scene).where(Scene.script_doc_id == doc.id, Scene.edited_by_human.is_(True))
        ).scalars()
    }
    blocks = {
        b.seq_no: b
        for b in db.execute(
            select(ScriptBlock).where(
                ScriptBlock.script_doc_id == doc.id, ScriptBlock.edited_by_human.is_(True)
            )
        ).scalars()
    }
    return scenes, blocks


def count_human_edits(db: Session, chapter_id: str) -> int:
    """供 API 在覆盖前告诉用户「将丢弃 N 处人工编辑」。"""
    doc = _active_doc(db, chapter_id)
    if doc is None:
        return 0
    scenes, blocks = _human_edits(db, doc)
    return len(scenes) + len(blocks)


def build_script(
    db: Session,
    chapter: Chapter,
    *,
    transform: WorldTransform | None = None,
    granularity: str = "medium",
    keep_human_edits: bool = True,
    activate: bool = True,
) -> ScriptDoc:
    """生成新版本 ScriptDoc。已有版本不被覆盖，便于比较与回滚。"""
    if not (chapter.content or "").strip():
        raise PipelineError("章节正文为空，无法生成剧本")

    novel_id = chapter.novel_id
    production_text, production_meta = _production_text(db, chapter, transform)
    if not production_text:
        raise PipelineError("用于剧本转换的文本为空")
    fp = fingerprint(production_text, granularity, transform.id if transform else "source")
    prev = _active_doc(db, chapter.id)

    if prev is not None and prev.input_fingerprint == fp and keep_human_edits:
        log.info("章节 %s 指纹未变，复用 ScriptDoc v%s", chapter.id, prev.version)
        return prev

    data, task = chat_json(
        db,
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _user_prompt(chapter, granularity, production_text)},
        ],
        SCRIPT_SCHEMA,
        purpose="script",
        novel_id=novel_id,
        chapter_id=chapter.id,
        ref_kind="script",
        ref_id=chapter.id,
    )

    scenes_raw = data.get("scenes") or []
    if not scenes_raw:
        raise PipelineError("模型未返回任何场景")

    prev_scenes, prev_blocks = ({}, {})
    # 人工改动只能在同一个世界投影内继承。从英国维多利亚版切到
    # 现代美国版时，旧的地点、称谓与道具都是新世界的污染源。
    same_projection = bool(
        prev is not None
        and (prev.generator_meta or {}).get("transform_id")
        == production_meta.get("transform_id")
    )
    if prev is not None and keep_human_edits and same_projection:
        prev_scenes, prev_blocks = _human_edits(db, prev)

    doc = ScriptDoc(
        id=new_id("sd"),
        chapter_id=chapter.id,
        version=_next_version(db, chapter.id),
        status=DocStatus.draft,
        doc_mode=DocMode.screenplay,
        language_source=(transform.target_language_code if transform
                         else _source_language(db, chapter)),
        input_fingerprint=fp,
        generator_meta={
            "model": task.model,
            "provider": task.provider,
            "granularity": granularity,
            "usage": task.usage_json,
            "inherited_edits": len(prev_scenes) + len(prev_blocks),
            **production_meta,
        },
    )
    db.add(doc)
    db.flush()

    # 模型输出的是当前生产语言的人名。生成时就回绑稳定 entity_id，
    # 后面的音色、身份锚和时期素材不再靠文字碰运气。
    entity_index = load_entity_surfaces(
        db, chapter.novel_id,
        transform_id=transform.id if transform else None,
    )

    seq = 0
    block_count = 0
    dialogue_count = 0

    for s_idx, s_raw in enumerate(sorted(scenes_raw, key=lambda x: x.get("order", 0)), start=1):
        keep = prev_scenes.get(s_idx)
        scene = Scene(
            id=new_id("sc"),
            script_doc_id=doc.id,
            order_no=s_idx,
            title=(keep.title if keep else s_raw.get("title")) or None,
            time_of_day=(keep.time_of_day if keep else s_raw.get("time_of_day")) or None,
            location_text=(keep.location_text if keep else s_raw.get("location_text")) or None,
            weather=(keep.weather if keep else s_raw.get("weather")) or None,
            mood=(keep.mood if keep else s_raw.get("mood")) or None,
            summary=(keep.summary if keep else s_raw.get("summary")) or None,
            edited_by_human=bool(keep),
        )
        if keep is not None:
            scene.location_entity_id = keep.location_entity_id
            scene.bg_asset_id = keep.bg_asset_id
            scene.bgm_asset_id = keep.bgm_asset_id
            scene.ambience_asset_id = keep.ambience_asset_id
        db.add(scene)
        db.flush()

        for b_raw in as_items(s_raw, "blocks"):
            seq += 1
            text = as_text(b_raw.get("text"))
            if not text:
                continue
            kept = prev_blocks.get(seq)
            try:
                btype = BlockType(b_raw.get("type") or "narration")
            except ValueError:
                btype = BlockType.narration

            speaker_tag = (kept.speaker_tag if kept else b_raw.get("speaker")) or None
            speaker_entity = entity_index.by_surface.get(str(speaker_tag or "").strip())
            block = ScriptBlock(
                id=new_id("bk"),
                script_doc_id=doc.id,
                scene_id=scene.id,
                seq_no=seq,
                block_type=kept.block_type if kept else btype,
                source_text=kept.source_text if kept else text,
                speaker_tag=speaker_tag,
                speaker_entity_id=(kept.speaker_entity_id if kept else
                                   (speaker_entity.id if speaker_entity else None)),
                edited_by_human=bool(kept),
            )
            db.add(block)
            block_count += 1
            if block.block_type == BlockType.dialogue:
                dialogue_count += 1

    # 先 flush 再统计。session 是 autoflush=False 的，
    # 在 flush 之前查 script_blocks 只能查到空 —— 块还在 session 里没落库。
    # 表现是 stats.translatable 恒为 0，而单个块的 translatable 是 true，
    # 前端据此显示「无内容可翻译」，人会以为拆剧本失败了。
    db.flush()
    doc.stats_json = {
        "scenes": len(scenes_raw),
        "blocks": block_count,
        "dialogues": dialogue_count,
        "translatable": _count_translatable(db, doc.id),
    }
    db.flush()

    if activate:
        activate_doc(db, doc)
    return doc


def _count_translatable(db: Session, doc_id: str) -> int:
    from app.models import TRANSLATABLE_TYPES

    blocks = db.execute(
        select(ScriptBlock).where(ScriptBlock.script_doc_id == doc_id)
    ).scalars().all()
    return sum(1 for b in blocks if b.block_type in TRANSLATABLE_TYPES)


def _source_language(db: Session, chapter: Chapter) -> str:
    from app.models import Novel

    novel = db.get(Novel, chapter.novel_id)
    return novel.source_language_code if novel else "zh-CN"


def activate_doc(db: Session, doc: ScriptDoc) -> ScriptDoc:
    """同一章每种文档各有一个 active 版本。

    prose 是经审核的译本，screenplay 是它的电影化投影。两者不是
    互斥版本；把 prose 归档会让后面的有声书与译本预览突然消失。
    """
    others = db.execute(
        select(ScriptDoc).where(
            ScriptDoc.chapter_id == doc.chapter_id,
            ScriptDoc.doc_mode == doc.doc_mode,
            ScriptDoc.id != doc.id,
            ScriptDoc.status == DocStatus.active,
        )
    ).scalars().all()
    for o in others:
        o.status = DocStatus.archived
        o.updated_at = utcnow()
    doc.status = DocStatus.active
    doc.updated_at = utcnow()
    db.flush()
    return doc
