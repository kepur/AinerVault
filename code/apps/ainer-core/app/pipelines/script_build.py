"""剧本生成：Chapter → ScriptDoc(Scene → Block)。

三条约束写死在这里：
1. ScriptDoc 语言无关，只算一次。翻译是 Block 的语言层，不是另一份剧本。
2. action / scene_break 不进翻译线 —— 它们只服务画面生成。
3. 重新生成时继承上一版的人工编辑，绝不静默覆盖。
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ids import new_id
from app.models import (
    BlockType, Chapter, DocStatus, Scene, ScriptBlock, ScriptDoc, utcnow,
)
from app.pipelines.base import PipelineError, chat_json, fingerprint

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

拆解规则：
1. 先按【场景】切分 —— 场景的边界是时间、地点或视角的改变，不是段落。
   每个场景标注：时间(晨/日/黄昏/夜)、地点、天气、情绪基调、一句话梗概。
2. 场景内按【块】切分，每块标注类型：
   - narration    旁白/环境描写/心理外的叙述
   - dialogue     角色说的话（必须标 speaker，用原文中的称呼）
   - action       动作与动作描写 —— 供画面生成使用
   - inner_monolog 内心独白
   - signage      画面中出现的文字（招牌/信件/告示）
   - heading      标题
   - scene_break  分场分隔
3. dialogue 的 text 只放话语本身，不要包含「他说」「李白道」这类引导语；
   引导语若含动作信息，另起一个 action 块。
4. 保持原文顺序，不增删情节，不改写措辞。text 使用原文原句。
5. speaker 用原文中出现的称呼原样填写，不要归一化、不要翻译。"""


def _user_prompt(chapter: Chapter, granularity: str) -> str:
    hint = {
        "coarse": "场景切得粗一些，一个场景可以包含较长的连续叙述。",
        "medium": "场景粒度适中。",
        "fine": "场景切得细一些，时间或地点稍有变化就分场。",
    }.get(granularity, "场景粒度适中。")
    title = chapter.title or f"第 {chapter.order_no} 章"
    return f"{hint}\n\n【章节】{title}\n\n【正文】\n{chapter.content}"


def _active_doc(db: Session, chapter_id: str) -> ScriptDoc | None:
    return db.execute(
        select(ScriptDoc)
        .where(ScriptDoc.chapter_id == chapter_id, ScriptDoc.status == DocStatus.active)
    ).scalars().first()


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
    granularity: str = "medium",
    keep_human_edits: bool = True,
    activate: bool = True,
) -> ScriptDoc:
    """生成新版本 ScriptDoc。已有版本不被覆盖，便于比较与回滚。"""
    if not (chapter.content or "").strip():
        raise PipelineError("章节正文为空，无法生成剧本")

    novel_id = chapter.novel_id
    fp = fingerprint(chapter.content, granularity)
    prev = _active_doc(db, chapter.id)

    if prev is not None and prev.input_fingerprint == fp and keep_human_edits:
        log.info("章节 %s 指纹未变，复用 ScriptDoc v%s", chapter.id, prev.version)
        return prev

    data, task = chat_json(
        db,
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _user_prompt(chapter, granularity)},
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
    if prev is not None and keep_human_edits:
        prev_scenes, prev_blocks = _human_edits(db, prev)

    doc = ScriptDoc(
        id=new_id("sd"),
        chapter_id=chapter.id,
        version=_next_version(db, chapter.id),
        status=DocStatus.draft,
        language_source=_source_language(db, chapter),
        input_fingerprint=fp,
        generator_meta={
            "model": task.model,
            "provider": task.provider,
            "granularity": granularity,
            "usage": task.usage_json,
            "inherited_edits": len(prev_scenes) + len(prev_blocks),
        },
    )
    db.add(doc)
    db.flush()

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

        for b_raw in s_raw.get("blocks") or []:
            seq += 1
            text = str(b_raw.get("text") or "").strip()
            if not text:
                continue
            kept = prev_blocks.get(seq)
            try:
                btype = BlockType(b_raw.get("type") or "narration")
            except ValueError:
                btype = BlockType.narration

            block = ScriptBlock(
                id=new_id("bk"),
                script_doc_id=doc.id,
                scene_id=scene.id,
                seq_no=seq,
                block_type=kept.block_type if kept else btype,
                source_text=kept.source_text if kept else text,
                speaker_tag=(kept.speaker_tag if kept else b_raw.get("speaker")) or None,
                speaker_entity_id=kept.speaker_entity_id if kept else None,
                edited_by_human=bool(kept),
            )
            db.add(block)
            block_count += 1
            if block.block_type == BlockType.dialogue:
                dialogue_count += 1

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
    """一个章节同时只有一个 active 版本。"""
    others = db.execute(
        select(ScriptDoc).where(
            ScriptDoc.chapter_id == doc.chapter_id,
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
