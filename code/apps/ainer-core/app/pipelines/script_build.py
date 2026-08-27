"""剧本生成：章节原文 → ScriptDoc(Scene → Block)。

这就是全部流程 —— 一个普通函数，从上往下读。
没有注册表、没有 stage 事件、没有 orchestrator。要看流程就读这里。
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.capability.schemas import Capability
from app.capability.service import submit_task
from app.ids import new_id
from app.models import (
    BlockType, Chapter, DocStatus, Scene, ScriptBlock, ScriptDoc,
)
from app.prompts import SCRIPT_BUILD_USER, SCRIPT_SCHEMA, get_prompt

log = logging.getLogger(__name__)

#: 单次送给模型的最大原文字数。超过则按场景边界切段，分批处理后拼接。
MAX_CHUNK_CHARS = 6000

_VALID_TYPES = {t.value for t in BlockType}


@dataclass(slots=True)
class ScriptConfig:
    mode: str = "full"                 # full | resegment
    keep_human_edits: bool = True
    scene_granularity: str = "medium"  # coarse | medium | fine
    model: str | None = None


def fingerprint(chapter: Chapter, cfg: ScriptConfig) -> str:
    blob = json.dumps(
        {
            "content": chapter.content,
            "granularity": cfg.scene_granularity,
            "mode": cfg.mode,
            "model": cfg.model,
        },
        sort_keys=True, ensure_ascii=False,
    )
    return hashlib.sha256(blob.encode()).hexdigest()


def _split_for_llm(text: str, limit: int = MAX_CHUNK_CHARS) -> list[str]:
    """按空行分段后贪心装箱。宁可切在段落边界，也不切在句子中间。"""
    if len(text) <= limit:
        return [text]
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    buf: list[str] = []
    size = 0
    for p in paras:
        if size + len(p) > limit and buf:
            chunks.append("\n\n".join(buf))
            buf, size = [], 0
        buf.append(p)
        size += len(p) + 2
    if buf:
        chunks.append("\n\n".join(buf))
    return chunks


def _normalize_block(raw: dict) -> tuple[BlockType, str, str | None] | None:
    """模型输出的容错归一。返回 None 表示该块应丢弃。"""
    text = str(raw.get("text") or "").strip()
    if not text:
        return None

    kind = str(raw.get("type") or "narration").strip().lower()
    if kind not in _VALID_TYPES:
        # 常见的模型自由发挥：monologue / inner / dialog / desc
        kind = {
            "dialog": "dialogue", "speech": "dialogue", "line": "dialogue",
            "monologue": "inner_monolog", "inner": "inner_monolog",
            "thought": "inner_monolog", "desc": "narration",
            "description": "narration", "narrative": "narration",
            "sign": "signage", "text_on_screen": "signage",
        }.get(kind, "narration")

    block_type = BlockType(kind)
    speaker = str(raw.get("speaker") or "").strip() or None
    if block_type not in {BlockType.dialogue, BlockType.inner_monolog}:
        speaker = None
    return block_type, text, speaker


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


def _human_edits(db: Session, doc: ScriptDoc) -> tuple[dict[int, ScriptBlock], dict[int, Scene]]:
    """上一版里人工改过的块与场景，按序号索引。"""
    blocks = {
        b.seq_no: b
        for b in db.execute(
            select(ScriptBlock).where(
                ScriptBlock.script_doc_id == doc.id,
                ScriptBlock.edited_by_human.is_(True),
            )
        ).scalars()
    }
    scenes = {
        s.order_no: s
        for s in db.execute(
            select(Scene).where(
                Scene.script_doc_id == doc.id, Scene.edited_by_human.is_(True)
            )
        ).scalars()
    }
    return blocks, scenes


def count_human_edits(db: Session, chapter_id: str) -> int:
    """重新生成前用来提示「将丢弃 N 处人工编辑」。"""
    doc = _active_doc(db, chapter_id)
    if doc is None:
        return 0
    b, s = _human_edits(db, doc)
    return len(b) + len(s)


def build_script(
    db: Session, chapter: Chapter, cfg: ScriptConfig | None = None
) -> ScriptDoc:
    """生成新版本 ScriptDoc 并置为 active。旧版本转 archived，不删除。"""
    cfg = cfg or ScriptConfig()
    if not (chapter.content or "").strip():
        raise ValueError("章节正文为空，无法生成剧本")

    prev = _active_doc(db, chapter.id)
    fp = fingerprint(chapter, cfg)
    if prev is not None and prev.input_fingerprint == fp and cfg.mode != "resegment":
        log.info("章节 %s 指纹未变，复用 v%s", chapter.id, prev.version)
        return prev

    keep_blocks, keep_scenes = ({}, {})
    if prev is not None and cfg.keep_human_edits:
        keep_blocks, keep_scenes = _human_edits(db, prev)

    system = get_prompt(db, "script_build_system")
    chunks = _split_for_llm(chapter.content)
    all_scenes: list[dict] = []
    usage_total = {"cost": 0.0, "tokens": 0}

    for idx, chunk in enumerate(chunks):
        user = SCRIPT_BUILD_USER.format(
            chapter_title=chapter.title or f"第 {chapter.order_no} 章",
            language=chapter.novel_id and "原文语言见小说设置" or "zh-CN",
            granularity=cfg.scene_granularity,
            content=chunk,
        )
        if len(chunks) > 1:
            user += f"\n\n（本章共 {len(chunks)} 段，这是第 {idx + 1} 段。场景序号从 1 开始即可，系统会统一重排。）"

        task = submit_task(
            db, Capability.text_chat,
            {
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.3,
                "max_tokens": 8192,
                "response_format": {"type": "json_schema", "schema": SCRIPT_SCHEMA},
            },
            purpose="script", sync=True,
            ref_kind="script", ref_id=chapter.id,
            novel_id=chapter.novel_id, chapter_id=chapter.id,
        )
        if task.error_json:
            raise RuntimeError(f"剧本生成失败: {task.error_json.get('message')}")

        payload = (task.result_json or {}).get("json")
        if payload is None:
            raw = (task.result_json or {}).get("text") or ""
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"模型未返回可解析 JSON: {raw[:200]}") from exc

        all_scenes.extend(payload.get("scenes") or [])
        u = task.usage_json or {}
        usage_total["cost"] += float(u.get("cost") or 0)
        usage_total["tokens"] += int((u.get("tokens") or {}).get("total") or 0)

    if not all_scenes:
        raise RuntimeError("模型未返回任何场景")

    # ── 落库 ──────────────────────────────────────────────
    doc = ScriptDoc(
        id=new_id("sd"),
        chapter_id=chapter.id,
        version=_next_version(db, chapter.id),
        status=DocStatus.active,
        input_fingerprint=fp,
        generator_meta={
            "chunks": len(chunks),
            "granularity": cfg.scene_granularity,
            "cost": round(usage_total["cost"], 6),
            "tokens": usage_total["tokens"],
            "inherited_edits": len(keep_blocks) + len(keep_scenes),
        },
    )
    db.add(doc)
    db.flush()

    seq = 0
    block_count = 0
    dialogue_count = 0
    for s_order, raw_scene in enumerate(all_scenes, start=1):
        inherited = keep_scenes.get(s_order)
        scene = Scene(
            id=new_id("sc"),
            script_doc_id=doc.id,
            order_no=s_order,
            title=(inherited.title if inherited else raw_scene.get("title")) or None,
            time_of_day=(inherited.time_of_day if inherited else raw_scene.get("time_of_day")) or None,
            location_text=(inherited.location_text if inherited else raw_scene.get("location_text")) or None,
            weather=(inherited.weather if inherited else raw_scene.get("weather")) or None,
            mood=(inherited.mood if inherited else raw_scene.get("mood")) or None,
            summary=(inherited.summary if inherited else raw_scene.get("summary")) or None,
            edited_by_human=bool(inherited),
        )
        if inherited:
            scene.bg_asset_id = inherited.bg_asset_id
            scene.bgm_asset_id = inherited.bgm_asset_id
            scene.ambience_asset_id = inherited.ambience_asset_id
        db.add(scene)
        db.flush()

        for raw_block in raw_scene.get("blocks") or []:
            norm = _normalize_block(raw_block)
            if norm is None:
                continue
            block_type, text, speaker = norm
            seq += 1
            keep = keep_blocks.get(seq)
            if keep is not None:
                # 人工编辑优先，AI 结果丢弃
                block_type, text, speaker = keep.block_type, keep.source_text, keep.speaker_tag
            db.add(ScriptBlock(
                id=new_id("sb"),
                script_doc_id=doc.id,
                scene_id=scene.id,
                seq_no=seq,
                block_type=block_type,
                source_text=text,
                speaker_tag=speaker,
                speaker_entity_id=keep.speaker_entity_id if keep else None,
                edited_by_human=keep is not None,
            ))
            block_count += 1
            if block_type == BlockType.dialogue:
                dialogue_count += 1

    doc.stats_json = {
        "scenes": len(all_scenes),
        "blocks": block_count,
        "dialogues": dialogue_count,
    }

    if prev is not None:
        prev.status = DocStatus.archived
    db.flush()
    log.info(
        "章节 %s 生成剧本 v%s：%s 场景 %s 块（继承 %s 处人工编辑）",
        chapter.id, doc.version, len(all_scenes), block_count,
        len(keep_blocks) + len(keep_scenes),
    )
    return doc
